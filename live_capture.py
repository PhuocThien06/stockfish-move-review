"""Observe a selected desktop window and infer moves from board image changes."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import median

import chess
from PIL import Image, ImageOps, ImageStat


def visible_windows() -> list[tuple[int, str]]:
    """List titled Windows windows; no browser data or network access is used."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(hwnd: int, _param: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value.strip()
                if title:
                    found.append((int(hwnd), title))
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return found


class WindowCaptureStream:
    """Keep the latest WGC frame from a Windows window, even when occluded."""

    def __init__(self, hwnd: int) -> None:
        from windows_capture import WindowsCapture

        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._frame: Image.Image | None = None
        self._frames: deque[Image.Image] = deque(maxlen=128)
        self.closed = False
        self._stopped = False
        self._capture = WindowsCapture(
            window_hwnd=hwnd, cursor_capture=False, draw_border=False,
            minimum_update_interval=0,
        )

        @self._capture.event
        def on_frame_arrived(frame, _capture_control) -> None:
            image = Image.frombytes("RGB", (frame.width, frame.height),
                                    frame.frame_buffer.tobytes(), "raw", "BGRX")
            with self._lock:
                self._frame = image
                self._frames.append(image)
            self._ready.set()

        @self._capture.event
        def on_closed() -> None:
            self.closed = True
            self._ready.set()

        self._control = self._capture.start_free_threaded()

    def latest(self, timeout: float = 0) -> Image.Image:
        if not self._ready.wait(timeout):
            raise TimeoutError("Chưa có ảnh từ cửa sổ. Hãy thử đưa cửa sổ lên trước.")
        with self._lock:
            image = self._frame
        if image is None:
            raise OSError("Cửa sổ đã đóng hoặc không thể chụp.")
        return image

    def drain(self, limit: int = 24) -> list[Image.Image]:
        """Return captured frames in arrival order instead of skipping to the newest."""
        with self._lock:
            frames = [self._frames.popleft() for _ in range(min(limit, len(self._frames)))]
        return frames

    def close(self) -> None:
        if not self._stopped:
            self._stopped = True
            self.closed = True
            try:
                self._control.stop()
            except Exception:
                pass  # The source window may already have closed the native session.


def board_crop(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = box
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError("Vùng bàn cờ nằm ngoài cửa sổ đã chọn.")
    width, height = right - left, bottom - top
    if min(width, height) < 200 or abs(width - height) > min(width, height) * .08:
        raise ValueError("Hãy chọn sát mép bàn cờ vuông 8×8, không gồm danh sách nước.")
    cropped = image.crop(box).resize((512, 512), Image.Resampling.BILINEAR)
    if ImageStat.Stat(ImageOps.grayscale(cropped)).stddev[0] < 12:
        raise ValueError("Ảnh bàn cờ trống hoặc bị che. Hãy đưa cửa sổ lên trước và thử lại.")
    return cropped


def reduce_glare(image: Image.Image) -> Image.Image:
    """Compress bright SDR preview values without changing Windows HDR settings."""
    lut = [value if value <= 180 else round(180 + (value - 180) * .6)
           for value in range(256)]
    return image.convert("RGB").point(lut * 3)


def _cell_signature(cell: Image.Image) -> bytes:
    cell = ImageOps.grayscale(cell.crop((6, 6, 58, 58)))
    pixels = list(cell.resize((26, 26), Image.Resampling.BILINEAR).tobytes())
    background = sorted(pixels)[len(pixels) // 2]
    return bytes(max(0, min(255, value - background + 128)) for value in pixels)


def _signature(image: Image.Image, flipped: bool) -> list[bytes]:
    """Describe piece shapes while discounting solid square and highlight colors."""
    image = image.resize((512, 512), Image.Resampling.BILINEAR)
    signatures: list[bytes] = [b""] * 64
    for row in range(8):
        for col in range(8):
            cell = image.crop((col * 64, row * 64, col * 64 + 64, row * 64 + 64))
            signature = _cell_signature(cell)
            file_ = 7 - col if flipped else col
            rank_ = row if flipped else 7 - row
            signatures[chess.square(file_, rank_)] = signature
    return signatures


@lru_cache(maxsize=16)
def _piece_templates(light: tuple[int, int, int],
                     dark: tuple[int, int, int]) -> dict[bool, dict[str, bytes]]:
    sprites = Path(__file__).resolve().parent / "pieces"
    result = {}
    for is_dark, background in ((False, light), (True, dark)):
        templates = {".": _cell_signature(Image.new("RGB", (64, 64), background))}
        for color in "wb":
            for symbol in "PNBRQK":
                sprite = Image.open(sprites / f"{color}{symbol}.png").convert("RGBA")
                cell = Image.new("RGB", (64, 64), background)
                cell.paste(sprite, (0, 0), sprite)
                templates[symbol if color == "w" else symbol.lower()] = _cell_signature(cell)
        result[is_dark] = templates
    return result


def _square_backgrounds(image: Image.Image, flipped: bool) -> tuple[tuple[int, int, int], ...]:
    image = image.resize((512, 512), Image.Resampling.BILINEAR).convert("RGB")
    samples: dict[bool, list[tuple[int, int, int]]] = {False: [], True: []}
    for row in range(8):
        for col in range(8):
            file_ = 7 - col if flipped else col
            rank = row if flipped else 7 - row
            dark = (file_ + rank) % 2 == 0
            samples[dark].append(image.getpixel((col * 64 + 4, row * 64 + 4)))
    return tuple(tuple(round(median(pixel[channel] for pixel in samples[dark]))
                       for channel in range(3)) for dark in (False, True))


def recognize_board(image: Image.Image, flipped: bool, turn: chess.Color) -> chess.Board:
    """Read a Neo board from a captured image; fail on ambiguous squares."""
    backgrounds = _square_backgrounds(image, flipped)
    templates = _piece_templates(*backgrounds)
    # White pieces can have very small margins against clipped HDR whites.
    min_margin = 0.4 if min(backgrounds[0]) >= 245 else 3
    position = chess.Board(None)
    for square, signature in enumerate(_signature(image, flipped)):
        dark = (chess.square_file(square) + chess.square_rank(square)) % 2 == 0
        scores = sorted((_difference(signature, sample), symbol)
                        for symbol, sample in templates[dark].items())
        (distance, symbol), (second, _) = scores[:2]
        if distance > 35 or second - distance < min_margin:
            raise ValueError(f"Không nhận rõ quân ở ô {chess.square_name(square)}; "
                             "hãy khoanh sát bàn cờ và dùng bộ quân Neo.")
        if symbol != ".":
            position.set_piece_at(square, chess.Piece.from_symbol(symbol))
    position.turn = turn
    position.castling_rights = 0
    for color, rank in ((chess.WHITE, 0), (chess.BLACK, 7)):
        king = position.piece_at(chess.square(4, rank))
        if king == chess.Piece(chess.KING, color):
            for file_ in (0, 7):
                square = chess.square(file_, rank)
                if position.piece_at(square) == chess.Piece(chess.ROOK, color):
                    position.castling_rights |= chess.BB_SQUARES[square]
    if not position.is_valid():
        raise ValueError("Thế cờ nhận từ ảnh không hợp lệ. Kiểm tra lượt đi, vùng bàn và chiều bàn.")
    return position


def align_board(image: Image.Image, box: tuple[int, int, int, int],
                flipped: bool, turn: chess.Color,
                ) -> tuple[tuple[int, int, int, int], chess.Board, Image.Image]:
    """Trim a small selected border and select the clearest legal board."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    valid: list[tuple[float, tuple[int, int, int, int], chess.Board, Image.Image]] = []
    initial: list[tuple[float, tuple[int, int, int, int], chess.Board, Image.Image]] = []
    last_error = "Không nhận được bàn cờ từ vùng đã chọn."
    start = chess.Board()
    for fraction in (0, .005, .01, .015, .02, .025):
        dx, dy = round(width * fraction), round(height * fraction)
        candidate = (left + dx, top + dy, right - dx, bottom - dy)
        try:
            cropped = board_crop(image, candidate)
        except ValueError as exc:
            last_error = str(exc)
            continue
        backgrounds = _square_backgrounds(cropped, flipped)
        templates = _piece_templates(*backgrounds)
        signatures = _signature(cropped, flipped)
        costs = []
        for square, signature in enumerate(signatures):
            dark = (chess.square_file(square) + chess.square_rank(square)) % 2 == 0
            costs.append({symbol: _difference(signature, sample)
                          for symbol, sample in templates[dark].items()})
        greedy_cost = sum(min(cell.values()) for cell in costs)
        try:
            board = recognize_board(cropped, flipped, turn)
        except ValueError as exc:
            last_error = str(exc)
        else:
            valid.append((greedy_cost, candidate, board, cropped))
        if turn == chess.WHITE:
            middle_empty = sum(min(costs[square], key=costs[square].get) == "."
                               for square in chess.SQUARES
                               if 2 <= chess.square_rank(square) <= 5)
            start_cost = sum(costs[square][start.piece_at(square).symbol()
                                            if start.piece_at(square) else "."]
                             for square in chess.SQUARES)
            if (middle_empty >= 30 and start_cost <= 900
                    and start_cost - greedy_cost <= max(25, greedy_cost * .07)):
                initial.append((start_cost, candidate, start.copy(), cropped))
    if initial:
        _, candidate, board, cropped = min(initial, key=lambda item: item[0])
        return candidate, board, cropped
    if valid:
        _, candidate, board, cropped = min(valid, key=lambda item: item[0])
        return candidate, board, cropped
    raise ValueError(last_error)


def _difference(first: bytes, second: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(first, second)) / len(first)


def _highlighted_squares(image: Image.Image, flipped: bool) -> set[int] | None:
    """Find the two last-move squares when the board marks them clearly."""
    frame = image.resize((512, 512), Image.Resampling.BILINEAR).convert("RGB")
    backgrounds = _square_backgrounds(frame, flipped)
    marked = set()
    for row in range(8):
        for col in range(8):
            file_ = 7 - col if flipped else col
            rank = row if flipped else 7 - row
            square = chess.square(file_, rank)
            base = backgrounds[(file_ + rank) % 2 == 0]
            pixel = frame.getpixel((col * 64 + 4, row * 64 + 4))
            if sum(abs(pixel[channel] - base[channel]) for channel in range(3)) >= 40:
                marked.add(square)
    return marked if len(marked) == 2 else None


def infer_turn(image: Image.Image, board: chess.Board,
               flipped: bool) -> chess.Color | None:
    """Infer the next side from the highlighted previous move when available."""
    if board.board_fen() == chess.STARTING_BOARD_FEN:
        return chess.WHITE
    highlighted = _highlighted_squares(image, flipped)
    if highlighted is None:
        return None
    occupied = [board.piece_at(square) for square in highlighted
                if board.piece_at(square) is not None]
    if len(occupied) == 1:
        return not occupied[0].color
    return None


def _changed_squares(board: chess.Board, move: chess.Move) -> set[int]:
    changed = {move.from_square, move.to_square}
    if board.is_en_passant(move):
        changed.add(move.to_square - 8 if board.turn == chess.WHITE else move.to_square + 8)
    if board.is_castling(move):
        rank = 0 if board.turn == chess.WHITE else 7
        if chess.square_file(move.to_square) == 6:
            changed.update((chess.square(7, rank), chess.square(5, rank)))
        else:
            changed.update((chess.square(0, rank), chess.square(3, rank)))
    return changed


@dataclass
class LiveBoardTracker:
    board: chess.Board
    flipped: bool
    reference: list[bytes] | None = None
    unmatched_frames: int = 0
    last_unmatched: list[bytes] | None = None
    pending_signature: list[bytes] | None = None
    pending_moves: list[chess.Move] | None = None
    pending_since: float = 0.0
    pending_delay: float = 0.0

    def _hold(self, moves: list[chess.Move], current: list[bytes],
              now: float, highlighted: set[int] | None) -> list[chess.Move]:
        self.pending_moves = moves
        self.pending_signature = current
        self.pending_since = now
        self.pending_delay = .12 if highlighted else .45
        self.last_unmatched = None
        self.unmatched_frames = 0
        return []

    def observe(self, image: Image.Image, now: float | None = None) -> list[chess.Move]:
        now = time.monotonic() if now is None else now
        current = _signature(image, self.flipped)
        if self.reference is None:
            self.reference = current
            return []
        if self.pending_signature is not None:
            if max(_difference(a, b) for a, b in zip(self.pending_signature, current)) < 2.5:
                if now - self.pending_since >= self.pending_delay:
                    moves = self.pending_moves or []
                    for move in moves:
                        self.board.push(move)
                    self.reference = current
                    self.pending_signature = None
                    self.pending_moves = None
                    self.unmatched_frames = 0
                    self.last_unmatched = None
                    return moves
                return []
            self.pending_signature = None
            self.pending_moves = None
        changes = [_difference(a, b) for a, b in zip(self.reference, current)]
        if max(changes) < 7:
            self.unmatched_frames = 0
            return []
        if self.last_unmatched is not None and max(
            _difference(a, b) for a, b in zip(self.last_unmatched, current)
        ) < 2.5:
            self.unmatched_frames += 1
            return []
        candidates: list[tuple[float, chess.Move, set[int]]] = []
        seen: set[tuple[int, int]] = set()
        for move in sorted(self.board.legal_moves,
                           key=lambda item: item.promotion not in (None, chess.QUEEN)):
            endpoints = (move.from_square, move.to_square)
            if endpoints in seen:  # Prefer queen when promotion endpoints coincide.
                continue
            seen.add(endpoints)
            changed = _changed_squares(self.board, move)
            if min(changes[move.from_square], changes[move.to_square]) < 8:
                continue
            signal = sum(changes[square] for square in changed)
            spill = sum(sorted((amount for square, amount in enumerate(changes)
                                if square not in changed), reverse=True)[:2])
            candidates.append((signal - spill, move, changed))
        candidates.sort(key=lambda item: item[0], reverse=True)
        highlighted = _highlighted_squares(image, self.flipped)
        if candidates:
            best_score, move, expected = candidates[0]
            if (best_score >= 22
                    and (len(candidates) == 1 or best_score - candidates[1][0] >= 4)
                    and sum(amount for square, amount in enumerate(changes)
                            if square not in expected and amount > 8)
                    <= sum(changes[s] for s in expected) * .55
                    and (highlighted is None
                         or highlighted == {move.from_square, move.to_square})):
                return self._hold([move], current, now, highlighted)

        # Two moves may occur between captured frames. Match the visible piece
        # placement to legal pairs rather than guessing a single move.
        try:
            target = recognize_board(image, self.flipped, self.board.turn).piece_map()
        except ValueError:
            self.last_unmatched = current
            self.unmatched_frames += 1
            return []
        if target == self.board.piece_map():
            self.reference = current
            self.unmatched_frames = 0
            self.last_unmatched = None
            return []
        matches: list[tuple[chess.Move, chess.Move]] = []
        probe = self.board.copy(stack=False)
        for first in list(probe.legal_moves):
            probe.push(first)
            for second in list(probe.legal_moves):
                probe.push(second)
                if probe.piece_map() == target:
                    matches.append((first, second))
                probe.pop()
            probe.pop()
        if len(matches) == 1:
            pair = list(matches[0])
            if (highlighted is None or highlighted
                    == {pair[-1].from_square, pair[-1].to_square}):
                return self._hold(pair, current, now, highlighted)
        self.last_unmatched = current
        self.unmatched_frames += 1
        return []
