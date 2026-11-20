"""Ứng dụng cờ vua: đánh giá kín khi chơi, phân tích sâu khi xem lại PGN."""

from __future__ import annotations

import io
import math
import os
import queue
import re
import shutil
import sys
import threading
import tkinter as tk
from collections import Counter, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

try:
    import chess
    import chess.engine
    import chess.pgn
except ImportError:
    messagebox.showerror("Thiếu thư viện", "Cài python-chess bằng lệnh:\npython -m pip install python-chess")
    raise SystemExit(2)


PIECES = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}
APP_HOME = Path("D:/Chess")
GAMES_DIR = APP_HOME / "data" / "games"
REPORTS_DIR = APP_HOME / "data" / "reports"
SQUARE = 64
BOARD_SIZE = 8 * SQUARE


def local_filename(name: str, extension: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*]+', "_", Path(name).stem).strip(" ._") or "van-co"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stem}-{stamp}-{uuid4().hex[:6]}{extension}"


def save_local_pgn(content: str, name: str) -> Path:
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    target = GAMES_DIR / local_filename(name, ".pgn")
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    return target


def resolve_engine(value: str) -> str:
    found = shutil.which(value)
    if found:
        return found
    path = Path(value.strip('"')).expanduser()
    if path.is_file():
        return str(path.resolve())
    raise FileNotFoundError("Chưa tìm thấy Stockfish. Hãy chọn tệp stockfish.exe.")


def grade(loss: int, exact_best: bool, full: bool) -> str:
    if full and exact_best:
        return "Tốt nhất (Best Move)"
    if loss <= 20:
        return "Rất tốt"
    if loss <= 50:
        return "Tốt"
    if loss <= 100:
        return "Chưa chính xác"
    if loss <= 250:
        return "Sai lầm"
    return "Sai lầm lớn"


def score_text(score: chess.engine.Score) -> str:
    mate = score.mate()
    if mate is not None:
        return f"M{mate:+d}"
    cp = score.score()
    return f"{cp / 100:+.2f}" if cp is not None else "?"


def variation_text(board: chess.Board, moves: list[chess.Move], max_plies: int = 6) -> str:
    sample = moves[:max_plies]
    return board.variation_san(sample) if sample else ""


def analyze(
    engine_path: str,
    before: chess.Board | None,
    played_move: chess.Move | None,
    current: chess.Board,
    full: bool,
    seconds: float,
) -> dict:
    result: dict = {"grade": "", "detail": "", "score": None, "best_prior": "", "lines": []}
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        engine.configure({
            "Threads": max(1, os.cpu_count() or 1) if full else 1,
            "Hash": 256 if full else 32,
        })
        limit = chess.engine.Limit(time=seconds)
        if before is not None and played_move is not None:
            info_level = chess.engine.INFO_SCORE | (chess.engine.INFO_PV if full else 0)
            best_info = engine.analyse(before, limit, info=info_level)
            played_info = engine.analyse(
                before, limit, info=chess.engine.INFO_SCORE, root_moves=[played_move]
            )
            best_score = best_info["score"].pov(before.turn)
            played_score = played_info["score"].pov(before.turn)
            best_cp = best_score.score(mate_score=100_000)
            played_cp = played_score.score(mate_score=100_000)
            if best_cp is None or played_cp is None:
                raise RuntimeError("Stockfish không trả về điểm đánh giá.")
            loss = max(0, best_cp - played_cp)
            best_pv = best_info.get("pv", []) if full else []
            exact_best = bool(best_pv and best_pv[0] == played_move)
            result["grade"] = grade(loss, exact_best, full)
            result["detail"] = (
                "Thế chiếu hết" if best_score.is_mate() or played_score.is_mate()
                else f"Độ lệch: {loss} cp"
            )
            result["score"] = played_info["score"].pov(chess.WHITE)
            if best_pv:
                result["best_prior"] = before.san(best_pv[0])
        elif not current.is_game_over():
            current_info = engine.analyse(current, limit, info=chess.engine.INFO_SCORE)
            result["score"] = current_info["score"].pov(chess.WHITE)

        if full and not current.is_game_over():
            lines = engine.analyse(
                current, limit, multipv=min(3, current.legal_moves.count()),
                info=chess.engine.INFO_SCORE | chess.engine.INFO_PV,
            )
            for item in lines:
                pv = item.get("pv", [])
                if pv:
                    result["lines"].append((
                        score_text(item["score"].pov(chess.WHITE)),
                        variation_text(current, pv),
                    ))
            if lines:
                result["score"] = lines[0]["score"].pov(chess.WHITE)
    return result


def game_phase(board: chess.Board) -> str:
    if board.fullmove_number <= 12:
        return "Khai cuộc"
    if len(board.piece_map()) <= 12:
        return "Tàn cuộc"
    return "Trung cuộc"


def compute_stats(
    games: list[chess.pgn.Game], player: str, engine_path: str,
    seconds: float, progress: queue.Queue, cancel: threading.Event, generation: int,
) -> dict:
    matching = [g for g in games if player.casefold() in (
        g.headers.get("White", "").casefold(), g.headers.get("Black", "").casefold()
    )]
    if not matching:
        raise ValueError(f"Không có ván nào của {player} trong PGN đã mở.")
    total = 0
    for game in matching:
        count_board = game.board()
        for move in game.mainline_moves():
            side = "White" if count_board.turn else "Black"
            if game.headers.get(side, "").casefold() == player.casefold():
                total += 1
            count_board.push(move)
    rows: list[dict] = []
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        engine.configure({"Threads": 1, "Hash": 64})
        for game in matching:
            board = game.board()
            for move in game.mainline_moves():
                if cancel.is_set():
                    return {"cancelled": True}
                side = "White" if board.turn == chess.WHITE else "Black"
                if game.headers.get(side, "").casefold() == player.casefold():
                    limit = chess.engine.Limit(time=seconds)
                    best = engine.analyse(board, limit, info=chess.engine.INFO_SCORE | chess.engine.INFO_PV)
                    played = engine.analyse(board, limit, info=chess.engine.INFO_SCORE, root_moves=[move])
                    best_score = best["score"].pov(board.turn)
                    played_score = played["score"].pov(board.turn)
                    best_cp = best_score.score(mate_score=100_000)
                    played_cp = played_score.score(mate_score=100_000)
                    if best_cp is None or played_cp is None:
                        raise RuntimeError("Stockfish không trả về điểm đánh giá.")
                    loss = max(0, best_cp - played_cp)
                    exact = bool(best.get("pv") and best["pv"][0] == move)
                    rows.append({
                        "phase": game_phase(board), "color": "Trắng" if board.turn else "Đen",
                        "grade": grade(loss, exact, True),
                        "loss": min(loss, 1000),
                        "mate": best_score.is_mate() or played_score.is_mate(),
                    })
                    progress.put((generation, "progress", len(rows), total))
                board.push(move)
    return {"player": player, "games": len(matching), "rows": rows}


def format_stats(stats: dict) -> str:
    rows = stats["rows"]
    if not rows:
        return "Không có nước đi nào để thống kê."
    counts = Counter(row["grade"] for row in rows)
    average = sum(row["loss"] for row in rows) / len(rows)
    good = sum(counts[name] for name in ("Tốt nhất (Best Move)", "Rất tốt", "Tốt"))
    lines = [
        f"THỐNG KÊ NÂNG CAO — {stats['player']}",
        f"{stats['games']} ván · {len(rows)} nước · {good / len(rows):.0%} nước tốt",
        f"Độ lệch trung bình: {average:.0f} cp",
        "",
        "PHÂN LOẠI NƯỚC ĐI",
    ]
    for name in ("Tốt nhất (Best Move)", "Rất tốt", "Tốt", "Chưa chính xác", "Sai lầm", "Sai lầm lớn"):
        lines.append(f"  {name}: {counts[name]} ({counts[name] / len(rows):.0%})")
    lines.extend(["", "THEO GIAI ĐOẠN"])
    phase_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        phase_groups[row["phase"]].append(row)
    for name in ("Khai cuộc", "Trung cuộc", "Tàn cuộc"):
        group = phase_groups[name]
        if group:
            avg = sum(row["loss"] for row in group) / len(group)
            lines.append(f"  {name}: {len(group)} nước, lệch TB {avg:.0f} cp")
    lines.extend(["", "THEO MÀU QUÂN"])
    for name in ("Trắng", "Đen"):
        group = [row for row in rows if row["color"] == name]
        if group:
            avg = sum(row["loss"] for row in group) / len(group)
            lines.append(f"  {name}: {len(group)} nước, lệch TB {avg:.0f} cp")
    enough = [(name, sum(row["loss"] for row in group) / len(group))
              for name, group in phase_groups.items() if len(group) >= 5]
    lines.extend(["", "ĐIỂM MẠNH / ĐIỂM CẦN LUYỆN"])
    if len(enough) >= 2:
        lines.append(f"  Mạnh nhất: {min(enough, key=lambda item: item[1])[0]}")
        lines.append(f"  Cần luyện thêm: {max(enough, key=lambda item: item[1])[0]}")
    else:
        lines.append("  Cần thêm ván để so sánh các giai đoạn.")
    lines.extend(["", "Ghi chú: Phân loại là ước lượng riêng, không trùng Game Review của Chess.com.",
                  "Khai cuộc: 12 lượt đầu; tàn cuộc: còn tối đa 12 quân trên bàn.",
                  "Các tình huống chiếu hết được giới hạn 1000 cp khi tính trung bình."])
    return "\n".join(lines)


class ChessReviewApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Stockfish · Đánh giá nước đi")
        self.root.geometry("1120x750")
        self.root.minsize(980, 680)
        self._set_style()
        piece_folder = Path(__file__).resolve().parent / "pieces"
        self.piece_images = {
            (color, piece): tk.PhotoImage(file=str(piece_folder / f"{color}{piece}.png"))
            for color in "wb" for piece in "KQRBNP"
            if (piece_folder / f"{color}{piece}.png").is_file()
        }
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.stats_executor = ThreadPoolExecutor(max_workers=1)
        self.results: queue.Queue[tuple[int, Future]] = queue.Queue()
        self.stats_events: queue.Queue = queue.Queue()
        self.stats_cancel = threading.Event()
        self.stats_window: tk.Toplevel | None = None
        self.stats_generation = 0
        self.future: Future | None = None
        self.generation = 0
        self.reviewing = False
        self.full = False
        self.flipped = False
        self.selected_square: int | None = None
        self.games: list[chess.pgn.Game] = []
        self.manual_save_path: Path | None = None
        self.moves: list[chess.Move] = []
        self.positions: list[chess.Board] = [chess.Board()]
        self.ply = 0
        self.engine_var = tk.StringVar(value=str(APP_HOME / "engine" / "stockfish.exe"))
        self.seconds_var = tk.StringVar(value="2")
        self.status_var = tk.StringVar(value="Tự đi cả hai bên hoặc dán PGN; dữ liệu lưu trong D:\\Chess\\data.")
        self.grade_var = tk.StringVar(value="Chưa có nước đi")
        self.detail_var = tk.StringVar(value="")
        self.eval_var = tk.StringVar(value="0.00")
        self.game_var = tk.StringVar(value="")
        self._build_ui()
        self._render_board()
        self._draw_bar(None)
        self.root.after(100, self._poll_results)
        self.root.after(100, self._poll_stats)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _set_style(self) -> None:
        self.root.configure(bg="#211f1c")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#211f1c")
        style.configure("TLabel", background="#211f1c", foreground="#ede9e1",
                        font=("Segoe UI", 10))
        style.configure("TButton", background="#3b3833", foreground="#f5f2eb",
                        bordercolor="#4d4943", padding=(10, 7), font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#4b4740"), ("disabled", "#302e2a")],
                  foreground=[("disabled", "#848078")])
        style.configure("Accent.TButton", background="#81b64c", foreground="#101a0c",
                        bordercolor="#81b64c", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#9bcc61")])
        style.configure("TEntry", fieldbackground="#33302c", foreground="#f5f2eb",
                        insertcolor="#f5f2eb", bordercolor="#5a554c")
        style.configure("TCombobox", fieldbackground="#33302c", foreground="#f5f2eb",
                        background="#33302c")
        style.configure("TLabelframe", background="#211f1c", bordercolor="#524c43")
        style.configure("TLabelframe.Label", background="#211f1c", foreground="#a8d77a",
                        font=("Segoe UI", 10, "bold"))
        style.configure("TSeparator", background="#4a453e")

    def _build_ui(self) -> None:
        heading = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        heading.pack(fill="x")
        ttk.Label(heading, text="STOCKFISH REVIEW", font=("Segoe UI", 18, "bold"),
                  foreground="#a8d77a").pack(side="left")
        ttk.Label(heading, text="Tự đi cả hai bên · chỉ bật gợi ý khi xem lại",
                  foreground="#aaa49a").pack(side="left", padx=16)
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Stockfish:").pack(side="left")
        ttk.Entry(top, textvariable=self.engine_var, width=48).pack(side="left", padx=5)
        ttk.Button(top, text="Chọn tệp…", command=self._choose_engine).pack(side="left")
        ttk.Button(top, text="Mở PGN…", command=self._open_pgn).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Dán PGN…", command=self._paste_pgn,
                   style="Accent.TButton").pack(side="left", padx=5)
        ttk.Button(top, text="Ván mới", command=self._new_game).pack(side="left", padx=6)

        main = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        main.pack(fill="both", expand=True)
        left = ttk.Frame(main)
        left.pack(side="left", fill="y")
        self.bar = tk.Canvas(left, width=40, height=BOARD_SIZE, highlightthickness=1,
                             highlightbackground="#645b50", bg="#252525")
        self.bar.pack(side="left", padx=(0, 8))
        self.board_canvas = tk.Canvas(left, width=BOARD_SIZE, height=BOARD_SIZE,
                                      highlightthickness=1, highlightbackground="#645b50")
        self.board_canvas.pack(side="left")
        self.board_canvas.bind("<Button-1>", self._click_board)

        right = ttk.Frame(main, padding=(14, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, textvariable=self.game_var, font=("Segoe UI", 11, "bold"),
                  wraplength=440).pack(anchor="w")
        controls = ttk.Frame(right)
        controls.pack(fill="x", pady=(8, 5))
        ttk.Button(controls, text="◀", width=5, command=lambda: self._go_to(self.ply - 1)).pack(side="left")
        ttk.Button(controls, text="▶", width=5, command=lambda: self._go_to(self.ply + 1)).pack(side="left", padx=4)
        ttk.Button(controls, text="Lật bàn", command=self._flip).pack(side="left", padx=4)
        self.review_button = ttk.Button(controls, text="Xem lại", command=self._review_manual, state="disabled")
        self.review_button.pack(side="left", padx=4)

        self.move_list = tk.Listbox(right, height=10, font=("Consolas", 10), exportselection=False,
                                    bg="#302d29", fg="#f2eee8", selectbackground="#729e42",
                                    selectforeground="#ffffff", borderwidth=0, highlightthickness=0)
        self.move_list.pack(fill="x")
        self.move_list.bind("<<ListboxSelect>>", self._select_move)
        entry_row = ttk.Frame(right)
        entry_row.pack(fill="x", pady=(8, 0))
        ttk.Label(entry_row, text="Nhập nước SAN/UCI:").pack(side="left")
        self.move_entry = ttk.Entry(entry_row)
        self.move_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.move_entry.bind("<Return>", self._enter_move)
        self.play_button = ttk.Button(entry_row, text="Đi", command=self._enter_move,
                                      style="Accent.TButton")
        self.play_button.pack(side="left")

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Đánh giá nước vừa đi", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.grade_var, font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(5, 0))
        ttk.Label(right, textvariable=self.detail_var).pack(anchor="w")
        ttk.Label(right, text="Thanh đánh giá: Đen ở trên, Trắng ở dưới").pack(anchor="w", pady=(6, 0))
        ttk.Label(right, textvariable=self.eval_var).pack(anchor="w")

        full_row = ttk.Frame(right)
        full_row.pack(fill="x", pady=(14, 5))
        self.full_button = ttk.Button(full_row, text="Bật Full công suất", command=self._toggle_full,
                                      state="disabled", style="Accent.TButton")
        self.full_button.pack(side="left")
        self.stats_button = ttk.Button(full_row, text="Thống kê nâng cao", command=self._open_stats, state="disabled")
        self.stats_button.pack(side="left", padx=(7, 0))
        ttk.Label(full_row, text="Giây/vị trí:").pack(side="left", padx=(10, 3))
        ttk.Combobox(full_row, textvariable=self.seconds_var, values=("1", "2", "5", "10"),
                     width=4, state="readonly").pack(side="left")
        self.full_frame = ttk.LabelFrame(right, text="Phân tích sâu", padding=8)
        self.full_text = tk.Text(self.full_frame, height=8, wrap="word", font=("Segoe UI", 10),
                                 state="disabled", bg="#302d29", fg="#f2eee8",
                                 borderwidth=0, highlightthickness=0)
        self.full_text.pack(fill="both", expand=True)
        ttk.Label(right, textvariable=self.status_var, wraplength=420).pack(anchor="w", pady=(10, 0))

    def _choose_engine(self) -> None:
        path = filedialog.askopenfilename(title="Chọn stockfish.exe", filetypes=[("Ứng dụng", "*.exe"), ("Tất cả", "*.*")])
        if path:
            self.engine_var.set(path)
            self._request_analysis()

    def _open_pgn(self) -> None:
        path = filedialog.askopenfilename(title="Mở ván cờ PGN", filetypes=[("PGN", "*.pgn"), ("Tất cả", "*.*")])
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8-sig")
            games = self._parse_pgn(content)
            source = Path(path).resolve()
            stored = source if source.parent == GAMES_DIR.resolve() else save_local_pgn(content, source.name)
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("Không mở được PGN", str(exc))
            return
        self._load_pgn_games(games, stored.name)

    @staticmethod
    def _parse_pgn(content: str) -> list[chess.pgn.Game]:
        games = []
        stream = io.StringIO(content)
        while (game := chess.pgn.read_game(stream)) is not None:
            if game.errors:
                raise ValueError(str(game.errors[0]))
            games.append(game)
        if not games:
            raise ValueError("Không tìm thấy ván cờ PGN hợp lệ.")
        return games

    def _paste_pgn(self) -> None:
        popup = tk.Toplevel(self.root)
        popup.configure(bg="#211f1c")
        popup.title("Dán mã PGN")
        popup.geometry("680x480")
        ttk.Label(popup, text="Dán mã PGN đã sao chép. Ván sẽ lưu tại D:\\Chess\\data\\games.",
                  padding=10).pack(anchor="w")
        editor = tk.Text(popup, wrap="word", font=("Consolas", 10),
                         bg="#302d29", fg="#f2eee8", insertbackground="#f2eee8")
        editor.pack(fill="both", expand=True, padx=10)

        def save_and_open() -> None:
            content = editor.get("1.0", "end").strip()
            try:
                games = self._parse_pgn(content)
            except ValueError as exc:
                messagebox.showerror("PGN không hợp lệ", str(exc), parent=popup)
                return
            try:
                stored = save_local_pgn(content, "van-co")
            except OSError as exc:
                messagebox.showerror("Không lưu được", str(exc), parent=popup)
                return
            popup.destroy()
            self._load_pgn_games(games, stored.name)

        ttk.Button(popup, text="Lưu vào D:\\Chess và mở", command=save_and_open).pack(pady=10)

    def _load_pgn_games(self, games: list[chess.pgn.Game], source_name: str) -> None:
        self.games = games
        self._load_game(games[0])
        self.status_var.set(f"Đã lưu {len(games)} ván trong D:\\Chess\\data\\games ({source_name}).")
        if len(games) > 1:
            self._choose_game_dialog()

    def _choose_game_dialog(self) -> None:
        popup = tk.Toplevel(self.root)
        popup.configure(bg="#211f1c")
        popup.title("Chọn ván")
        popup.geometry("380x300")
        listing = tk.Listbox(popup)
        listing.pack(fill="both", expand=True, padx=10, pady=10)
        for index, game in enumerate(self.games, 1):
            listing.insert("end", f"{index}. {game.headers.get('White', '?')} – {game.headers.get('Black', '?')}")
        listing.selection_set(0)

        def choose() -> None:
            selection = listing.curselection()
            if selection:
                self._load_game(self.games[selection[0]])
            popup.destroy()

        ttk.Button(popup, text="Mở ván", command=choose).pack(pady=(0, 10))
        listing.bind("<Double-Button-1>", lambda _event: choose())

    def _load_game(self, game: chess.pgn.Game) -> None:
        self.manual_save_path = None
        self.moves = list(game.mainline_moves())
        board = game.board()
        self.positions = [board.copy(stack=True)]
        for move in self.moves:
            board.push(move)
            self.positions.append(board.copy(stack=True))
        self.ply = len(self.moves)
        self.reviewing = True
        self.full = False
        self.full_frame.pack_forget()
        self.full_button.configure(text="Bật Full công suất", state="normal")
        self.stats_button.configure(state="normal")
        self.review_button.configure(state="disabled")
        self.move_entry.configure(state="disabled")
        self.play_button.configure(state="disabled")
        self.game_var.set(f"{game.headers.get('White', 'Trắng')} – {game.headers.get('Black', 'Đen')}")
        self._fill_moves()
        self._refresh()

    def _new_game(self) -> None:
        self.games = []
        self.manual_save_path = None
        self.moves = []
        self.positions = [chess.Board()]
        self.ply = 0
        self.reviewing = False
        self.full = False
        self.selected_square = None
        self.full_frame.pack_forget()
        self.full_button.configure(text="Bật Full công suất", state="disabled")
        self.stats_button.configure(state="disabled")
        self.review_button.configure(state="disabled")
        self.move_entry.configure(state="normal")
        self.play_button.configure(state="normal")
        self.move_list.delete(0, "end")
        self.game_var.set("Ván mới")
        self._refresh()

    def _review_manual(self) -> None:
        if not self.positions[-1].is_game_over():
            return
        game = chess.pgn.Game.from_board(self.positions[-1])
        game.headers["White"] = "Trắng"
        game.headers["Black"] = "Đen"
        self.games = [game]
        self.reviewing = True
        self.full_button.configure(state="normal")
        self.stats_button.configure(state="normal")
        self.review_button.configure(state="disabled")
        self.move_entry.configure(state="disabled")
        self.play_button.configure(state="disabled")
        self._refresh()

    def _fill_moves(self) -> None:
        self.move_list.delete(0, "end")
        for index, move in enumerate(self.moves):
            board = self.positions[index]
            prefix = f"{board.fullmove_number}{'.' if board.turn else '...'}"
            self.move_list.insert("end", f"{prefix} {board.san(move)}")

    def _select_move(self, _event: tk.Event) -> None:
        if not self.reviewing:
            return
        selection = self.move_list.curselection()
        if selection and self.ply != selection[0] + 1:
            self._go_to(selection[0] + 1)

    def _go_to(self, ply: int) -> None:
        if not self.reviewing:
            return
        self.ply = max(0, min(ply, len(self.moves)))
        self._refresh()

    def _flip(self) -> None:
        self.flipped = not self.flipped
        self._render_board()

    def _click_board(self, event: tk.Event) -> None:
        if self.reviewing or self.positions[-1].is_game_over():
            return
        file_index = event.x // SQUARE
        rank_index = event.y // SQUARE
        if not 0 <= file_index < 8 or not 0 <= rank_index < 8:
            return
        file_ = 7 - file_index if self.flipped else file_index
        rank_ = rank_index if self.flipped else 7 - rank_index
        square = chess.square(file_, rank_)
        board = self.positions[-1]
        if self.selected_square is not None:
            move = chess.Move(self.selected_square, square)
            if board.piece_at(self.selected_square) and board.piece_at(self.selected_square).piece_type == chess.PAWN:
                if chess.square_rank(square) in (0, 7):
                    move = chess.Move(self.selected_square, square, promotion=chess.QUEEN)
            if move in board.legal_moves:
                self.selected_square = None
                self._play_move(move)
                return
        piece = board.piece_at(square)
        self.selected_square = square if piece and piece.color == board.turn else None
        self._render_board()

    def _enter_move(self, _event: tk.Event | None = None) -> None:
        if self.reviewing:
            return
        raw = self.move_entry.get().strip()
        if not raw:
            return
        board = self.positions[-1]
        try:
            move = board.parse_san(raw)
        except ValueError:
            try:
                move = chess.Move.from_uci(raw.lower())
                if move not in board.legal_moves:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Nước đi không hợp lệ", f"Không hiểu nước đi: {raw}")
                return
        self.move_entry.delete(0, "end")
        self._play_move(move)

    def _play_move(self, move: chess.Move) -> None:
        board = self.positions[-1].copy(stack=True)
        self.moves.append(move)
        board.push(move)
        self.positions.append(board)
        self.ply = len(self.moves)
        self._fill_moves()
        try:
            GAMES_DIR.mkdir(parents=True, exist_ok=True)
            if self.manual_save_path is None:
                self.manual_save_path = GAMES_DIR / local_filename("van-tu-choi", ".pgn")
            saved_game = chess.pgn.Game.from_board(board)
            saved_game.headers["White"] = "Trắng"
            saved_game.headers["Black"] = "Đen"
            self.manual_save_path.write_text(str(saved_game) + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Không lưu được ván", str(exc))
        if board.is_game_over():
            self.review_button.configure(state="normal")
            self.status_var.set("Ván đã kết thúc. Bấm Xem lại để bật phân tích sâu.")
        self._refresh()

    def _toggle_full(self) -> None:
        if not self.reviewing:
            return
        self.full = not self.full
        self.full_button.configure(text="Tắt Full công suất" if self.full else "Bật Full công suất")
        if self.full:
            self.full_frame.pack(fill="both", expand=True, pady=(0, 5))
        else:
            self.full_frame.pack_forget()
        self._request_analysis()

    def _open_stats(self) -> None:
        if not self.games:
            return
        if self.stats_window is not None and self.stats_window.winfo_exists():
            self.stats_window.lift()
            return
        popup = tk.Toplevel(self.root)
        popup.configure(bg="#211f1c")
        popup.title("Thống kê nâng cao")
        popup.geometry("660x650")
        self.stats_window = popup
        players = sorted({name for game in self.games
                          for name in (game.headers.get("White", ""), game.headers.get("Black", "")) if name})
        player_var = tk.StringVar(value=players[0] if players else "")
        time_var = tk.StringVar(value="0.25")
        self.stats_status_var = tk.StringVar(value="Chọn tên người chơi và bấm Phân tích.")
        row = ttk.Frame(popup, padding=10)
        row.pack(fill="x")
        ttk.Label(row, text="Người chơi:").pack(side="left")
        ttk.Combobox(row, textvariable=player_var, values=players, width=22).pack(side="left", padx=5)
        ttk.Label(row, text="Giây/vị trí:").pack(side="left", padx=(10, 3))
        ttk.Combobox(row, textvariable=time_var, values=("0.1", "0.25", "0.5", "1"),
                     width=5, state="readonly").pack(side="left")
        self.stats_report = tk.Text(popup, wrap="word", font=("Consolas", 10), state="disabled",
                                    bg="#302d29", fg="#f2eee8", borderwidth=0)
        self.stats_report.pack(fill="both", expand=True, padx=10, pady=5)
        ttk.Label(popup, textvariable=self.stats_status_var, padding=(10, 3)).pack(anchor="w")
        buttons = ttk.Frame(popup, padding=10)
        buttons.pack(fill="x")

        def start() -> None:
            try:
                path = resolve_engine(self.engine_var.get())
                seconds = float(time_var.get())
                if seconds <= 0:
                    raise ValueError("Thời gian phải lớn hơn 0.")
            except (FileNotFoundError, ValueError) as exc:
                messagebox.showerror("Không thể phân tích", str(exc), parent=popup)
                return
            self.stats_generation += 1
            generation = self.stats_generation
            self.stats_cancel = threading.Event()
            start_button.configure(state="disabled")
            self.stats_status_var.set("Đang phân tích…")
            self.stats_report.configure(state="normal")
            self.stats_report.delete("1.0", "end")
            self.stats_report.configure(state="disabled")
            future = self.stats_executor.submit(
                compute_stats, self.games[:], player_var.get().strip(), path,
                seconds, self.stats_events, self.stats_cancel, generation,
            )
            future.add_done_callback(
                lambda finished: self.stats_events.put((generation, "done", finished))
            )

        def save_report() -> None:
            content = self.stats_report.get("1.0", "end").strip()
            if not content:
                return
            try:
                REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                path = REPORTS_DIR / local_filename(player_var.get().strip() or "thong-ke", ".txt")
                path.write_text(content + "\n", encoding="utf-8")
                self.stats_status_var.set(f"Đã lưu: {path}")
            except OSError as exc:
                messagebox.showerror("Không lưu được", str(exc), parent=popup)

        start_button = ttk.Button(buttons, text="Phân tích", command=start)
        start_button.pack(side="left")
        self.stats_start_button = start_button
        ttk.Button(buttons, text="Lưu báo cáo…", command=save_report).pack(side="left", padx=8)

        def close() -> None:
            self.stats_cancel.set()
            self.stats_generation += 1
            popup.destroy()
            self.stats_window = None

        popup.protocol("WM_DELETE_WINDOW", close)

    def _poll_stats(self) -> None:
        try:
            while True:
                event = self.stats_events.get_nowait()
                generation, kind = event[:2]
                if generation != self.stats_generation or self.stats_window is None:
                    continue
                if kind == "progress":
                    self.stats_status_var.set(f"Đã phân tích {event[2]}/{event[3]} nước…")
                else:
                    future = event[2]
                    self.stats_start_button.configure(state="normal")
                    try:
                        result = future.result()
                        report = format_stats(result) if not result.get("cancelled") else "Đã hủy."
                    except Exception as exc:
                        report = f"Không thể thống kê: {exc}"
                    self.stats_report.configure(state="normal")
                    self.stats_report.delete("1.0", "end")
                    self.stats_report.insert("1.0", report)
                    self.stats_report.configure(state="disabled")
                    self.stats_status_var.set("Hoàn tất. Bấm Lưu báo cáo để lưu trong D:\\Chess\\data\\reports.")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_stats)

    def _refresh(self) -> None:
        self.selected_square = None
        self._render_board()
        self.move_list.selection_clear(0, "end")
        if self.ply:
            self.move_list.selection_set(self.ply - 1)
            self.move_list.see(self.ply - 1)
        self.grade_var.set("Đang phân tích…" if self.ply else "Vị trí ban đầu")
        self.detail_var.set("")
        self._draw_bar(None)
        self._request_analysis()

    def _render_board(self) -> None:
        self.board_canvas.delete("all")
        board = self.positions[self.ply]
        previous = self.moves[self.ply - 1] if self.ply else None
        for row in range(8):
            for col in range(8):
                file_ = 7 - col if self.flipped else col
                rank_ = row if self.flipped else 7 - row
                sq = chess.square(file_, rank_)
                color = "#f0d9b5" if (file_ + rank_) % 2 else "#b58863"
                if previous and sq in (previous.from_square, previous.to_square):
                    color = "#cdd26a" if (file_ + rank_) % 2 else "#a6ad55"
                if sq == self.selected_square:
                    color = "#76b7dc"
                x, y = col * SQUARE, row * SQUARE
                self.board_canvas.create_rectangle(x, y, x + SQUARE, y + SQUARE,
                                                   fill=color, outline=color)
                piece = board.piece_at(sq)
                if piece:
                    icon = self.piece_images.get(("w" if piece.color else "b", piece.symbol().upper()))
                    if icon:
                        self.board_canvas.create_image(x + SQUARE / 2, y + SQUARE / 2, image=icon)
                    else:
                        self.board_canvas.create_text(x + SQUARE / 2, y + SQUARE / 2,
                                                      text=PIECES[piece.symbol()],
                                                      font=("Segoe UI Symbol", 38),
                                                      fill="#171717" if piece.color == chess.BLACK else "#ffffff")
                if col == 0:
                    self.board_canvas.create_text(x + 4, y + 4, text=str(rank_ + 1),
                                                  anchor="nw", font=("Segoe UI", 8, "bold"),
                                                  fill="#ffffff" if color == "#b58863" else "#333333")
                if row == 7:
                    self.board_canvas.create_text(x + SQUARE - 4, y + SQUARE - 3,
                                                  text=chess.FILE_NAMES[file_], anchor="se",
                                                  font=("Segoe UI", 8, "bold"),
                                                  fill="#ffffff" if color == "#b58863" else "#333333")

    def _draw_bar(self, score: chess.engine.Score | None) -> None:
        self.bar.delete("all")
        cp = score.score(mate_score=100_000) if score else 0
        if cp is None:
            cp = 0
        ratio = 1 / (1 + math.exp(-max(-1500, min(1500, cp)) / 300))
        white_height = int(BOARD_SIZE * ratio)
        self.bar.create_rectangle(0, 0, 40, BOARD_SIZE - white_height, fill="#252525", outline="")
        self.bar.create_rectangle(0, BOARD_SIZE - white_height, 40, BOARD_SIZE, fill="#f3f3f3", outline="")
        self.eval_var.set(score_text(score) if score else "0.00")

    def _request_analysis(self) -> None:
        self.generation += 1
        generation = self.generation
        if self.future is not None:
            self.future.cancel()
        try:
            path = resolve_engine(self.engine_var.get())
        except FileNotFoundError:
            self.status_var.set("Chọn stockfish.exe để bắt đầu phân tích.")
            return
        try:
            seconds = float(self.seconds_var.get()) if self.full else 0.35
        except ValueError:
            seconds = 2.0
        previous = self.positions[self.ply - 1].copy(stack=True) if self.ply else None
        move = self.moves[self.ply - 1] if self.ply else None
        current = self.positions[self.ply].copy(stack=True)
        self.status_var.set("Đang phân tích sâu…" if self.full else "Đang đánh giá nước vừa đi…")
        self.future = self.executor.submit(analyze, path, previous, move, current, self.full, seconds)
        self.future.add_done_callback(lambda future: self.results.put((generation, future)))

    def _poll_results(self) -> None:
        try:
            while True:
                generation, future = self.results.get_nowait()
                if generation != self.generation or future.cancelled():
                    continue
                try:
                    result = future.result()
                except Exception as exc:
                    self.grade_var.set("Không phân tích được")
                    self.status_var.set(str(exc))
                    continue
                self.grade_var.set(result["grade"] or "Vị trí ban đầu")
                self.detail_var.set(result["detail"])
                self._draw_bar(result["score"])
                if self.full:
                    notes = []
                    if self.ply and result["best_prior"]:
                        notes.append(f"Nước mạnh nhất ở lượt vừa qua: {result['best_prior']}")
                    if result["lines"]:
                        notes.append("Các phương án mạnh từ vị trí hiện tại:")
                        for index, (score, line) in enumerate(result["lines"], 1):
                            notes.append(f"{index}. {line}  (Trắng: {score})")
                    else:
                        notes.append("Ván đã kết thúc; không còn nước đi tiếp.")
                    self.full_text.configure(state="normal")
                    self.full_text.delete("1.0", "end")
                    self.full_text.insert("1.0", "\n".join(notes))
                    self.full_text.configure(state="disabled")
                self.status_var.set("Đã phân tích. Nhãn đánh giá là ước lượng, có thể khác Chess.com.")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    def _close(self) -> None:
        self.stats_cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.stats_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        GAMES_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        messagebox.showerror("Không tạo được thư mục D:\\Chess", str(exc))
        root.destroy()
        return
    ChessReviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
