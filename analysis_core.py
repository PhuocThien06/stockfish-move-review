"""Local Stockfish analysis shared by the GUI, statistics, and batch CLI."""

from __future__ import annotations

import math
import os
import struct
import subprocess
from pathlib import Path

import chess
import chess.engine
import chess.polyglot


LABELS = {
    "brilliant": ("!! Thiên tài", "#1eb7bd"),
    "great": ("! Rất mạnh", "#3b8edb"),
    "best": ("★ Tốt nhất", "#58ad51"),
    "excellent": ("✓ Xuất sắc", "#80ba4c"),
    "good": ("✓ Tốt", "#99bb74"),
    "book": ("▤ Theo lý thuyết", "#ab7442"),
    "forced": ("→ Bắt buộc", "#8797a0"),
    "inaccuracy": ("?! Kém chính xác", "#e6b32e"),
    "mistake": ("? Sai lầm", "#e48b39"),
    "miss": ("× Bỏ lỡ cơ hội", "#e45b4c"),
    "blunder": ("?? Sai lầm nghiêm trọng", "#d33b3b"),
}


def _load_book() -> set[int]:
    path = Path(__file__).resolve().parent / "openings" / "book_positions.bin"
    if not path.is_file():
        return set()
    data = path.read_bytes()
    return {item[0] for item in struct.iter_unpack("<Q", data)}


BOOK_POSITIONS = _load_book()


def open_engine(path: str) -> chess.engine.SimpleEngine:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return chess.engine.SimpleEngine.popen_uci(path, **options)


def configure_engine(engine: chess.engine.SimpleEngine, full: bool) -> None:
    engine.configure({
        "Threads": max(1, os.cpu_count() or 1) if full else 1,
        "Hash": 256 if full else 32,
        "UCI_ShowWDL": True,
    })


def expected_points(info: dict, color: chess.Color) -> float:
    if "wdl" in info:
        return info["wdl"].pov(color).expectation()
    score = info["score"].pov(color)
    mate = score.mate()
    if mate is not None:
        return 1.0 if mate > 0 else 0.0
    cp = score.score() or 0
    return 1 / (1 + math.exp(-max(-1500, min(1500, cp)) / 300))


def _is_book_move(board: chess.Board, move: chess.Move) -> bool:
    if not BOOK_POSITIONS or board.root().fen() != chess.STARTING_FEN:
        return False
    after = board.copy(stack=False)
    after.push(move)
    return chess.polyglot.zobrist_hash(after) in BOOK_POSITIONS


def _is_clear_sacrifice(board: chess.Board, move: chess.Move, pv: list[chess.Move]) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type not in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        return False
    if len(pv) < 2:
        return False
    after = board.copy(stack=False)
    after.push(move)
    reply = pv[1]
    target = after.piece_at(reply.to_square)
    return bool(
        after.is_capture(reply) and target is not None
        and target.color == board.turn and reply.to_square == move.to_square
    )


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

    if board.legal_moves.count() == 1:
        category = "forced"
    elif _is_book_move(board, move) and ep_loss <= 0.05:
        category = "book"
    elif (ep_loss <= 0.02 and _is_clear_sacrifice(board, move, played_pv)
          and played_ep >= 0.40 and best_ep < 0.95):
        category = "brilliant"
    elif exact_best and second_info is not None and (
        best_ep - expected_points(second_info, mover) >= 0.10
    ) and best_ep < 0.95:
        category = "great"
    elif exact_best:
        category = "best"
    elif best_ep >= 0.75 and played_ep <= 0.55 and ep_loss >= 0.10:
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
    }


def assess_move(
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
) -> dict:
    result = {
        "category": "", "detail": "", "score": None, "white_ep": 0.5,
        "best_prior": "", "lines": [], "assessment": None,
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
    elif not current.is_game_over():
        info = engine.analyse(current, chess.engine.Limit(time=seconds),
                              info=chess.engine.INFO_SCORE)
        result["score"] = info["score"].pov(chess.WHITE)
        result["white_ep"] = expected_points(info, chess.WHITE)

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
    return result


class EngineSession:
    """One Stockfish process owned by a single executor thread."""

    def __init__(self) -> None:
        self.engine: chess.engine.SimpleEngine | None = None
        self.path: str | None = None
        self.mode: bool | None = None

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
    ) -> dict:
        for attempt in range(2):
            try:
                self._ensure(path, full)
                return analyze_position(self.engine, before, move, current, full, seconds)
            except (chess.engine.EngineTerminatedError, BrokenPipeError, OSError):
                self.close()
                if attempt:
                    raise
        raise RuntimeError("Không mở được Stockfish.")
