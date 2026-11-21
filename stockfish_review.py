"""Ứng dụng cờ vua: đánh giá kín khi chơi, phân tích sâu khi xem lại PGN."""

from __future__ import annotations

import io
import hashlib
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

from analysis_core import (
    EngineSession, LABELS, assess_move, configure_engine, open_engine, score_text,
)
from chesscom_import import sync_recent_games
from coach import explain_move
from grade_badges import draw_badge, make_badge, text_color
from local_store import load_favorites, prune_old_games, save_favorites
from live_capture import (LiveBoardTracker, WindowCaptureStream, align_board,
                          board_crop, infer_turn, reduce_glare, visible_windows)
from material import DISPLAY_ORDER, material_snapshot


PIECES = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}
COACH_MOODS = {
    "brilliant": "celebrating", "great": "celebrating",
    "best": "celebrating", "excellent": "celebrating",
    "inaccuracy": "thinking", "miss": "angry",
    "mistake": "angry", "blunder": "angry",
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
    with open_engine(engine_path) as engine:
        configure_engine(engine, False)
        for game in matching:
            board = game.board()
            for move in game.mainline_moves():
                if cancel.is_set():
                    return {"cancelled": True}
                side = "White" if board.turn == chess.WHITE else "Black"
                if game.headers.get(side, "").casefold() == player.casefold():
                    assessment = assess_move(engine, board, move, seconds)
                    rows.append({
                        "phase": game_phase(board), "color": "Trắng" if board.turn else "Đen",
                        "grade": assessment["category"],
                        "loss": min(assessment["cp_loss"], 1000),
                        "ep_loss": assessment["ep_loss"],
                        "mate": assessment["mate"],
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
    average_ep = sum(row["ep_loss"] for row in rows) / len(rows)
    good = sum(counts[name] for name in (
        "brilliant", "great", "best", "excellent", "good", "book", "forced"
    ))
    lines = [
        f"THỐNG KÊ NÂNG CAO — {stats['player']}",
        f"{stats['games']} ván · {len(rows)} nước · {good / len(rows):.0%} nước tốt",
        f"Mất điểm kỳ vọng trung bình: {average_ep * 100:.1f}%",
        f"Độ lệch trung bình: {average:.0f} cp",
        "",
        "PHÂN LOẠI NƯỚC ĐI",
    ]
    for code, (label, _color) in LABELS.items():
        lines.append(f"  {label}: {counts[code]} ({counts[code] / len(rows):.0%})")
    lines.extend(["", "THEO GIAI ĐOẠN"])
    phase_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        phase_groups[row["phase"]].append(row)
    for name in ("Khai cuộc", "Trung cuộc", "Tàn cuộc"):
        group = phase_groups[name]
        if group:
            avg = sum(row["ep_loss"] for row in group) / len(group)
            lines.append(f"  {name}: {len(group)} nước, mất {avg * 100:.1f}% điểm kỳ vọng TB")
    lines.extend(["", "THEO MÀU QUÂN"])
    for name in ("Trắng", "Đen"):
        group = [row for row in rows if row["color"] == name]
        if group:
            avg = sum(row["ep_loss"] for row in group) / len(group)
            lines.append(f"  {name}: {len(group)} nước, mất {avg * 100:.1f}% điểm kỳ vọng TB")
    enough = [(name, sum(row["ep_loss"] for row in group) / len(group))
              for name, group in phase_groups.items() if len(group) >= 5]
    lines.extend(["", "ĐIỂM MẠNH / ĐIỂM CẦN LUYỆN"])
    if len(enough) >= 2:
        lines.append(f"  Mạnh nhất: {min(enough, key=lambda item: item[1])[0]}")
        lines.append(f"  Cần luyện thêm: {max(enough, key=lambda item: item[1])[0]}")
    else:
        lines.append("  Cần thêm ván để so sánh các giai đoạn.")
    lines.extend(["", "Ghi chú: Dùng ngưỡng Expected Points của Chess.com với mô hình tỷ lệ thắng Lichess.",
                  "Các nhãn vẫn là ước lượng; Chess.com còn dùng Elo và quy tắc riêng.",
                  "Khai cuộc: 12 lượt đầu; tàn cuộc: còn tối đa 12 quân trên bàn.",
                  "Các tình huống chiếu hết được giới hạn 1000 cp khi tính trung bình."])
    return "\n".join(lines)


def compute_overview(
    game: chess.pgn.Game, engine_path: str, progress: queue.Queue,
    generation: int, cancel: threading.Event,
) -> dict:
    """Precompute the review summary and scores without blocking the window."""
    board = game.board()
    moves = list(game.mainline_moves())
    assessments: list[dict] = []
    with open_engine(engine_path) as engine:
        configure_engine(engine, False)
        for index, move in enumerate(moves, 1):
            if cancel.is_set():
                return {"cancelled": True}
            assessment = assess_move(engine, board, move, 0.45)
            assessments.append(assessment)
            progress.put((generation, "move", index, len(moves), assessment))
            board.push(move)
    return {"assessments": assessments, "total": len(moves)}


class ChessReviewApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Stockfish · Đánh giá nước đi")
        self.root.geometry("1220x770")
        self.root.minsize(1080, 680)
        if sys.platform == "win32":
            self.root.state("zoomed")
        self._set_style()
        piece_folder = Path(__file__).resolve().parent / "pieces"
        self.piece_images = {
            (color, piece): tk.PhotoImage(file=str(piece_folder / f"{color}{piece}.png"))
            for color in "wb" for piece in "KQRBNP"
            if (piece_folder / f"{color}{piece}.png").is_file()
        }
        self.capture_icons = {
            (color, piece): image.subsample(4, 4)
            for (color, piece), image in self.piece_images.items()
            if piece in "PNBRQ"
        }
        self.coach_images: dict[str, dict[str, tk.PhotoImage]] = {}
        for mood, filename in (
            ("neutral", "bruno_coach.png"),
            ("celebrating", "bruno_celebrating.png"),
            ("thinking", "bruno_thinking.png"),
            ("angry", "bruno_angry.png"),
        ):
            asset = piece_folder / filename
            if asset.is_file():
                source = tk.PhotoImage(file=str(asset))
                self.coach_images[mood] = {
                    "tip": source.subsample(24, 24),
                    "overview": source.subsample(16, 16),
                    "popup": source.subsample(9, 9),
                }
        self.coach_mood = "neutral"
        self.coach_panel: ttk.Frame | None = None
        self.coach_close = None
        self.material_state: dict = {}
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.analysis_engine = EngineSession()
        self.stats_executor = ThreadPoolExecutor(max_workers=1)
        self.overview_executor = ThreadPoolExecutor(max_workers=1)
        self.sync_executor = ThreadPoolExecutor(max_workers=1)
        self.sync_events: queue.Queue = queue.Queue()
        self.sync_future: Future | None = None
        self.user_acted = False
        self.current_game_path: Path | None = None
        self.game_paths: list[Path] = []
        self.original_review_state: dict | None = None
        self.variation_save_path: Path | None = None
        self.variation_start_ply: int | None = None
        self.overview_events: queue.Queue = queue.Queue()
        self.overview_generation = 0
        self.overview_cancel = threading.Event()
        self.overview_assessments: dict[int, dict] = {}
        self.overview_counts: dict[str, Counter] = {"white": Counter(), "black": Counter()}
        self.overview_points: list[float] = []
        self.results: queue.Queue[tuple[int, Future]] = queue.Queue()
        self.progress_results: queue.Queue[tuple[int, chess.engine.Score, float]] = queue.Queue()
        self.stats_events: queue.Queue = queue.Queue()
        self.stats_cancel = threading.Event()
        self.stats_window: tk.Toplevel | None = None
        self.stats_generation = 0
        self.future: Future | None = None
        self.analysis_cancel: threading.Event | None = None
        self.generation = 0
        self.analysis_cache: dict[tuple[int, bool], dict] = {}
        self.score_cache: dict[int, tuple[chess.engine.Score | None, float]] = {}
        self.bar_display_share = 0.5
        self.bar_target_share = 0.5
        self.bar_last_score: chess.engine.Score | None = None
        self.bar_job: str | None = None
        self.best_arrow_cache: dict[int, chess.Move] = {}
        self.reviewing = False
        self.review_stage = "manual"
        self.live_tracker: LiveBoardTracker | None = None
        self.live_stream: WindowCaptureStream | None = None
        self.live_window: int | None = None
        self.live_region: tuple[int, int, int, int] | None = None
        self.live_job: str | None = None
        self.live_game_path: Path | None = None
        self.live_window_title = ""
        self.full = False
        self.flipped = False
        self.selected_square: int | None = None
        self.marked_squares: set[int] = set()
        self.arrows: set[tuple[int, int]] = set()
        self.left_press_square: int | None = None
        self.right_press_square: int | None = None
        self.left_dragging = False
        self.right_dragging = False
        self.drag_item: int | None = None
        self.autoplay_job: str | None = None
        self.games: list[chess.pgn.Game] = []
        self.current_game: chess.pgn.Game | None = None
        self.manual_save_path: Path | None = None
        self.manual_branch_source: Path | None = None
        self.moves: list[chess.Move] = []
        self.positions: list[chess.Board] = [chess.Board()]
        self.ply = 0
        self.engine_var = tk.StringVar(value=str(APP_HOME / "engine" / "stockfish.exe"))
        self.username_var = tk.StringVar(value="TheFallenWizard")
        self.seconds_var = tk.StringVar(value="3")
        self.status_var = tk.StringVar(value="")
        self.grade_var = tk.StringVar(value="Chưa có nước đi")
        self.detail_var = tk.StringVar(value="")
        self.eval_var = tk.StringVar(value="0.00")
        self.bar_orientation_var = tk.StringVar(value="Thanh đánh giá: Đen ở trên, Trắng ở dưới")
        self.game_var = tk.StringVar(value="")
        self.live_status_var = tk.StringVar(value="Chọn cửa sổ và vùng bàn cờ trước khi bắt đầu ván.")
        self._build_ui()
        self._render_board()
        self._draw_bar(None)
        self.root.after(100, self._poll_results)
        self.root.after(100, self._poll_stats)
        self.root.after(100, self._poll_overview)
        self.root.after(100, self._poll_sync)
        self.root.after(400, self._sync_games_on_start)
        self.root.after(24 * 60 * 60 * 1000, self._cleanup_tick)
        self.root.bind("<Left>", lambda _event: self._go_to(self.ply - 1))
        self.root.bind("<Right>", lambda _event: self._go_to(self.ply + 1))
        self.root.bind("<Home>", lambda _event: self._go_to(0))
        self.root.bind("<End>", lambda _event: self._go_to(len(self.moves)))
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
        style.configure("Heart.TButton", background="#3b3833", foreground="#ef7484",
                        font=("Segoe UI", 16, "bold"), padding=(8, 1))

    def _build_ui(self) -> None:
        heading = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        heading.pack(fill="x")
        ttk.Label(heading, text="STOCKFISH REVIEW", font=("Segoe UI", 18, "bold"),
                  foreground="#a8d77a").pack(side="left")
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Stockfish:").pack(side="left")
        ttk.Entry(top, textvariable=self.engine_var, width=48).pack(side="left", padx=5)
        ttk.Button(top, text="Chọn tệp…", command=self._choose_engine).pack(side="left")
        ttk.Button(top, text="Mở PGN…", command=self._open_pgn).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Dán PGN…", command=self._paste_pgn,
                   style="Accent.TButton").pack(side="left", padx=5)
        ttk.Button(top, text="Ván mới", command=self._new_game).pack(side="left", padx=6)
        ttk.Label(top, text="Tên:").pack(side="left", padx=(14, 2))
        ttk.Entry(top, textvariable=self.username_var, width=17).pack(side="left")
        ttk.Button(top, text="Đồng bộ", command=lambda: self._sync_games(auto_load=True)).pack(side="left", padx=4)
        ttk.Button(top, text="Ván đã lưu", command=self._open_saved_games).pack(side="left")

        live_row = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        live_row.pack(fill="x")
        self.live_button = ttk.Button(live_row, text="Theo dõi bàn cờ trên màn hình…",
                                      command=self._open_live_capture)
        self.live_button.pack(side="left")
        ttk.Label(live_row, textvariable=self.live_status_var).pack(side="left", padx=10)

        main = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        main.pack(fill="both", expand=True)
        left = ttk.Frame(main)
        left.pack(side="left", fill="y")
        info_width = BOARD_SIZE + 50
        self.top_material = tk.Canvas(left, width=info_width, height=38,
                                      bg="#2b2926", highlightthickness=0)
        self.top_material.pack(anchor="w")
        board_row = ttk.Frame(left)
        board_row.pack(anchor="w")
        self.bar = tk.Canvas(board_row, width=40, height=BOARD_SIZE, highlightthickness=1,
                             highlightbackground="#645b50", bg="#252525")
        self.bar.pack(side="left", anchor="n", padx=(0, 8))
        self.board_canvas = tk.Canvas(board_row, width=BOARD_SIZE, height=BOARD_SIZE,
                                      highlightthickness=1, highlightbackground="#645b50")
        self.board_canvas.pack(side="left", anchor="n")
        self.bottom_material = tk.Canvas(left, width=info_width, height=38,
                                         bg="#2b2926", highlightthickness=0)
        self.bottom_material.pack(anchor="w")
        self.board_canvas.bind("<ButtonPress-1>", self._left_press)
        self.board_canvas.bind("<B1-Motion>", self._left_motion)
        self.board_canvas.bind("<ButtonRelease-1>", self._left_release)
        self.board_canvas.bind("<ButtonPress-3>", self._right_press)
        self.board_canvas.bind("<B3-Motion>", self._right_motion)
        self.board_canvas.bind("<ButtonRelease-3>", self._right_release)

        right = ttk.Frame(main, padding=(14, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)
        game_row = ttk.Frame(right)
        game_row.pack(fill="x")
        ttk.Label(game_row, textvariable=self.game_var, font=("Segoe UI", 11, "bold"),
                  wraplength=410).pack(side="left", fill="x", expand=True)
        self.favorite_button = ttk.Button(game_row, text="♡", width=3, style="Heart.TButton",
                                          command=self._toggle_favorite, state="disabled")
        self.favorite_button.pack(side="right")
        self.analysis_panel = ttk.Frame(right)
        self.analysis_panel.pack(fill="both", expand=True)
        self.coach_tip_var = tk.StringVar(value="Bruno: Hãy chọn một nước, mình sẽ giúp bạn đọc vị trí.")
        self.coach_tip_row = ttk.Frame(self.analysis_panel)
        self.coach_tip_label = ttk.Label(self.coach_tip_row)
        self.coach_tip_label.pack(side="left", padx=(0, 8))
        ttk.Label(self.coach_tip_row, textvariable=self.coach_tip_var, wraplength=410,
                  font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        controls = ttk.Frame(self.analysis_panel)
        controls.pack(fill="x", pady=(8, 5))
        ttk.Button(controls, text="|◀", width=4, command=lambda: self._go_to(0)).pack(side="left")
        ttk.Button(controls, text="◀", width=4, command=lambda: self._go_to(self.ply - 1)).pack(side="left", padx=3)
        self.autoplay_button = ttk.Button(controls, text="▶", width=4, command=self._toggle_autoplay)
        self.autoplay_button.pack(side="left")
        ttk.Button(controls, text="❯", width=4, command=lambda: self._go_to(self.ply + 1)).pack(side="left", padx=3)
        ttk.Button(controls, text="▶|", width=4, command=lambda: self._go_to(len(self.moves))).pack(side="left")
        ttk.Button(controls, text="Lật bàn", command=self._flip).pack(side="left", padx=4)
        self.review_button = ttk.Button(controls, text="Xem lại", command=self._review_manual, state="disabled")
        self.review_button.pack(side="left", padx=4)

        self.detail_area = ttk.Frame(self.analysis_panel)
        self.detail_area.pack(fill="both", expand=True)
        self.review_sidebar = ttk.Frame(self.detail_area, width=330)
        self.review_sidebar.pack(side="right", fill="y", padx=(10, 0))
        self.review_sidebar.pack_propagate(False)
        self.coach_idle = ttk.LabelFrame(self.detail_area, text="Bruno · HLV cờ", padding=12)
        self.coach_idle.pack(side="left", fill="both", expand=True)
        idle_header = ttk.Frame(self.coach_idle)
        idle_header.pack(anchor="nw")
        self.coach_idle_image = ttk.Label(idle_header)
        self.coach_idle_image.pack(side="left", padx=(0, 12))
        ttk.Label(idle_header, text="Chọn một nước để Bruno giải thích trên bàn cờ.",
                  wraplength=320).pack(side="left")

        self.move_list = tk.Listbox(self.review_sidebar, height=11, font=("Consolas", 10), exportselection=False,
                                    bg="#302d29", fg="#f2eee8", selectbackground="#729e42",
                                    selectforeground="#ffffff", borderwidth=0, highlightthickness=0)
        self.move_list.pack(fill="x")
        self.move_list.bind("<<ListboxSelect>>", self._select_move)
        self.entry_row = ttk.Frame(self.analysis_panel)
        self.entry_row.pack(fill="x", pady=(8, 0), before=self.detail_area)
        ttk.Label(self.entry_row, text="Nhập nước SAN/UCI:").pack(side="left")
        self.move_entry = ttk.Entry(self.entry_row)
        self.move_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.move_entry.bind("<Return>", self._enter_move)
        self.play_button = ttk.Button(self.entry_row, text="Đi", command=self._enter_move,
                                      style="Accent.TButton")
        self.play_button.pack(side="left")

        self.analysis_separator = ttk.Separator(self.review_sidebar)
        self.analysis_separator.pack(fill="x", pady=12)
        self.grade_section = ttk.Frame(self.review_sidebar)
        self.grade_section.pack(fill="x")
        ttk.Label(self.grade_section, text="Đánh giá nước vừa đi", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        grade_row = ttk.Frame(self.grade_section)
        grade_row.pack(anchor="w", pady=(5, 0))
        self.grade_badge = make_badge(grade_row, None, 48)
        self.grade_label = ttk.Label(grade_row, textvariable=self.grade_var, font=("Segoe UI", 16, "bold"))
        self.grade_label.pack(side="left", padx=(6, 0))
        ttk.Label(self.grade_section, textvariable=self.detail_var).pack(anchor="w")
        ttk.Label(self.grade_section, textvariable=self.bar_orientation_var).pack(anchor="w", pady=(6, 0))
        ttk.Label(self.grade_section, textvariable=self.eval_var).pack(anchor="w")

        full_row = ttk.Frame(self.analysis_panel)
        self.full_row = full_row
        full_row.pack(fill="x", pady=(8, 5), before=self.detail_area)
        self.full_button = ttk.Button(full_row, text="Bật Full công suất", command=self._toggle_full,
                                      state="disabled", style="Accent.TButton")
        self.full_button.pack(side="left")
        self.stats_button = ttk.Button(full_row, text="Thống kê nâng cao", command=self._open_stats, state="disabled")
        self.stats_button.pack(side="left", padx=(7, 0))
        self.coach_button = ttk.Button(full_row, text="Hỏi HLV Bruno", command=self._ask_coach, state="disabled")
        self.coach_button.pack(side="left", padx=(7, 0))
        ttk.Label(full_row, text="Giây/vị trí:").pack(side="left", padx=(10, 3))
        self.seconds_combo = ttk.Combobox(full_row, textvariable=self.seconds_var,
                                          values=("1", "2", "3", "5", "10"), width=4, state="readonly")
        self.seconds_combo.pack(side="left")
        self.seconds_combo.bind("<<ComboboxSelected>>", self._analysis_settings_changed)
        self.full_frame = ttk.LabelFrame(self.analysis_panel, text="Phân tích sâu", padding=8)
        self.full_text = tk.Text(self.full_frame, height=5, wrap="word", font=("Segoe UI", 10),
                                 state="disabled", bg="#302d29", fg="#f2eee8",
                                 borderwidth=0, highlightthickness=0)
        self.full_text.pack(fill="both", expand=True)
        self.status_label = ttk.Label(self.analysis_panel, textvariable=self.status_var, wraplength=480)
        self.status_label.pack(anchor="w", pady=(10, 0))

        self.overview_panel = ttk.Frame(right, padding=(0, 12, 0, 0))
        ttk.Label(self.overview_panel, text="TỔNG QUAN VÁN ĐẤU", font=("Segoe UI", 16, "bold"),
                  foreground="#a8d77a").pack(anchor="w")
        self.overview_intro = tk.StringVar(value="Đang chuẩn bị bản xem lại…")
        ttk.Label(self.overview_panel, textvariable=self.overview_intro, wraplength=480).pack(anchor="w", pady=(3, 3))
        coach_row = ttk.Frame(self.overview_panel)
        coach_row.pack(fill="x", pady=(0, 3))
        self.coach_overview_label = ttk.Label(coach_row)
        self.coach_overview_label.pack(side="left", padx=(0, 10))
        ttk.Label(coach_row, text="Bruno · HLV cờ của bạn\nMình sẽ cùng bạn xem các thời điểm quan trọng và giải thích từng nước bằng biến thể cụ thể.",
                  wraplength=330, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        self._set_coach_mood("")
        ttk.Label(self.overview_panel, text="PHÂN LOẠI NƯỚC ĐI", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(2, 2))
        self.overview_grid = ttk.Frame(self.overview_panel)
        self.overview_grid.pack(fill="x")
        self.overview_grid.columnconfigure(0, minsize=210)
        self.overview_count_vars: dict[tuple[str, str], tk.StringVar] = {}
        for col, heading in enumerate(("Nhãn", "Trắng", "Đen")):
            ttk.Label(self.overview_grid, text=heading, font=("Segoe UI", 9, "bold"),
                      foreground="#a8d77a").grid(row=0, column=col, sticky="w", padx=(0, 14))
        for row, (code, (name, color)) in enumerate(LABELS.items(), 1):
            grade_cell = ttk.Frame(self.overview_grid)
            grade_cell.grid(row=row, column=0, sticky="w")
            make_badge(grade_cell, code, 27).pack(side="left", padx=(0, 7))
            ttk.Label(grade_cell, text=name, foreground=text_color(code)).pack(side="left")
            for col, side in ((1, "white"), (2, "black")):
                variable = tk.StringVar(value="0")
                self.overview_count_vars[(side, code)] = variable
                ttk.Label(self.overview_grid, textvariable=variable).grid(row=row, column=col, sticky="w")
        ttk.Label(self.overview_panel, text="DIỄN BIẾN LỢI THẾ", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        self.overview_chart = tk.Canvas(self.overview_panel, height=45, bg="#302d29", highlightthickness=0)
        self.overview_chart.pack(fill="x")
        self.overview_start_button = ttk.Button(self.overview_panel, text="Xem lại từng nước  ▶",
                                                 command=self._start_step_review, style="Accent.TButton")
        self.overview_start_button.pack(fill="x", pady=(6, 0))

    def _choose_engine(self) -> None:
        path = filedialog.askopenfilename(title="Chọn stockfish.exe", filetypes=[("Ứng dụng", "*.exe"), ("Tất cả", "*.*")])
        if path:
            self.engine_var.set(path)
            self._reset_analysis_cache()
            if self.review_stage == "overview" and self.current_game is not None:
                self._show_overview(self.current_game)
                return
            self._request_analysis()

    def _open_live_capture(self) -> None:
        if self.live_tracker is not None:
            self._stop_live_capture()
            return
        self.user_acted = True
        windows = [(hwnd, title) for hwnd, title in visible_windows()
                   if "Stockfish · Đánh giá nước đi" not in title]
        if not windows:
            messagebox.showerror("Không tìm thấy cửa sổ", "Hãy mở cửa sổ có bàn cờ rồi thử lại.")
            return
        from PIL import ImageChops, ImageStat, ImageTk

        dialog = tk.Toplevel(self.root)
        dialog.title("Chọn cửa sổ và vùng bàn cờ")
        dialog.geometry("1000x740")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Chọn cửa sổ, khoanh đúng 8×8 ô và đặt lượt đi hiện tại (kể cả giữa ván).",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 5))
        titles = [f"{title[:95]}  [{hwnd}]" for hwnd, title in windows]
        selection = ttk.Combobox(dialog, values=titles, state="readonly")
        selection.pack(fill="x", padx=12)
        preferred = next((index for index, (_, title) in enumerate(windows)
                          if "chess.com" in title.casefold()), 0)
        selection.current(preferred)
        status = tk.StringVar(value="Bấm Chụp cửa sổ, rồi kéo chuột quanh bàn cờ trong ảnh.")
        ttk.Label(dialog, textvariable=status).pack(anchor="w", padx=12, pady=5)
        preview = tk.Canvas(dialog, bg="#302d29", highlightthickness=0,
                            cursor="crosshair")
        preview.pack(fill="both", expand=True, padx=12, pady=5)
        state: dict = {"image": None, "photo": None, "scale": 1.0,
                       "start": None, "box": None, "rectangle": None,
                       "stream": None, "hwnd": None, "begin_frame": None,
                       "begin_retries": 0, "starting": False}

        def cancel() -> None:
            if state["stream"] is not None:
                state["stream"].close()
                state["stream"] = None
            dialog.grab_release()
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Escape>", lambda _event: cancel())

        def take_preview() -> None:
            try:
                hwnd = windows[selection.current()][0]
                if state["stream"] is not None and state["hwnd"] != hwnd:
                    state["stream"].close()
                    state["stream"] = None
                if state["stream"] is None:
                    state["stream"] = WindowCaptureStream(hwnd)
                    state["hwnd"] = hwnd
                source = state["stream"].latest(timeout=4)
                max_width = max(300, preview.winfo_width() - 4)
                max_height = max(250, preview.winfo_height() - 4)
                factor = min(max_width / source.width, max_height / source.height, 1.0)
                display = reduce_glare(source.resize((round(source.width * factor),
                                                      round(source.height * factor))))
                photo = ImageTk.PhotoImage(display)
                state.update({"image": source, "photo": photo, "scale": factor,
                              "start": None, "box": None, "rectangle": None,
                              "begin_frame": None})
                preview.delete("all")
                preview.create_image(0, 0, image=photo, anchor="nw")
                status.set("Kéo một hình vuông sát mép bàn cờ; không lấy đồng hồ hoặc danh sách nước.")
            except Exception as exc:
                status.set(f"Không chụp được cửa sổ này: {exc}")

        def press(event: tk.Event) -> None:
            if state["image"] is None:
                return
            state["start"] = (event.x, event.y)
            if state["rectangle"] is not None:
                preview.delete(state["rectangle"])
            state["rectangle"] = preview.create_rectangle(
                event.x, event.y, event.x, event.y, outline="#f8b831", width=3)

        def drag(event: tk.Event) -> None:
            if state["start"] is not None:
                x, y = state["start"]
                preview.coords(state["rectangle"], x, y, event.x, event.y)

        def release(event: tk.Event) -> None:
            if state["start"] is None:
                return
            x, y = state["start"]
            factor = state["scale"]
            box = (round(min(x, event.x) / factor), round(min(y, event.y) / factor),
                   round(max(x, event.x) / factor), round(max(y, event.y) / factor))
            try:
                board_crop(state["image"], box)
            except ValueError as exc:
                state["box"] = None
                status.set(str(exc))
                return
            state["box"] = box
            state["begin_frame"] = None
            status.set("Đã chọn bàn cờ. Kiểm tra lượt hiện tại rồi bấm Bắt đầu theo dõi.")

        preview.bind("<ButtonPress-1>", press)
        preview.bind("<B1-Motion>", drag)
        preview.bind("<ButtonRelease-1>", release)
        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=(2, 10))
        ttk.Button(buttons, text="Chụp cửa sổ", command=take_preview).pack(side="left")
        flipped = tk.BooleanVar(value=self.flipped)
        ttk.Checkbutton(buttons, text="Đen ở dưới", variable=flipped).pack(side="left", padx=12)
        ttk.Label(buttons, text="Lượt hiện tại:").pack(side="left", padx=(12, 4))
        turn_selection = ttk.Combobox(buttons, values=("Tự động", "Trắng", "Đen"),
                                      width=9, state="readonly")
        turn_selection.current(0)
        turn_selection.pack(side="left")

        def begin() -> None:
            if not dialog.winfo_exists():
                return
            box = state["box"]
            if box is None:
                status.set("Hãy chụp và chọn vùng bàn cờ trước.")
                return
            if not state["starting"]:
                state["starting"] = True
                state["begin_retries"] = 0
                begin_button.configure(state="disabled")
            hwnd, title = windows[selection.current()]
            try:
                stream = state["stream"]
                if stream is None or stream.closed or state["hwnd"] != hwnd:
                    raise ValueError("Hãy chụp lại cửa sổ đã chọn.")
                source = stream.latest(timeout=4)
                if state["begin_frame"] is None:
                    state["begin_frame"] = source
                    status.set("Đang đợi ảnh bàn cờ ổn định…")
                    dialog.after(180, begin)
                    return
                before = board_crop(state["begin_frame"], box)
                after = board_crop(source, box)
                change = max(ImageStat.Stat(ImageChops.difference(before, after)).mean)
                if change > 1.5:
                    state["begin_frame"] = source
                    state["begin_retries"] += 1
                    if state["begin_retries"] < 12:
                        dialog.after(180, begin)
                        return
                    raise ValueError("Bàn cờ đang thay đổi liên tục. Hãy đợi nước đi hoàn tất rồi thử lại.")
                selected_turn = turn_selection.current()
                if selected_turn:
                    box, starting_board, first_frame = align_board(
                        source, box, flipped.get(), selected_turn == 1,
                    )
                else:
                    try:
                        box, starting_board, first_frame = align_board(
                            source, box, flipped.get(), chess.WHITE,
                        )
                    except ValueError:
                        box, starting_board, first_frame = align_board(
                            source, box, flipped.get(), chess.BLACK,
                        )
                    inferred = infer_turn(first_frame, starting_board, flipped.get())
                    if inferred is None:
                        raise ValueError("Không xác định được lượt đi từ ảnh. "
                                         "Hãy chọn Trắng hoặc Đen ở mục Lượt hiện tại.")
                    starting_board.turn = inferred
                    if not starting_board.is_valid():
                        raise ValueError("Lượt đi suy ra không hợp lệ; hãy chọn thủ công.")
            except (OSError, ValueError, TimeoutError) as exc:
                state["starting"] = False
                state["begin_frame"] = None
                begin_button.configure(state="normal")
                status.set(f"Không đọc được bàn cờ: {exc}")
                return
            stream.drain(128)
            state["stream"] = None
            dialog.grab_release()
            dialog.destroy()
            self._begin_live_capture(hwnd, title, box, flipped.get(), first_frame,
                                     stream, starting_board)

        begin_button = ttk.Button(buttons, text="Bắt đầu theo dõi", command=begin,
                                  style="Accent.TButton")
        begin_button.pack(side="right")

    def _begin_live_capture(self, hwnd: int, title: str,
                            box: tuple[int, int, int, int], flipped: bool,
                            first_frame, stream: WindowCaptureStream,
                            starting_board: chess.Board) -> None:
        self._new_game()
        self.flipped = flipped
        self.positions = [starting_board]
        self.live_tracker = LiveBoardTracker(starting_board.copy(stack=True), flipped)
        self.live_tracker.observe(first_frame)
        self.live_stream = stream
        self.live_window = hwnd
        self.live_region = box
        self.live_window_title = title
        self.live_game_path = GAMES_DIR / local_filename("van-theo-doi", ".pgn")
        self.manual_save_path = self.live_game_path
        self.move_entry.configure(state="disabled")
        self.play_button.configure(state="disabled")
        self.live_button.configure(text="Dừng theo dõi")
        self.game_var.set("Đang theo dõi · " + title[:65])
        self.live_status_var.set("Đang nhận nước đi trực tiếp · 0 nước")
        self._refresh()
        self.live_job = self.root.after(60, self._capture_live_tick)

    def _capture_live_tick(self) -> None:
        self.live_job = None
        tracker = self.live_tracker
        if (tracker is None or self.live_stream is None
                or self.live_window is None or self.live_region is None):
            return
        try:
            if self.live_stream.closed:
                raise OSError("Cửa sổ nguồn đã đóng.")
            frames = self.live_stream.drain(128)
            source = frames[-1] if frames else self.live_stream.latest()
            frame = board_crop(source, self.live_region)
            for move in tracker.observe(frame):
                self._apply_live_move(move)
                if self.live_tracker is None:
                    return
        except (OSError, ValueError, TimeoutError) as exc:
            self._stop_live_capture()
            self.live_status_var.set(f"Đã dừng: {exc}")
            return
        if tracker.unmatched_frames >= 50:
            saved_path = self.live_game_path
            self._stop_live_capture()
            self.live_status_var.set(
                "Đã dừng vì ảnh bàn cờ không còn khớp nước hợp lệ (có thể đã bỏ lỡ nước). "
                f"PGN trước đó đã lưu tại {saved_path}. Chọn lại vùng, chiều bàn và lượt đi để theo dõi tiếp."
            )
        if self.live_tracker is not None:
            self.live_job = self.root.after(60, self._capture_live_tick)

    def _apply_live_move(self, move: chess.Move) -> None:
        current = self.positions[-1]
        if move not in current.legal_moves:
            self._stop_live_capture()
            self.live_status_var.set("Vị trí trên màn hình không khớp PGN đã ghi; hãy chọn lại vùng bàn cờ.")
            return
        following = current.copy(stack=True)
        following.push(move)
        self.moves.append(move)
        self.positions.append(following)
        self.ply = len(self.moves)
        self._clear_annotations()
        game = chess.pgn.Game.from_board(following)
        name = self.username_var.get().strip() or "Bạn"
        game.headers["White"] = "Đối thủ" if self.live_tracker.flipped else name
        game.headers["Black"] = name if self.live_tracker.flipped else "Đối thủ"
        game.headers["Event"] = "Theo dõi bàn cờ trên màn hình"
        self.current_game = game
        try:
            GAMES_DIR.mkdir(parents=True, exist_ok=True)
            temporary = self.live_game_path.with_suffix(".part")
            temporary.write_text(str(game) + "\n", encoding="utf-8")
            temporary.replace(self.live_game_path)
            self.current_game_path = self.live_game_path
            self._update_favorite_button()
        except OSError as exc:
            self._stop_live_capture()
            self.live_status_var.set(f"Không lưu được PGN: {exc}")
            return
        self._fill_moves()
        self._refresh()
        self.live_status_var.set(f"Đang nhận nước đi trực tiếp · {self.ply} nước · "
                                 f"vừa ghi {self.positions[-2].san(move)}")
        if following.is_game_over():
            self._stop_live_capture()
            self.live_status_var.set("Ván đã kết thúc; PGN đã lưu trên ổ D.")

    def _stop_live_capture(self) -> None:
        if self.live_job is not None:
            self.root.after_cancel(self.live_job)
            self.live_job = None
        if self.live_tracker is None:
            return
        count = len(self.moves)
        self.live_tracker = None
        if self.live_stream is not None:
            self.live_stream.close()
            self.live_stream = None
        self.live_window = None
        self.live_region = None
        self.live_button.configure(text="Theo dõi bàn cờ trên màn hình…")
        self.move_entry.configure(state="normal")
        self.play_button.configure(state="normal")
        self.live_status_var.set(
            f"Đã dừng theo dõi · {count} nước; PGN lưu tại D:\\Chess\\data\\games."
            if count else "Đã dừng theo dõi trước khi có nước đi."
        )

    def _analysis_settings_changed(self, _event: tk.Event) -> None:
        self.analysis_cache = {
            key: value for key, value in self.analysis_cache.items() if not key[1]
        }
        if self.review_stage != "overview" and self.full:
            self._request_analysis()

    def _sync_games_on_start(self) -> None:
        try:
            removed = prune_old_games(GAMES_DIR)
        except (OSError, ValueError) as exc:
            self.status_var.set(f"Không dọn được ván cũ: {exc}")
            removed = 0
        if removed:
            self.status_var.set(f"Đã dọn {removed} PGN quá 30 ngày không yêu thích.")
        self._sync_games(auto_load=True)

    def _cleanup_tick(self) -> None:
        try:
            removed = prune_old_games(GAMES_DIR)
            if removed:
                self.status_var.set(f"Đã dọn {removed} PGN quá 30 ngày không yêu thích.")
                self._update_favorite_button()
        except (OSError, ValueError) as exc:
            self.status_var.set(f"Không dọn được ván cũ: {exc}")
        self.root.after(24 * 60 * 60 * 1000, self._cleanup_tick)

    def _sync_games(self, auto_load: bool = False) -> None:
        if self.sync_future is not None and not self.sync_future.done():
            self.status_var.set("Đang đồng bộ ván đã kết thúc…")
            return
        username = self.username_var.get().strip()
        self.status_var.set(f"Đang lấy tối đa 10 ván đã kết thúc gần nhất của {username}…")
        self.sync_future = self.sync_executor.submit(sync_recent_games, username, GAMES_DIR)
        self.sync_future.add_done_callback(
            lambda future: self.sync_events.put((future, auto_load, username))
        )

    def _poll_sync(self) -> None:
        try:
            while True:
                future, auto_load, username = self.sync_events.get_nowait()
                try:
                    result = future.result()
                except Exception as exc:
                    self.status_var.set(f"Đồng bộ không thành công: {exc}")
                    result = None
                if result is not None:
                    self.status_var.set(
                        f"Đã đồng bộ {result['total']} ván gần nhất của {username} (tối đa 10); "
                        f"thêm {result['created']} ván vào D:\\Chess\\data\\games."
                    )
                if auto_load and not self.user_acted and self.current_game_path is None:
                    latest = result["latest"] if result else None
                    if latest is None:
                        stored = sorted(GAMES_DIR.glob(f"chesscom-*-{username.casefold()}-*.pgn"))
                        latest = stored[-1] if stored else None
                    if latest is not None and latest.is_file():
                        try:
                            games = self._parse_pgn(latest.read_text(encoding="utf-8-sig"))
                            self._load_pgn_games(games, latest)
                        except (OSError, ValueError) as exc:
                            self.status_var.set(f"Không mở được PGN đã đồng bộ: {exc}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_sync)

    def _open_saved_games(self) -> None:
        self.user_acted = True
        favorites = load_favorites(GAMES_DIR)
        all_paths = sorted(GAMES_DIR.glob("*.pgn"), key=lambda path: path.stat().st_mtime,
                           reverse=True)
        paths = ([path for path in all_paths if path.name in favorites]
                 + [path for path in all_paths if path.name not in favorites][:100])
        popup = tk.Toplevel(self.root)
        popup.title("Các ván đã lưu trên ổ D")
        popup.configure(bg="#211f1c")
        popup.geometry("640x490")
        ttk.Label(popup, text=f"{len(paths)} ván gần nhất trong D:\\Chess\\data\\games",
                  padding=10).pack(anchor="w")
        listing = tk.Listbox(popup, bg="#302d29", fg="#f2eee8",
                             selectbackground="#729e42", font=("Segoe UI", 10))
        listing.pack(fill="both", expand=True, padx=10, pady=5)
        for path in paths:
            try:
                with path.open("r", encoding="utf-8-sig") as source:
                    game = chess.pgn.read_game(source)
                title = (f"{game.headers.get('White', '?')} – {game.headers.get('Black', '?')}"
                         if game else path.name)
            except (OSError, UnicodeError):
                title = path.name
            favorite = "♥ " if path.name in favorites else ""
            listing.insert("end", f"{favorite}{title}   ·   {path.name}")
        if paths:
            listing.selection_set(0)

        def open_selected() -> None:
            selection = listing.curselection()
            if not selection:
                return
            path = paths[selection[0]]
            try:
                games = self._parse_pgn(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, ValueError) as exc:
                messagebox.showerror("Không mở được ván", str(exc), parent=popup)
                return
            self.user_acted = True
            popup.destroy()
            self._load_pgn_games(games, path)

        ttk.Button(popup, text="Mở ván đã chọn", command=open_selected,
                   style="Accent.TButton").pack(fill="x", padx=10, pady=10)
        listing.bind("<Double-Button-1>", lambda _event: open_selected())

    def _update_favorite_button(self) -> None:
        path = self.current_game_path
        if path is None or not path.is_file():
            self.favorite_button.configure(text="♡", state="disabled")
            return
        selected = path.name in load_favorites(GAMES_DIR)
        self.favorite_button.configure(text="♥" if selected else "♡", state="normal")

    def _toggle_favorite(self) -> None:
        path = self.current_game_path
        if path is None or not path.is_file():
            return
        favorites = load_favorites(GAMES_DIR)
        if path.name in favorites:
            favorites.remove(path.name)
            self.status_var.set("Đã bỏ yêu thích. Ván sẽ được dọn sau khi quá 30 ngày.")
        else:
            favorites.add(path.name)
            self.status_var.set("Đã yêu thích. Ván này được giữ lại trên ổ D.")
        try:
            save_favorites(GAMES_DIR, favorites)
        except OSError as exc:
            messagebox.showerror("Không lưu được yêu thích", str(exc))
        self._update_favorite_button()

    def _open_pgn(self) -> None:
        path = filedialog.askopenfilename(title="Mở ván cờ PGN", filetypes=[("PGN", "*.pgn"), ("Tất cả", "*.*")])
        if not path:
            return
        self.user_acted = True
        try:
            content = Path(path).read_text(encoding="utf-8-sig")
            games = self._parse_pgn(content)
            source = Path(path).resolve()
            stored = source if source.parent == GAMES_DIR.resolve() else save_local_pgn(content, source.name)
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("Không mở được PGN", str(exc))
            return
        self._load_pgn_games(games, stored)

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
        self.user_acted = True
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
            self.user_acted = True
            self._load_pgn_games(games, stored)

        ttk.Button(popup, text="Lưu vào D:\\Chess và mở", command=save_and_open).pack(pady=10)

    def _load_pgn_games(self, games: list[chess.pgn.Game], source: Path) -> None:
        self.games = games
        self.game_paths = []
        if len(games) == 1:
            self.game_paths.append(source)
        else:
            for index, game in enumerate(games):
                digest = hashlib.sha256(
                    f"{source.name}:{index}:{game}".encode("utf-8")
                ).hexdigest()[:16]
                single_path = GAMES_DIR / f"tach-van-{digest}.pgn"
                if not single_path.is_file():
                    single_path.write_text(str(game) + "\n", encoding="utf-8")
                self.game_paths.append(single_path)
        self.current_game_path = self.game_paths[0]
        self._load_game(games[0])
        self.status_var.set(f"Đã mở {len(games)} ván trong D:\\Chess\\data\\games ({source.name}).")
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
                self.current_game_path = self.game_paths[selection[0]]
                self._load_game(self.games[selection[0]])
            popup.destroy()

        ttk.Button(popup, text="Mở ván", command=choose).pack(pady=(0, 10))
        listing.bind("<Double-Button-1>", lambda _event: choose())

    def _load_game(self, game: chess.pgn.Game) -> None:
        self._stop_live_capture()
        self._dismiss_coach_panel()
        self.current_game = game
        self.original_review_state = None
        self.variation_save_path = None
        self.variation_start_ply = None
        self._update_favorite_button()
        self.manual_save_path = None
        self.manual_branch_source = None
        self._stop_autoplay()
        self._reset_analysis_cache(reset_bar=True)
        self._clear_annotations()
        self.moves = list(game.mainline_moves())
        player = self.username_var.get().strip().casefold()
        white = game.headers.get("White", "").strip().casefold()
        black = game.headers.get("Black", "").strip().casefold()
        self.flipped = bool(player and black == player and white != player)
        board = game.board()
        self.positions = [board.copy(stack=True)]
        for move in self.moves:
            board.push(move)
            self.positions.append(board.copy(stack=True))
        self.ply = 0
        self.reviewing = True
        self.review_stage = "overview"
        self.full = False
        self.full_frame.pack_forget()
        self.move_list.configure(height=11)
        self.full_button.configure(text="Bật Full công suất", state="normal")
        self.coach_button.configure(state="disabled")
        self.coach_tip_row.pack_forget()
        self.stats_button.configure(state="normal")
        self.review_button.configure(text="Xem lại", command=self._review_manual, state="disabled")
        self.move_entry.configure(state="disabled")
        self.play_button.configure(state="disabled")
        self.game_var.set(f"{game.headers.get('White', 'Trắng')} – {game.headers.get('Black', 'Đen')}")
        self._fill_moves()
        self._show_overview(game)

    def _new_game(self) -> None:
        self._stop_live_capture()
        self._dismiss_coach_panel()
        self.user_acted = True
        self._stop_autoplay()
        self._reset_analysis_cache(reset_bar=True)
        self._clear_annotations()
        self.games = []
        self.current_game = None
        self.current_game_path = None
        self.game_paths = []
        self.original_review_state = None
        self.variation_save_path = None
        self.variation_start_ply = None
        self._update_favorite_button()
        self.manual_save_path = None
        self.manual_branch_source = None
        self.moves = []
        self.positions = [chess.Board()]
        self.ply = 0
        self.flipped = False
        self.reviewing = False
        self.review_stage = "manual"
        self.full = False
        self.selected_square = None
        self.full_frame.pack_forget()
        self.full_button.configure(text="Bật Full công suất", state="disabled")
        self.coach_button.configure(state="disabled")
        self.coach_tip_row.pack_forget()
        self.stats_button.configure(state="disabled")
        self.review_button.configure(text="Xem lại", command=self._review_manual, state="disabled")
        self.move_entry.configure(state="normal")
        self.play_button.configure(state="normal")
        self.entry_row.pack(fill="x", pady=(8, 0), before=self.detail_area)
        self.move_list.configure(height=11)
        self.move_list.delete(0, "end")
        self.game_var.set("Ván mới")
        self.overview_panel.pack_forget()
        self.analysis_panel.pack(fill="both", expand=True)
        self._refresh()

    def _review_manual(self) -> None:
        if not self.positions[-1].is_game_over():
            return
        self._dismiss_coach_panel()
        game = chess.pgn.Game.from_board(self.positions[-1])
        game.headers["White"] = "Trắng"
        game.headers["Black"] = "Đen"
        self.games = [game]
        self.current_game = game
        self.original_review_state = None
        self.variation_save_path = None
        self.variation_start_ply = None
        self.current_game_path = self.manual_save_path
        self.game_paths = [self.manual_save_path] if self.manual_save_path else []
        self._update_favorite_button()
        self.reviewing = True
        self.review_stage = "overview"
        self.full_button.configure(state="normal")
        self.stats_button.configure(state="normal")
        self.review_button.configure(state="disabled")
        self.move_entry.configure(state="disabled")
        self.play_button.configure(state="disabled")
        self.coach_button.configure(state="disabled")
        self._show_overview(game)

    def _show_overview(self, game: chess.pgn.Game) -> None:
        self._dismiss_coach_panel()
        self.overview_cancel.set()
        self.overview_cancel = threading.Event()
        self.overview_generation += 1
        generation = self.overview_generation
        self.overview_assessments.clear()
        self.overview_points.clear()
        self.overview_counts = {"white": Counter(), "black": Counter()}
        for variable in self.overview_count_vars.values():
            variable.set("0")
        self.overview_chart.delete("all")
        self.analysis_panel.pack_forget()
        self.overview_panel.pack(fill="both", expand=True)
        self.overview_intro.set(f"{len(self.moves)} nước đi · Đang phân tích tổng quan trên máy…")
        self.overview_start_button.configure(state="disabled")
        self._render_board()
        self._draw_bar(None)
        try:
            path = resolve_engine(self.engine_var.get())
        except FileNotFoundError as exc:
            self.overview_intro.set(f"{len(self.moves)} nước đi · {exc}")
            self.overview_start_button.configure(state="normal")
            return
        future = self.overview_executor.submit(
            compute_overview, game, path, self.overview_events,
            generation, self.overview_cancel,
        )
        future.add_done_callback(lambda done: self.overview_events.put((generation, "done", done)))

    def _start_step_review(self) -> None:
        self.review_stage = "step"
        self.overview_panel.pack_forget()
        self.analysis_panel.pack(fill="both", expand=True)
        self.coach_tip_row.pack_forget()
        self.entry_row.pack_forget()
        self.coach_button.configure(state="normal")
        self.ply = 0
        self._refresh()
        self.coach_idle.pack(side="left", fill="both", expand=True)

    def _poll_overview(self) -> None:
        try:
            while True:
                event = self.overview_events.get_nowait()
                generation, kind = event[:2]
                if generation != self.overview_generation:
                    continue
                if kind == "move":
                    _, _, index, total, assessment = event
                    self.overview_assessments[index] = assessment
                    if assessment.get("best_pv"):
                        self.best_arrow_cache[index - 1] = assessment["best_pv"][0]
                    side = "white" if index % 2 else "black"
                    code = assessment["category"]
                    self.overview_counts[side][code] += 1
                    self.overview_count_vars[(side, code)].set(str(self.overview_counts[side][code]))
                    self.overview_points.append(assessment["white_ep"])
                    self.score_cache[index] = (assessment["white_score"], assessment["white_ep"])
                    self.overview_intro.set(f"Đã phân tích {index}/{total} nước · Đang chuẩn bị thanh đánh giá và thống kê.")
                    if self.review_stage == "step" and self.ply == index:
                        self._draw_bar(*self.score_cache[index])
                        self._render_board()
                    if self.review_stage == "step" and self.ply == index - 1:
                        self._render_board()
                    self._draw_overview_chart()
                else:
                    try:
                        event[2].result()
                    except Exception as exc:
                        self.overview_intro.set(f"Phân tích tổng quan dừng: {exc}. Vẫn có thể xem lại từng nước.")
                    else:
                        self.overview_intro.set(f"Đã phân tích {len(self.moves)} nước. Bấm Xem lại từng nước để khám phá.")
                    self._fill_moves()
                    self.overview_start_button.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_overview)

    def _draw_overview_chart(self) -> None:
        canvas = self.overview_chart
        canvas.delete("all")
        width = max(canvas.winfo_width(), 410)
        height = 45
        canvas.create_line(0, height / 2, width, height / 2, fill="#77716a", dash=(3, 3))
        if not self.overview_points:
            return
        coordinates = [(i * width / max(len(self.moves), 1), height * (1 - ep))
                       for i, ep in enumerate([0.5] + self.overview_points)]
        if len(coordinates) >= 2:
            canvas.create_line(*[coord for point in coordinates for coord in point],
                               fill="#a8d77a", width=2, smooth=False)
        for x, y in coordinates[1:]:
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#f0d9b5", outline="")

    def _fill_moves(self) -> None:
        self.move_list.delete(0, "end")
        for index, move in enumerate(self.moves):
            board = self.positions[index]
            prefix = f"{board.fullmove_number}{'.' if board.turn else '...'}"
            category = (self.overview_assessments.get(index + 1, {}).get("category")
                        or self.analysis_cache.get((index + 1, False), {}).get("category"))
            label = f"  ·  {LABELS[category][0]}" if category in LABELS else ""
            self.move_list.insert("end", f"{prefix} {board.san(move)}{label}")
            if category in LABELS:
                self.move_list.itemconfigure(index, foreground=text_color(category))
            if self.original_review_state is not None and self.variation_start_ply is not None:
                if index >= self.variation_start_ply:
                    self.move_list.itemconfigure(index, foreground="#f2c66e")
        if self.review_stage == "step" and self.ply:
            self.move_list.selection_set(self.ply - 1)
            self.move_list.see(self.ply - 1)

    def _select_move(self, _event: tk.Event) -> None:
        selection = self.move_list.curselection()
        if selection and self.ply != selection[0] + 1:
            self._go_to(selection[0] + 1)

    def _go_to(self, ply: int, *, from_autoplay: bool = False) -> None:
        if self.live_tracker is not None:
            return
        if self.reviewing and self.review_stage != "step":
            return
        if not from_autoplay:
            self._stop_autoplay()
        next_ply = max(0, min(ply, len(self.moves)))
        if next_ply == self.ply:
            return
        self.ply = next_ply
        self._clear_annotations()
        self._refresh()
        if (self.review_stage == "step" and self.ply and not from_autoplay
                and self.coach_panel is None):
            self.root.after_idle(
                lambda: self._ask_coach()
                if self.review_stage == "step" and self.ply and self.coach_panel is None
                else None
            )

    def _toggle_autoplay(self) -> None:
        if not self.reviewing or self.review_stage != "step":
            return
        if self.autoplay_job is not None:
            self._stop_autoplay()
            return
        if self.ply >= len(self.moves):
            self._go_to(0)
        self.autoplay_button.configure(text="Ⅱ")
        self.autoplay_job = self.root.after(700, self._autoplay_tick)

    def _autoplay_tick(self) -> None:
        self.autoplay_job = None
        if not self.reviewing or self.ply >= len(self.moves):
            self._stop_autoplay()
            return
        self._go_to(self.ply + 1, from_autoplay=True)
        if self.ply < len(self.moves):
            self.autoplay_job = self.root.after(700, self._autoplay_tick)
        else:
            self._stop_autoplay()

    def _stop_autoplay(self) -> None:
        if self.autoplay_job is not None:
            self.root.after_cancel(self.autoplay_job)
            self.autoplay_job = None
        if hasattr(self, "autoplay_button"):
            self.autoplay_button.configure(text="▶")

    def _clear_annotations(self) -> None:
        self.marked_squares.clear()
        self.arrows.clear()
        self.selected_square = None
        self.left_press_square = None
        self.right_press_square = None
        self.left_dragging = False
        self.right_dragging = False
        self.drag_item = None

    def _reset_analysis_cache(self, *, reset_bar: bool = False) -> None:
        self.generation += 1
        self._cancel_current_analysis()
        self.analysis_cache.clear()
        self.score_cache.clear()
        self.best_arrow_cache.clear()
        if reset_bar:
            if self.bar_job is not None:
                self.root.after_cancel(self.bar_job)
                self.bar_job = None
            self.bar_display_share = self.bar_target_share = 0.5
            self.bar_last_score = None

    def _cancel_current_analysis(self) -> None:
        if self.analysis_cancel is not None:
            self.analysis_cancel.set()
            self.analysis_cancel = None
        if self.future is not None:
            self.analysis_engine.interrupt()
            self.future.cancel()

    def _flip(self) -> None:
        self.flipped = not self.flipped
        self.bar_display_share = 1 - self.bar_display_share
        self.bar_target_share = 1 - self.bar_target_share
        self._render_board()
        self._draw_bar(*self.score_cache.get(self.ply, (None, 0.5)))

    def _event_square(self, event: tk.Event) -> int | None:
        file_index = event.x // SQUARE
        rank_index = event.y // SQUARE
        if not 0 <= file_index < 8 or not 0 <= rank_index < 8:
            return None
        file_ = 7 - file_index if self.flipped else file_index
        rank_ = rank_index if self.flipped else 7 - rank_index
        return chess.square(file_, rank_)

    def _square_center(self, square: int) -> tuple[float, float]:
        file_ = chess.square_file(square)
        rank_ = chess.square_rank(square)
        col = 7 - file_ if self.flipped else file_
        row = rank_ if self.flipped else 7 - rank_
        return (col + 0.5) * SQUARE, (row + 0.5) * SQUARE

    def _can_move_board(self) -> bool:
        return self.live_tracker is None and (not self.reviewing or self.review_stage == "step")

    def _legal_move(self, start: int, end: int) -> chess.Move | None:
        if not self._can_move_board():
            return None
        board = self.positions[self.ply]
        piece = board.piece_at(start)
        if piece is None or piece.color != board.turn:
            return None
        move = chess.Move(start, end)
        if piece.piece_type == chess.PAWN and chess.square_rank(end) in (0, 7):
            move = chess.Move(start, end, promotion=chess.QUEEN)
        return move if move in board.legal_moves else None

    def _left_press(self, event: tk.Event) -> None:
        self.left_press_square = self._event_square(event)
        self.left_press_xy = (event.x, event.y)
        self.left_dragging = False

    def _left_motion(self, event: tk.Event) -> None:
        start = self.left_press_square
        if start is None or not self._can_move_board() or self.positions[self.ply].is_game_over():
            return
        piece = self.positions[self.ply].piece_at(start)
        if piece is None or piece.color != self.positions[self.ply].turn:
            return
        if not self.left_dragging:
            x0, y0 = self.left_press_xy
            if (event.x - x0) ** 2 + (event.y - y0) ** 2 < 64:
                return
            self.left_dragging = True
            self.board_canvas.itemconfigure(f"piece_{start}", state="hidden")
            icon = self.piece_images.get(("w" if piece.color else "b", piece.symbol().upper()))
            if icon:
                self.drag_item = self.board_canvas.create_image(event.x, event.y, image=icon)
            else:
                self.drag_item = self.board_canvas.create_text(
                    event.x, event.y, text=PIECES[piece.symbol()], font=("Segoe UI Symbol", 38)
                )
        elif self.drag_item is not None:
            self.board_canvas.coords(self.drag_item, event.x, event.y)

    def _left_release(self, event: tk.Event) -> None:
        start = self.left_press_square
        target = self._event_square(event)
        dragging = self.left_dragging
        self.left_press_square = None
        self.left_dragging = False
        if self.drag_item is not None:
            self.board_canvas.delete(self.drag_item)
            self.drag_item = None
        if target is None:
            self._render_board()
            return
        if dragging and start is not None:
            move = self._legal_move(start, target)
            if move is not None:
                self._play_move(move)
            else:
                self.selected_square = start if self._can_move_board() else None
                self._render_board()
            return
        if not self._can_move_board():
            self._remove_annotations_at(target)
            self._render_board()
            return
        if self.selected_square is not None:
            if self.selected_square == target:
                self.selected_square = None
                self._render_board()
                return
            move = self._legal_move(self.selected_square, target)
            if move is not None:
                self._play_move(move)
                return
        if target in self.marked_squares or any(target in arrow for arrow in self.arrows):
            self._remove_annotations_at(target)
            self._render_board()
            return
        board = self.positions[self.ply]
        piece = board.piece_at(target)
        self.selected_square = target if piece and piece.color == board.turn else None
        self._render_board()

    def _remove_annotations_at(self, square: int) -> None:
        self.marked_squares.discard(square)
        self.arrows = {arrow for arrow in self.arrows if square not in arrow}

    def _right_press(self, event: tk.Event) -> None:
        self.right_press_square = self._event_square(event)
        self.right_press_xy = (event.x, event.y)
        self.right_dragging = False

    def _right_motion(self, event: tk.Event) -> None:
        start = self.right_press_square
        if start is None:
            return
        if not self.right_dragging:
            x0, y0 = self.right_press_xy
            if (event.x - x0) ** 2 + (event.y - y0) ** 2 < 64:
                return
            self.right_dragging = True
        self.board_canvas.delete("preview_arrow")
        end = self._event_square(event)
        if end is not None and end != start:
            self._draw_arrow(start, end, "preview_arrow")

    def _right_release(self, event: tk.Event) -> None:
        start = self.right_press_square
        end = self._event_square(event)
        dragging = self.right_dragging
        self.right_press_square = None
        self.right_dragging = False
        self.board_canvas.delete("preview_arrow")
        if start is None:
            return
        if dragging and end is not None and end != start:
            arrow = (start, end)
            if arrow in self.arrows:
                self.arrows.remove(arrow)
            else:
                self.arrows.add(arrow)
        else:
            if start in self.marked_squares:
                self.marked_squares.remove(start)
            elif any(start in arrow for arrow in self.arrows):
                self.arrows = {arrow for arrow in self.arrows if start not in arrow}
            else:
                self.marked_squares.add(start)
        self._render_board()

    def _draw_arrow(self, start: int, end: int, tag: str) -> None:
        x1, y1 = self._square_center(start)
        x2, y2 = self._square_center(end)
        piece = self.positions[self.ply].piece_at(start)
        if piece is not None and piece.piece_type == chess.KNIGHT and x1 != x2 and y1 != y2:
            points = (x1, y1, x2, y1, x2, y2)
        else:
            points = (x1, y1, x2, y2)
        self.board_canvas.create_line(
            *points, fill="#efae22", width=14, joinstyle=tk.ROUND,
            arrow=tk.LAST, arrowshape=(24, 32, 12), tags=tag,
        )

    def _enter_move(self, _event: tk.Event | None = None) -> None:
        if not self._can_move_board():
            return
        raw = self.move_entry.get().strip()
        if not raw:
            return
        board = self.positions[self.ply]
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
        if self.live_tracker is not None:
            return
        self.user_acted = True
        if self.reviewing:
            if self.review_stage == "step":
                self._play_variation_move(move)
            return
        current = self.positions[self.ply]
        if move not in current.legal_moves:
            return
        if self.ply < len(self.moves) and self.moves[self.ply] == move:
            self._go_to(self.ply + 1)
            return
        if self.ply < len(self.moves):
            branch_from = self.ply
            self.manual_branch_source = self.manual_save_path
            self.manual_save_path = GAMES_DIR / local_filename("van-tu-choi-nhanh", ".pgn")
            self.game_var.set("Nhánh tự chơi")
            self.generation += 1
            self._cancel_current_analysis()
            self.analysis_cache = {
                key: value for key, value in self.analysis_cache.items()
                if key[0] <= branch_from
            }
            self.score_cache = {
                key: value for key, value in self.score_cache.items()
                if key <= branch_from
            }
            self.moves = self.moves[:branch_from]
            self.positions = self.positions[:branch_from + 1]
        board = current.copy(stack=True)
        self.moves.append(move)
        board.push(move)
        self.positions.append(board)
        self.ply = len(self.moves)
        self._clear_annotations()
        self._fill_moves()
        try:
            GAMES_DIR.mkdir(parents=True, exist_ok=True)
            if self.manual_save_path is None:
                self.manual_save_path = GAMES_DIR / local_filename("van-tu-choi", ".pgn")
            saved_game = chess.pgn.Game.from_board(board)
            saved_game.headers["White"] = "Trắng"
            saved_game.headers["Black"] = "Đen"
            if self.manual_branch_source is not None:
                saved_game.headers["Event"] = "Nhánh tự chơi"
                saved_game.headers["SourcePGN"] = self.manual_branch_source.name
            self.manual_save_path.write_text(str(saved_game) + "\n", encoding="utf-8")
            self.current_game_path = self.manual_save_path
            self._update_favorite_button()
        except OSError as exc:
            messagebox.showerror("Không lưu được ván", str(exc))
        if board.is_game_over():
            self.review_button.configure(state="normal")
            self.status_var.set("Ván đã kết thúc. Bấm Xem lại để bật phân tích sâu.")
        else:
            self.review_button.configure(state="disabled")
        self._refresh()

    def _play_variation_move(self, move: chess.Move) -> None:
        board = self.positions[self.ply]
        if move not in board.legal_moves:
            return
        if self.ply < len(self.moves) and self.moves[self.ply] == move:
            self._go_to(self.ply + 1)
            return
        self._stop_autoplay()
        if self.original_review_state is None:
            self.original_review_state = {
                "moves": self.moves[:],
                "positions": self.positions[:],
                "analysis_cache": self.analysis_cache.copy(),
                "score_cache": self.score_cache.copy(),
                "best_arrow_cache": self.best_arrow_cache.copy(),
                "overview_assessments": self.overview_assessments.copy(),
                "overview_points": self.overview_points[:],
                "current_game_path": self.current_game_path,
                "game": self.current_game,
                "game_var": self.game_var.get(),
                "ply": self.ply,
            }
        if self.ply < len(self.moves) or self.variation_save_path is None:
            self.variation_save_path = GAMES_DIR / local_filename("nhanh-phan-tich", ".pgn")
            self.variation_start_ply = self.ply
        branch_from = self.ply
        self.generation += 1
        self._cancel_current_analysis()
        self.analysis_cache = {key: value for key, value in self.analysis_cache.items()
                               if key[0] <= branch_from}
        self.score_cache = {key: value for key, value in self.score_cache.items()
                            if key <= branch_from}
        self.best_arrow_cache = {key: value for key, value in self.best_arrow_cache.items()
                                 if key <= branch_from}
        self.overview_assessments = {
            key: value for key, value in self.overview_assessments.items()
            if key <= branch_from
        }
        self.moves = self.moves[:branch_from]
        self.positions = self.positions[:branch_from + 1]
        changed = board.copy(stack=True)
        changed.push(move)
        self.moves.append(move)
        self.positions.append(changed)
        self.ply = len(self.moves)
        self._clear_annotations()
        self.current_game_path = self.variation_save_path
        self.game_var.set(f"Nhánh phân tích · {self.original_review_state['game_var']}")
        self.review_button.configure(text="Ván gốc", command=self._return_to_original,
                                     state="normal")
        self.stats_button.configure(state="disabled")
        self._update_favorite_button()
        self._fill_moves()
        try:
            GAMES_DIR.mkdir(parents=True, exist_ok=True)
            saved = chess.pgn.Game.from_board(changed)
            source_game = self.original_review_state["game"]
            if source_game is not None:
                saved.headers["White"] = source_game.headers.get("White", "Trắng")
                saved.headers["Black"] = source_game.headers.get("Black", "Đen")
            saved.headers["Event"] = "Nhánh phân tích"
            saved.headers["BranchPly"] = str(self.variation_start_ply)
            source_path = self.original_review_state["current_game_path"]
            if source_path is not None:
                saved.headers["SourcePGN"] = source_path.name
            temporary = self.variation_save_path.with_suffix(".part")
            temporary.write_text(str(saved) + "\n", encoding="utf-8")
            temporary.replace(self.variation_save_path)
            self._update_favorite_button()
        except OSError as exc:
            messagebox.showerror("Không lưu được nhánh phân tích", str(exc))
        self._refresh()

    def _return_to_original(self) -> None:
        self._dismiss_coach_panel()
        original = self.original_review_state
        if original is None:
            return
        self._stop_autoplay()
        self._reset_analysis_cache()
        self._clear_annotations()
        self.moves = original["moves"]
        self.positions = original["positions"]
        self.analysis_cache = original["analysis_cache"]
        self.score_cache = original["score_cache"]
        self.best_arrow_cache = original["best_arrow_cache"]
        self.overview_assessments = original["overview_assessments"]
        self.overview_points = original["overview_points"]
        self.current_game_path = original["current_game_path"]
        self.current_game = original["game"]
        self.game_var.set(original["game_var"])
        self.ply = original["ply"]
        self.original_review_state = None
        self.variation_save_path = None
        self.variation_start_ply = None
        self.review_button.configure(text="Xem lại", command=self._review_manual,
                                     state="disabled")
        self.stats_button.configure(state="normal")
        self._update_favorite_button()
        self._fill_moves()
        self._refresh()
        self.status_var.set("Đã quay về ván gốc. Nhánh phân tích vẫn có trong Ván đã lưu.")

    def _toggle_full(self) -> None:
        if not self.reviewing:
            return
        self.full = not self.full
        self.full_button.configure(text="Tắt Full công suất" if self.full else "Bật Full công suất")
        if self.full:
            self.coach_tip_row.pack_forget()
            self.move_list.configure(height=9)
            self.full_frame.pack(fill="x", pady=(0, 5), before=self.detail_area)
        else:
            self.full_frame.pack_forget()
            self.move_list.configure(height=11)
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

    def _set_coach_mood(self, category: str) -> None:
        mood = COACH_MOODS.get(category, "neutral")
        self.coach_mood = mood
        images = self.coach_images.get(mood) or self.coach_images.get("neutral", {})
        if images:
            self.coach_tip_label.configure(image=images["tip"])
            self.coach_idle_image.configure(image=images["popup"])
        neutral = self.coach_images.get("neutral")
        if neutral:
            self.coach_overview_label.configure(image=neutral["overview"])
        if self.review_stage == "step" and self.ply and category in (
            "brilliant", "great", "inaccuracy", "miss", "mistake", "blunder"
        ):
            san = self.positions[self.ply - 1].san(self.moves[self.ply - 1])
            reactions = {
                "brilliant": "Tuyệt vời! Hỏi mình để xem nước thí quân tạo ra điều gì.",
                "great": "Hay lắm! Cùng xem vì sao nước này quan trọng.",
                "inaccuracy": "Khoan đã, có thể còn cách chính xác hơn.",
                "miss": "Ôi, bạn vừa bỏ qua một cơ hội lớn. Cùng xem lại.",
                "mistake": "Nước này làm thế cờ xấu đi. Mình sẽ chỉ ra chỗ khó.",
                "blunder": "Ôi không! Nước này tổn thất nặng. Cùng tìm nguyên nhân.",
            }
            self.coach_tip_var.set(f"Bruno: {san} — {reactions[category]}")

    def _refresh(self) -> None:
        self.selected_square = None
        self._render_board()
        self.move_list.selection_clear(0, "end")
        if self.ply:
            self.move_list.selection_set(self.ply - 1)
            self.move_list.see(self.ply - 1)
        cached = self.analysis_cache.get((self.ply, self.full))
        overview = self.overview_assessments.get(self.ply) if self.reviewing else None
        if self.review_stage == "step":
            if self.ply:
                san = self.positions[self.ply - 1].san(self.moves[self.ply - 1])
                if self.original_review_state is not None:
                    self.coach_tip_var.set(
                        f"Bruno: Đang thử nhánh sau {san}. Cứ đi tiếp trên bàn; bấm Ván gốc để quay lại."
                    )
                else:
                    self.coach_tip_var.set(
                        f"Bruno: {san} là nước đang xem. Bạn có thể bấm hoặc kéo quân để thử hướng khác."
                    )
            else:
                self.coach_tip_var.set(
                    "Bruno: Dùng các nút để xem từng nước, hoặc tự đi quân trên bàn để tạo nhánh mới."
                )
        if cached:
            self._display_analysis(cached)
        elif overview:
            code = overview["category"]
            self.grade_var.set(LABELS[code][0])
            self.grade_label.configure(foreground=text_color(code))
            self._set_grade_badge(code)
            self.detail_var.set(f"Mất {overview['ep_loss'] * 100:.1f}% điểm kỳ vọng")
            self._set_coach_mood(code)
        else:
            self.grade_var.set("Đang phân tích…" if self.ply else "Vị trí ban đầu")
            self._set_grade_badge(None)
            self.detail_var.set("")
            self._set_coach_mood("")
        self._draw_bar(*self.score_cache.get(self.ply, (None, 0.5)))
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
                if sq in self.marked_squares:
                    color = "#e36b56"
                x, y = col * SQUARE, row * SQUARE
                self.board_canvas.create_rectangle(x, y, x + SQUARE, y + SQUARE,
                                                   fill=color, outline=color)
        if self.reviewing and self.review_stage == "step":
            suggested = self.best_arrow_cache.get(self.ply)
            if suggested is not None and suggested in board.legal_moves:
                self._draw_arrow(suggested.from_square, suggested.to_square,
                                 "engine_best_arrow")
        for start, end in sorted(self.arrows):
            self._draw_arrow(start, end, "annotation_arrow")
        legal_targets = set()
        if self.selected_square is not None and self._can_move_board():
            legal_targets = {move.to_square for move in board.legal_moves
                             if move.from_square == self.selected_square}
        for row in range(8):
            for col in range(8):
                file_ = 7 - col if self.flipped else col
                rank_ = row if self.flipped else 7 - row
                sq = chess.square(file_, rank_)
                x, y = col * SQUARE, row * SQUARE
                piece = board.piece_at(sq)
                if piece:
                    icon = self.piece_images.get(("w" if piece.color else "b", piece.symbol().upper()))
                    if icon:
                        self.board_canvas.create_image(x + SQUARE / 2, y + SQUARE / 2,
                                                       image=icon, tags=f"piece_{sq}")
                    else:
                        self.board_canvas.create_text(x + SQUARE / 2, y + SQUARE / 2,
                                                      text=PIECES[piece.symbol()],
                                                      font=("Segoe UI Symbol", 38),
                                                      fill="#171717" if piece.color == chess.BLACK else "#ffffff",
                                                      tags=f"piece_{sq}")
                if sq in legal_targets:
                    if piece:
                        self.board_canvas.create_oval(x + 5, y + 5, x + SQUARE - 5,
                                                      y + SQUARE - 5, outline="#315a20", width=4)
                    else:
                        self.board_canvas.create_oval(x + 25, y + 25, x + 39, y + 39,
                                                      fill="#6f7050", outline="")
                if col == 0:
                    self.board_canvas.create_text(x + 4, y + 4, text=str(rank_ + 1),
                                                  anchor="nw", font=("Segoe UI", 8, "bold"),
                                                  fill="#ffffff" if (file_ + rank_) % 2 == 0 else "#333333")
                if row == 7:
                    self.board_canvas.create_text(x + SQUARE - 4, y + SQUARE - 3,
                                                  text=chess.FILE_NAMES[file_], anchor="se",
                                                  font=("Segoe UI", 8, "bold"),
                                                  fill="#ffffff" if (file_ + rank_) % 2 == 0 else "#333333")
        self._draw_board_grade()
        self._render_material()

    def _draw_board_grade(self) -> None:
        """Place the current move's grade by the piece that just moved."""
        if not self.ply or self.review_stage == "overview":
            return
        assessment = (self.analysis_cache.get((self.ply, self.full))
                      or self.analysis_cache.get((self.ply, not self.full)))
        if assessment is None and self.reviewing:
            assessment = self.overview_assessments.get(self.ply)
        category = assessment.get("category") if assessment else None
        if category not in LABELS:
            return
        square = self.moves[self.ply - 1].to_square
        if self.positions[self.ply].piece_at(square) is None:
            return
        col = 7 - chess.square_file(square) if self.flipped else chess.square_file(square)
        row = chess.square_rank(square) if self.flipped else 7 - chess.square_rank(square)
        size = 30
        center_x = max(size / 2 + 2, min(BOARD_SIZE - size / 2 - 2,
                                       (col + 1) * SQUARE - 5))
        center_y = max(size / 2 + 2, min(BOARD_SIZE - size / 2 - 2,
                                       row * SQUARE + 5))
        draw_badge(self.board_canvas, category, size,
                   origin=(center_x - size / 2, center_y - size / 2),
                   clear=False, tag="move_grade")

    def _render_material(self) -> None:
        self.material_state = material_snapshot(self.positions[0], self.moves, self.ply)
        top_color = chess.WHITE if self.flipped else chess.BLACK
        self._draw_material_side(self.top_material, top_color)
        self._draw_material_side(self.bottom_material, not top_color)

    def _draw_material_side(self, canvas: tk.Canvas, color: chess.Color) -> None:
        canvas.delete("all")
        if self.current_game is None:
            name = "Trắng" if color == chess.WHITE else "Đen"
        else:
            name = self.current_game.headers.get("White" if color == chess.WHITE else "Black", "?")
        canvas.create_text(52, 3, text=name, anchor="nw", fill="#f3f0e9",
                           font=("Segoe UI", 9, "bold"))
        captured = self.material_state["captured"][color]
        count = sum(captured.values())
        x = 58
        icon_color = "b" if color == chess.WHITE else "w"
        for piece_type in DISPLAY_ORDER:
            icon = self.capture_icons.get((icon_color, chess.piece_symbol(piece_type).upper()))
            for _ in range(captured[piece_type]):
                if icon is not None:
                    canvas.create_image(x + 8, 28, image=icon)
                else:
                    canvas.create_text(x + 8, 28, text=chess.piece_symbol(piece_type).upper(),
                                       fill="#e8e3d8", font=("Segoe UI", 10, "bold"))
                x += 18
        canvas.create_text(x + 5, 28, text=f"Đã ăn {count}", anchor="w",
                           fill="#bcb6aa", font=("Segoe UI", 9))
        lead = self.material_state["balance"] * (1 if color == chess.WHITE else -1)
        if lead > 0:
            canvas.create_text(x + 83, 28, text=f"+{lead}", anchor="w",
                               fill="#a8d77a", font=("Segoe UI", 10, "bold"))

    def _draw_bar(self, score: chess.engine.Score | None, white_ep: float = 0.5) -> None:
        self.bar_orientation_var.set(
            "Thanh đánh giá: Trắng ở trên, Đen ở dưới" if self.flipped
            else "Thanh đánh giá: Đen ở trên, Trắng ở dưới"
        )
        if score is not None:
            self.bar_last_score = score
            bottom_share = 1 - white_ep if self.flipped else white_ep
            self.bar_target_share = max(0.02, min(0.98, bottom_share))
        display_score = self.bar_last_score
        self.eval_var.set(score_text(-display_score if self.flipped else display_score)
                          if display_score is not None else "0.00")
        if self.bar_job is None:
            self._animate_bar()

    def _animate_bar(self) -> None:
        self.bar_job = None
        remaining = self.bar_target_share - self.bar_display_share
        if abs(remaining) < 0.002:
            self.bar_display_share = self.bar_target_share
        else:
            self.bar_display_share += remaining * 0.22
        self.bar.delete("all")
        bottom_height = int(BOARD_SIZE * self.bar_display_share)
        top_color = "#f3f3f3" if self.flipped else "#252525"
        bottom_color = "#252525" if self.flipped else "#f3f3f3"
        self.bar.create_rectangle(0, 0, 40, BOARD_SIZE - bottom_height,
                                  fill=top_color, outline="")
        self.bar.create_rectangle(0, BOARD_SIZE - bottom_height, 40, BOARD_SIZE,
                                  fill=bottom_color, outline="")
        if self.bar_display_share != self.bar_target_share:
            self.bar_job = self.root.after(16, self._animate_bar)

    def _request_analysis(self) -> None:
        self.generation += 1
        generation = self.generation
        self._cancel_current_analysis()
        try:
            path = resolve_engine(self.engine_var.get())
        except FileNotFoundError:
            self.status_var.set("Chọn stockfish.exe để bắt đầu phân tích.")
            return
        try:
            seconds = float(self.seconds_var.get()) if self.full else 1.0
        except ValueError:
            seconds = 3.0
        previous = self.positions[self.ply - 1].copy(stack=True) if self.ply else None
        move = self.moves[self.ply - 1] if self.ply else None
        current = self.positions[self.ply].copy(stack=True)
        if (self.ply, self.full) in self.analysis_cache:
            self._display_analysis(self.analysis_cache[(self.ply, self.full)])
            return
        self.status_var.set("Đang phân tích sâu…" if self.full else "Đang đánh giá nước vừa đi…")
        cancel = threading.Event()
        self.analysis_cancel = cancel
        self.future = self.executor.submit(
            self.analysis_engine.run, path, previous, move, current, self.full,
            seconds, self.reviewing and self.review_stage == "step",
            lambda score, white_ep: self.progress_results.put((generation, score, white_ep)),
            cancel,
        )
        self.future.add_done_callback(lambda future: self.results.put((generation, future)))

    def _poll_results(self) -> None:
        try:
            while True:
                generation, score, white_ep = self.progress_results.get_nowait()
                if generation == self.generation:
                    self.score_cache[self.ply] = (score, white_ep)
                    self._draw_bar(score, white_ep)
                    self.status_var.set("Ước lượng nhanh · đang kiểm tra nước đi…")
        except queue.Empty:
            pass
        try:
            while True:
                generation, future = self.results.get_nowait()
                if generation != self.generation or future.cancelled():
                    continue
                self.analysis_cancel = None
                try:
                    result = future.result()
                except Exception as exc:
                    self.grade_var.set("Không phân tích được")
                    self._set_grade_badge(None)
                    self.detail_var.set("Hãy kiểm tra tệp Stockfish và thử lại.")
                    self.status_var.set(f"Stockfish gặp lỗi: {exc}")
                    continue
                self.analysis_cache[(self.ply, self.full)] = result
                self.score_cache[self.ply] = (result["score"], result["white_ep"])
                self._display_analysis(result)
                if self.live_tracker is not None:
                    self._fill_moves()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    def _set_grade_badge(self, category: str | None) -> None:
        draw_badge(self.grade_badge, category, 48)
        if category in LABELS:
            self.grade_badge.pack(side="left", before=self.grade_label)
        else:
            self.grade_badge.pack_forget()

    def _display_analysis(self, result: dict) -> None:
        if self.reviewing and self.review_stage == "step":
            suggested = result.get("next_best_move")
            if suggested is not None and suggested in self.positions[self.ply].legal_moves:
                self.best_arrow_cache[self.ply] = suggested
            else:
                self.best_arrow_cache.pop(self.ply, None)
        category = result["category"]
        name, color = LABELS.get(category, ("Vị trí ban đầu", "#ede9e1"))
        self.grade_var.set(name)
        self.grade_label.configure(foreground=text_color(category) if category in LABELS else color)
        self._set_grade_badge(category)
        self._set_coach_mood(category)
        self.detail_var.set(result["detail"])
        self._draw_bar(result["score"], result["white_ep"])
        self._render_board()
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
        self.status_var.set("")

    def _dismiss_coach_panel(self) -> None:
        if self.coach_close is not None:
            close = self.coach_close
            self.coach_close = None
            close()

    def _ask_coach(self) -> None:
        if self.review_stage != "step" or self.ply == 0:
            self.status_var.set("Chọn một nước trong danh sách rồi hỏi HLV Bruno.")
            return
        self._dismiss_coach_panel()
        self._stop_autoplay()
        self.coach_tip_row.pack_forget()
        self.coach_idle.pack_forget()
        panel = ttk.LabelFrame(self.detail_area, text="Bruno · HLV cờ", padding=8)
        panel.pack(side="left", fill="both", expand=True, before=self.review_sidebar)
        self.coach_panel = panel
        header = ttk.Frame(panel)
        header.pack(fill="x")
        popup_image_label = ttk.Label(header)
        popup_image_label.pack(side="left", padx=(0, 10))
        current_images = self.coach_images.get(self.coach_mood)
        if current_images:
            popup_image_label.configure(image=current_images["popup"])
        ttk.Label(header, text="Hỏi về nước vừa chọn. Mình sẽ đi từng nước trong biến thể để bạn thấy điều gì xảy ra trên bàn.",
                  wraplength=300, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        question = tk.StringVar(value="Tại sao nước này được đánh giá như vậy?")
        entry = ttk.Entry(panel, textvariable=question)
        entry.pack(fill="x", pady=(4, 6))
        response_row = ttk.Frame(panel)
        response_row.pack(fill="both", expand=True)
        response = tk.Text(response_row, height=8, wrap="word", font=("Segoe UI", 10),
                           bg="#302d29", fg="#f2eee8", borderwidth=0,
                           padx=10, pady=8)
        response.pack(side="left", fill="both", expand=True)
        response_scroll = ttk.Scrollbar(response_row, command=response.yview)
        response_scroll.pack(side="right", fill="y")
        response.configure(yscrollcommand=response_scroll.set)
        chosen_ply = self.ply
        before_board = self.positions[chosen_ply - 1].copy(stack=True)
        played_move = self.moves[chosen_ply - 1]
        after_board = before_board.copy(stack=True)
        after_board.push(played_move)
        assessment_holder: dict = {"value": None, "deep": None}
        deep_future: dict = {"value": None}
        line_state: dict = {"moves": [], "index": 0, "board": None}
        demonstration: dict = {"job": None, "moves": [], "index": 0, "board": None}
        answer_generation = 0

        def find_assessment() -> dict | None:
            for mode in (self.full, not self.full):
                cached = self.analysis_cache.get((chosen_ply, mode))
                if cached and cached.get("assessment"):
                    return cached["assessment"]
            return self.overview_assessments.get(chosen_ply)

        def stop_demonstration() -> None:
            job = demonstration["job"]
            if job is not None and panel.winfo_exists():
                panel.after_cancel(job)
            demonstration["job"] = None

        def animate_next() -> None:
            demonstration["job"] = None
            if not panel.winfo_exists() or self.review_stage != "step":
                return
            moves = demonstration["moves"]
            index = demonstration["index"]
            expected = demonstration["board"]
            if expected is None or index >= len(moves):
                return
            current = self.positions[self.ply]
            if current.fen() != expected.fen():
                append_note("Bạn đã đổi vị trí trên bàn nên mình dừng minh họa.")
                return
            move = moves[index]
            if move not in current.legal_moves:
                append_note("Biến thể không còn hợp lệ từ vị trí hiện tại.")
                return
            san = current.san(move)
            self._play_move(move)
            expected.push(move)
            demonstration["index"] = index + 1
            append_note(f"{index + 1}/{len(moves)} · {san}")
            if index + 1 < len(moves):
                demonstration["job"] = panel.after(800, animate_next)
            else:
                append_note("Đã đi hết biến thể minh họa. Bạn có thể tự thử nước khác trên bàn.")

        def start_demonstration(assessment: dict) -> None:
            pv = assessment.get("played_pv", [])
            if not pv or pv[0] != played_move:
                append_note("Stockfish chưa trả về biến thể tiếp theo để minh họa.")
                return
            if (self.review_stage != "step" or chosen_ply > len(self.moves)
                    or self.positions[chosen_ply - 1].fen() != before_board.fen()
                    or self.moves[chosen_ply - 1] != played_move):
                append_note("Vị trí đã thay đổi. Hãy chọn lại nước cần giải thích.")
                return
            self._go_to(chosen_ply - 1)
            demonstration.update({"moves": pv[:], "index": 0,
                                  "board": before_board.copy(stack=True)})
            append_note("Mình sẽ đi nước bạn chọn và các câu trả lời Stockfish dự kiến trên bàn.")
            demonstration["job"] = panel.after(250, animate_next)

        def answer(generation: int, attempt: int = 0) -> None:
            if not panel.winfo_exists():
                return
            if generation != answer_generation:
                return
            assessment = assessment_holder["deep"] or find_assessment() or assessment_holder["value"]
            if assessment is None and attempt < 30:
                response.delete("1.0", "end")
                response.insert("1.0", "Bruno đang xem lại vị trí và các biến thể…")
                panel.after(500, lambda: answer(generation, attempt + 1))
                return
            if (assessment is not None and len(assessment.get("played_pv", [])) < 3
                    and not after_board.is_game_over()):
                future = deep_future["value"]
                if future is None:
                    try:
                        path = resolve_engine(self.engine_var.get())
                        future = self.executor.submit(
                            self.analysis_engine.run, path, before_board.copy(stack=True),
                            played_move, after_board.copy(stack=True), False, 2.0, False,
                        )
                        deep_future["value"] = future
                    except FileNotFoundError:
                        future = None
                if future is not None and not future.done():
                    response.delete("1.0", "end")
                    response.insert("1.0", "Bruno đang phân tích sâu để tìm chuỗi nước minh họa…")
                    panel.after(150, lambda: answer(generation, attempt + 1))
                    return
                if future is not None:
                    try:
                        assessment = future.result()["assessment"]
                        assessment_holder["deep"] = assessment
                    except Exception as exc:
                        self.status_var.set(f"Bruno không phân tích sâu được: {exc}")
            if assessment is None:
                content = "Chưa lấy được dữ liệu từ Stockfish. Hãy kiểm tra đường dẫn engine rồi thử lại."
            else:
                assessment_holder["value"] = assessment
                panel.configure(text=f"Bruno · {before_board.san(played_move)} — {LABELS[assessment['category']][0]}")
                mood = COACH_MOODS.get(assessment["category"], "neutral")
                images = self.coach_images.get(mood)
                if images:
                    popup_image_label.configure(image=images["popup"])
                content = explain_move(before_board, played_move, assessment, question.get())
                if assessment.get("best_pv"):
                    content += "\n\nBấm ‘Đi nước mạnh nhất trên bàn’ để xem quân di chuyển thật, rồi bấm ‘Xem tiếp biến thể’."
                    best_button.configure(state="normal")
            response.delete("1.0", "end")
            response.insert("1.0", content)
            response.yview_moveto(0.0)
            if assessment is not None:
                start_demonstration(assessment)

        def request_answer() -> None:
            nonlocal answer_generation
            stop_demonstration()
            answer_generation += 1
            answer(answer_generation)

        def append_note(note: str) -> None:
            top, _ = response.yview()
            response.insert("end", f"\n\nBruno: {note}")
            response.yview_moveto(top)

        def play_best() -> None:
            stop_demonstration()
            assessment = assessment_holder["value"]
            pv = assessment.get("best_pv", []) if assessment else []
            if not pv or self.review_stage != "step" or chosen_ply > len(self.moves):
                return
            if (self.positions[chosen_ply - 1].fen() != before_board.fen()
                    or self.moves[chosen_ply - 1] != played_move):
                append_note("Vị trí đã thay đổi. Hãy quay về ván gốc rồi chọn lại nước cần giải thích.")
                return
            self._go_to(chosen_ply - 1)
            if pv[0] not in self.positions[self.ply].legal_moves:
                append_note("Không thể đi biến thể này từ vị trí hiện tại.")
                return
            san = self.positions[self.ply].san(pv[0])
            line_state["moves"] = pv[:]
            line_state["index"] = 0
            line_state["board"] = before_board.copy(stack=True)
            self._play_move(pv[0])
            line_state["board"].push(pv[0])
            line_state["index"] = 1
            next_button.configure(state="normal" if len(pv) > 1 else "disabled")
            append_note(f"Đã đi {san} trên bàn. Đây là nước Stockfish chọn từ vị trí trước nước bạn hỏi.")

        def play_next() -> None:
            stop_demonstration()
            moves = line_state["moves"]
            index = line_state["index"]
            expected = line_state["board"]
            if index >= len(moves) or expected is None or self.review_stage != "step":
                return
            current = self.positions[self.ply]
            if current.fen() != expected.fen():
                append_note("Bạn đã đổi vị trí trên bàn. Bấm lại ‘Đi nước mạnh nhất trên bàn’ để xem từ đầu.")
                return
            move = moves[index]
            if move not in current.legal_moves:
                append_note("Biến thể không còn hợp lệ từ vị trí này.")
                return
            san = current.san(move)
            self._play_move(move)
            expected.push(move)
            line_state["index"] = index + 1
            next_button.configure(state="normal" if index + 1 < len(moves) else "disabled")
            append_note(f"Tiếp theo {san}. Bạn có thể dừng ở đây và tự thử nước khác trên bàn.")

        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Giải thích", command=request_answer,
                   style="Accent.TButton").pack(side="left")
        best_button = ttk.Button(buttons, text="Đi nước mạnh nhất trên bàn",
                                 command=play_best, state="disabled")
        best_button.pack(side="left", padx=6)
        more_buttons = ttk.Frame(panel)
        more_buttons.pack(fill="x", pady=(4, 0))
        next_button = ttk.Button(more_buttons, text="Xem tiếp biến thể", command=play_next,
                                 state="disabled")
        next_button.pack(side="left")
        entry.bind("<Return>", lambda _event: request_answer())
        response.insert("1.0", "Nhấn Giải thích để nghe Bruno và xem biến thể tự chạy trên bàn cờ.")

        def close_panel() -> None:
            stop_demonstration()
            self.coach_close = None
            self.coach_panel = None
            if panel.winfo_exists():
                panel.destroy()
            if self.review_stage == "step":
                self.coach_idle.pack(side="left", fill="both", expand=True,
                                     before=self.review_sidebar)

        ttk.Button(more_buttons, text="Đóng giải thích", command=close_panel).pack(side="left", padx=6)
        self.coach_close = close_panel

    def _close(self) -> None:
        self._stop_live_capture()
        if self.bar_job is not None:
            self.root.after_cancel(self.bar_job)
            self.bar_job = None
        self._dismiss_coach_panel()
        self.stats_cancel.set()
        self.overview_cancel.set()
        self._stop_autoplay()
        self._cancel_current_analysis()
        self.executor.submit(self.analysis_engine.close)
        self.executor.shutdown(wait=False)
        self.stats_executor.shutdown(wait=False, cancel_futures=True)
        self.overview_executor.shutdown(wait=False, cancel_futures=True)
        self.sync_executor.shutdown(wait=False, cancel_futures=True)
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
