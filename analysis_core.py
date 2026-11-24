"""Local Stockfish analysis shared by the GUI, statistics, and batch CLI."""

from __future__ import annotations

import os
import struct
import subprocess
import threading
from pathlib import Path

import chess
import chess.engine
import chess.polyglot


LABELS = {
    "brilliant": ("Brilliant", "#13aeb1"),
    "great": ("Great Move", "#147bca"),
    "best": ("Best Move", "#2b9c42"),
    "excellent": ("Excellent", "#80b927"),
    "good": ("Good", "#94bc65"),
    "book": ("Book Move", "#95612e"),
    "forced": ("Forced Move", "#47657a"),
    "inaccuracy": ("Inaccuracy", "#f4b710"),
    "mistake": ("Mistake", "#f28c16"),
    "miss": ("Miss", "#e74838"),
    "blunder": ("Blunder", "#c72027"),
}


def _load_book() -> set[int]:
    path = Path(__file__).resolve().parent / "openings" / "book_positions.bin"
    if not path.is_file():
        return set()
    data = path.read_bytes()
    return {item[0] for item in struct.iter_unpack("<Q", data)}


BOOK_POSITIONS = _load_book()


def open_engine(path: str) -> chess.engine.SimpleEngine:
    # Let the UI keep responding while a full-strength search uses every core.
    options = {"creationflags": (subprocess.CREATE_NO_WINDOW |
                                  subprocess.BELOW_NORMAL_PRIORITY_CLASS)} if os.name == "nt" else {}
    return chess.engine.SimpleEngine.popen_uci(path, **options)


def configure_engine(engine: chess.engine.SimpleEngine, full: bool) -> None:
    engine.configure({
        "Threads": max(1, os.cpu_count() or 1) if full else min(2, os.cpu_count() or 1),
        "Hash": 256 if full else 64,
        "UCI_ShowWDL": False,
    })


def expected_points(info: dict, color: chess.Color) -> float:
    score = info["score"].pov(color)
    mate = score.mate()
    if mate is not None:
        return 1.0 if mate > 0 else 0.0
    # Lichess derives this win-chance curve from played games. Stockfish's
    # UCI WDL instead models engine self-play, which exaggerates a human
    # player's expected-points loss when combined with Chess.com cutoffs.
    return score.wdl(model="lichess").expectation()


def _is_book_move(board: chess.Board, move: chess.Move) -> bool:
    if not BOOK_POSITIONS or board.root().fen() != chess.STARTING_FEN:
        return False
    after = board.copy(stack=False)
    after.push(move)
    return chess.polyglot.zobrist_hash(after) in BOOK_POSITIONS


PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9,
}


def _material_balance(board: chess.Board, color: chess.Color) -> int:
    return sum(
        PIECE_VALUES.get(piece.piece_type, 0) * (1 if piece.color == color else -1)
        for piece in board.piece_map().values()
    )


def material_offer(board: chess.Board, move: chess.Move,
                   pv: list[chess.Move]) -> dict | None:
    """Describe a captured offered piece and the mover's immediate reply."""
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type not in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        return None
    if len(pv) < 3 or pv[0] != move or move not in board.legal_moves:
        return None
    victim = board.piece_at(move.to_square)
    gained = PIECE_VALUES.get(victim.piece_type, 0) if victim else 0
    if PIECE_VALUES[piece.piece_type] - gained < 2:
        return None
    starting_balance = _material_balance(board, board.turn)
    after = board.copy(stack=False)
    after.push(move)
    reply = pv[1]
    if reply not in after.legal_moves:
        return None
    target = after.piece_at(reply.to_square)
    if not (after.is_capture(reply) and target is not None
            and target.color == board.turn and reply.to_square == move.to_square):
        return None
    reply_san = after.san(reply)
    after.push(reply)
    followup = pv[2]
    if followup not in after.legal_moves:
        return None
    followup_san = after.san(followup)
    followup_capture = after.piece_at(followup.to_square)
    after.push(followup)
    return {
        "piece_type": piece.piece_type,
        "reply_san": reply_san,
        "followup_san": followup_san,
        "followup_check": after.is_check(),
        "followup_capture_type": followup_capture.piece_type if followup_capture else None,
        "net_material_loss": starting_balance - _material_balance(after, board.turn),
    }


def available_material_offer(board: chess.Board, move: chess.Move) -> dict | None:
    """Find a legal acceptance of a piece offer even when the best PV declines it.

    A same-square recapture that restores the material balance is an exchange,
    not a sacrifice. This is only a board fact; the engine score decides whether
    the offer is sound.
    """
    piece = board.piece_at(move.from_square)
    if (piece is None or piece.piece_type not in
            (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
            or move not in board.legal_moves):
        return None
    before_balance = _material_balance(board, board.turn)
    after = board.copy(stack=False)
    after.push(move)
    if not after.is_attacked_by(after.turn, move.to_square):
        return None
    candidates = []
    for reply in after.generate_legal_captures():
        if reply.to_square != move.to_square:
            continue
        reply_san = after.san(reply)
        accepted = after.copy(stack=False)
        accepted.push(reply)
        balances = [_material_balance(accepted, piece.color)]
        for recapture in accepted.generate_legal_captures():
            if recapture.to_square == move.to_square:
                recovered = accepted.copy(stack=False)
                recovered.push(recapture)
                balances.append(_material_balance(recovered, piece.color))
        loss = before_balance - max(balances)
        if loss >= 1:
            candidates.append((loss, reply_san))
    if not candidates:
        return None
    loss, reply_san = max(candidates)
    return {"piece_type": piece.piece_type, "reply_san": reply_san,
            "net_material_loss": loss}


def classify_move(
    board: chess.Board, move: chess.Move, best_info: dict, played_info: dict,
    second_info: dict | None,
) -> dict:
    mover = board.turn
    best_ep = expected_points(best_info, mover)
    played_ep = expected_points(played_info, mover)
    ep_loss = max(0.0, best_ep - played_ep)
    best_score = best_info["score"].pov(mover)
    played_score = played_info["score"].pov(mover)
    best_cp = best_score.score(mate_score=100_000) or 0
    played_cp = played_score.score(mate_score=100_000) or 0
    cp_loss = max(0, best_cp - played_cp)
    best_pv = best_info.get("pv", [])
    played_pv = played_info.get("pv", [])
    exact_best = bool(best_pv and best_pv[0] == move)
    offer = material_offer(board, move, played_pv)
    possible_offer = available_material_offer(board, move) if offer is None else None
    second_ep = expected_points(second_info, mover) if second_info else None
    not_winning_without_move = (
        best_ep < 0.90
        or (played_score.mate() is not None and played_score.mate() > 0
            and second_ep is not None and second_ep < 0.90)
    )
    sound_sacrifice = (
        len(played_pv) >= 3
        and ((offer is not None and offer["net_material_loss"] >= 1)
             or (possible_offer is not None and possible_offer["net_material_loss"] >= 1))
        and ep_loss <= 0.03 and played_ep >= 0.38 and not_winning_without_move
    )

    if board.legal_moves.count() == 1:
        category = "forced"
    elif _is_book_move(board, move) and ep_loss <= 0.05:
        category = "book"
    elif sound_sacrifice:
        category = "brilliant"
    elif exact_best and second_ep is not None and (
        best_ep - second_ep >= 0.12
    ) and played_ep >= 0.45 and best_ep < 0.98:
        category = "great"
    elif exact_best:
        category = "best"
    elif ep_loss >= 0.10 and (
        (best_ep >= 0.75 and played_ep <= 0.55)
        or (best_score.mate() is not None and best_score.mate() > 0
            and played_score.mate() is None and played_ep < 0.75)
    ):
        category = "miss"
    elif ep_loss <= 0.02:
        category = "excellent"
    elif ep_loss <= 0.05:
        category = "good"
    elif ep_loss <= 0.10:
        category = "inaccuracy"
    elif ep_loss <= 0.20:
        category = "mistake"
    else:
        category = "blunder"

    return {
        "category": category,
        "ep_loss": ep_loss,
        "cp_loss": cp_loss,
        "white_score": played_info["score"].pov(chess.WHITE),
        "white_ep": expected_points(played_info, chess.WHITE),
        "best_prior": board.san(best_pv[0]) if best_pv else "",
        "mate": best_score.is_mate() or played_score.is_mate(),
        "best_pv": best_pv[:8],
        "played_pv": played_pv[:8],
        "best_ep": best_ep,
        "played_ep": played_ep,
        "material_offer": offer,
        "available_material_offer": possible_offer,
    }


def assess_move(
    engine: chess.engine.SimpleEngine, board: chess.Board,
    move: chess.Move, seconds: float,
) -> dict:
    result = _assess_move_once(engine, board, move, seconds)
    # A short search can mistake a tactical move for a blunder. Recheck only
    # this severe label so a long PGN overview remains responsive.
    if result["category"] == "blunder" and seconds < 1.5:
        result = _assess_move_once(engine, board, move, 1.5)
    elif result["category"] == "brilliant" and seconds < 2.0:
        result = _assess_move_once(engine, board, move, 2.0)
    return result


def _assess_move_once(
    engine: chess.engine.SimpleEngine, board: chess.Board,
    move: chess.Move, seconds: float,
) -> dict:
    limit = chess.engine.Limit(time=seconds)
    move_count = board.legal_moves.count()
    best_lines = engine.analyse(
        board, limit, multipv=min(2, move_count),
        info=chess.engine.INFO_SCORE | chess.engine.INFO_PV,
    )
    if isinstance(best_lines, dict):
        best_lines = [best_lines]
    played_info = next(
        (line for line in best_lines if line.get("pv", [None])[0] == move), None
    )
    if played_info is None:
        played_info = engine.analyse(
            board, limit, root_moves=[move],
            info=chess.engine.INFO_SCORE | chess.engine.INFO_PV,
        )
    return classify_move(
        board, move, best_lines[0], played_info,
        best_lines[1] if len(best_lines) > 1 else None,
    )


def score_text(score: chess.engine.Score) -> str:
    mate = score.mate()
    if mate is not None:
        return f"M{mate:+d}"
    cp = score.score()
    return f"{cp / 100:+.2f}" if cp is not None else "?"


def variation_text(board: chess.Board, moves: list[chess.Move], max_plies: int = 6) -> str:
    sample = moves[:max_plies]
    return board.variation_san(sample) if sample else ""


def analyze_position(
    engine: chess.engine.SimpleEngine,
    before: chess.Board | None,
    played_move: chess.Move | None,
    current: chess.Board,
    full: bool,
    seconds: float,
    show_best_arrow: bool = False,
) -> dict:
    result = {
        "category": "", "detail": "", "score": None, "white_ep": 0.5,
        "best_prior": "", "lines": [], "assessment": None,
        "next_best_move": None, "next_best_line": [],
    }
    if before is not None and played_move is not None:
        assessment = assess_move(engine, before, played_move, seconds)
        result.update({
            "category": assessment["category"],
            "score": assessment["white_score"],
            "white_ep": assessment["white_ep"],
            "best_prior": assessment["best_prior"],
            "assessment": assessment,
            "detail": (
                f"Mất {assessment['ep_loss'] * 100:.1f}% điểm kỳ vọng"
                + (" · thế chiếu hết" if assessment["mate"]
                   else f" · {assessment['cp_loss']} cp")
            ),
        })
        # The forced-root PV already contains Stockfish's reply to the move
        # just played. Reuse it for opening guidance instead of searching the
        # current board a second time during live capture.
        reply_line = assessment.get("played_pv", [])[1:]
        if reply_line and reply_line[0] in current.legal_moves:
            result["next_best_move"] = reply_line[0]
            result["next_best_line"] = reply_line[:3]
    elif not current.is_game_over():
        info = engine.analyse(current, chess.engine.Limit(time=seconds),
                              info=chess.engine.INFO_SCORE | chess.engine.INFO_PV)
        result["score"] = info["score"].pov(chess.WHITE)
        result["white_ep"] = expected_points(info, chess.WHITE)
        if info.get("pv"):
            result["next_best_move"] = info["pv"][0]
            result["next_best_line"] = info["pv"][:3]

    if full and not current.is_game_over():
        lines = engine.analyse(
            current, chess.engine.Limit(time=seconds),
            multipv=min(3, current.legal_moves.count()),
            info=chess.engine.INFO_SCORE | chess.engine.INFO_PV,
        )
        if isinstance(lines, dict):
            lines = [lines]
        for item in lines:
            pv = item.get("pv", [])
            if pv:
                result["lines"].append((
                    score_text(item["score"].pov(chess.WHITE)),
                    variation_text(current, pv),
                ))
        if lines:
            result["score"] = lines[0]["score"].pov(chess.WHITE)
            result["white_ep"] = expected_points(lines[0], chess.WHITE)
            if lines[0].get("pv"):
                result["next_best_move"] = lines[0]["pv"][0]
                result["next_best_line"] = lines[0]["pv"][:3]
    elif show_best_arrow and before is not None and not current.is_game_over():
        next_info = engine.analyse(
            current, chess.engine.Limit(time=seconds),
            info=chess.engine.INFO_SCORE | chess.engine.INFO_PV,
        )
        result["score"] = next_info["score"].pov(chess.WHITE)
        result["white_ep"] = expected_points(next_info, chess.WHITE)
        if next_info.get("pv"):
            result["next_best_move"] = next_info["pv"][0]
            result["next_best_line"] = next_info["pv"][:3]
    return result


class EngineSession:
    """One Stockfish process owned by a single executor thread."""

    def __init__(self) -> None:
        self.engine: chess.engine.SimpleEngine | None = None
        self.path: str | None = None
        self.mode: bool | None = None
        self._lock = threading.Lock()
        self._cancel: threading.Event | None = None
        self._active: chess.engine.SimpleAnalysisResult | None = None

    def interrupt(self) -> None:
        """Stop the running UCI search so the newest position can start."""
        with self._lock:
            cancel, active = self._cancel, self._active
            if cancel is not None:
                cancel.set()
        if active is not None:
            try:
                active.stop()
            except (OSError, RuntimeError, chess.engine.EngineError):
                pass

    def close(self) -> None:
        if self.engine is not None:
            try:
                self.engine.quit()
            except (OSError, chess.engine.EngineError):
                pass
        self.engine = None
        self.path = None
        self.mode = None

    def _ensure(self, path: str, full: bool) -> None:
        if self.engine is None or self.path != path:
            self.close()
            self.engine = open_engine(path)
            self.path = path
        if self.mode != full:
            configure_engine(self.engine, full)
            self.mode = full

    def run(
        self, path: str, before: chess.Board | None, move: chess.Move | None,
        current: chess.Board, full: bool, seconds: float,
        show_best_arrow: bool = False,
        preview_callback=None,
        cancel_event: threading.Event | None = None,
    ) -> dict:
        cancel = cancel_event or threading.Event()
        with self._lock:
            self._cancel = cancel
        try:
            for attempt in range(2):
                try:
                    if cancel.is_set():
                        raise InterruptedError("Đã chuyển sang vị trí mới.")
                    self._ensure(path, full)
                    proxy = _InterruptibleEngine(self, cancel)
                    if preview_callback is not None and not current.is_game_over():
                        info = proxy.analyse(current, chess.engine.Limit(time=0.15),
                                             info=chess.engine.INFO_SCORE)
                        preview_callback(info["score"].pov(chess.WHITE),
                                         expected_points(info, chess.WHITE))
                    return analyze_position(
                        proxy, before, move, current, full, seconds, show_best_arrow,
                    )
                except (chess.engine.EngineTerminatedError, BrokenPipeError, OSError):
                    self.close()
                    if attempt:
                        raise
            raise RuntimeError("Không mở được Stockfish.")
        finally:
            with self._lock:
                if self._cancel is cancel:
                    self._cancel = None
                self._active = None


class _InterruptibleEngine:
    """Synchronous engine adapter that exposes a stoppable active search."""

    def __init__(self, session: EngineSession, cancel: threading.Event) -> None:
        self.session = session
        self.cancel = cancel

    def analyse(self, board: chess.Board, limit: chess.engine.Limit, **options):
        if self.cancel.is_set():
            raise InterruptedError("Đã chuyển sang vị trí mới.")
        with self.session.engine.analysis(board, limit, **options) as analysis:
            with self.session._lock:
                self.session._active = analysis
                interrupted = self.cancel.is_set()
            if interrupted:
                analysis.stop()
            try:
                analysis.wait()
                if self.cancel.is_set():
                    raise InterruptedError("Đã chuyển sang vị trí mới.")
                return analysis.multipv if options.get("multipv") is not None else analysis.info
            finally:
                with self.session._lock:
                    if self.session._active is analysis:
                        self.session._active = None
