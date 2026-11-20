"""Observe a selected desktop window and infer moves from board image changes."""

from __future__ import annotations

import ctypes
import sys
import threading
from dataclasses import dataclass

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
        self.closed = False
        self._stopped = False
        self._capture = WindowsCapture(
            window_hwnd=hwnd, cursor_capture=False, draw_border=False,
            minimum_update_interval=150,
        )

        @self._capture.event
        def on_frame_arrived(frame, _capture_control) -> None:
            image = Image.frombytes("RGB", (frame.width, frame.height),
                                    frame.frame_buffer.tobytes(), "raw", "BGRX")
            with self._lock:
                self._frame = image
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


def _signature(image: Image.Image, flipped: bool) -> list[bytes]:
    """Describe piece shapes while discounting solid square and highlight colors."""
    image = image.resize((512, 512), Image.Resampling.BILINEAR)
    signatures: list[bytes] = [b""] * 64
    for row in range(8):
        for col in range(8):
            cell = ImageOps.grayscale(image.crop((col * 64 + 6, row * 64 + 6,
                                                  col * 64 + 58, row * 64 + 58)))
            cell = cell.resize((26, 26), Image.Resampling.BILINEAR)
            pixels = list(cell.tobytes())
            background = sorted(pixels)[len(pixels) // 2]
            signature = bytes(max(0, min(255, value - background + 128)) for value in pixels)
            file_ = 7 - col if flipped else col
            rank_ = row if flipped else 7 - row
            signatures[chess.square(file_, rank_)] = signature
    return signatures


def _difference(first: bytes, second: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(first, second)) / len(first)


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
    pending: list[bytes] | None = None
    pending_count: int = 0
    unmatched_frames: int = 0

    def observe(self, image: Image.Image) -> chess.Move | None:
        current = _signature(image, self.flipped)
        if self.reference is None:
            self.reference = current
            return None
        if self.pending is not None and max(
            _difference(a, b) for a, b in zip(self.pending, current)
        ) < 2.5:
            self.pending_count += 1
        else:
            self.pending = current
            self.pending_count = 1
        if self.pending_count < 2:
            return None
        changes = [_difference(a, b) for a, b in zip(self.reference, current)]
        if max(changes) < 7:
            self.unmatched_frames = 0
            return None
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
        if not candidates:
            self.unmatched_frames += 1
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, move, expected = candidates[0]
        if best_score < 22 or (len(candidates) > 1 and best_score - candidates[1][0] < 4):
            self.unmatched_frames += 1
            return None
        if sum(amount for square, amount in enumerate(changes)
               if square not in expected and amount > 8) > sum(changes[s] for s in expected) * .55:
            self.unmatched_frames += 1
            return None
        self.board.push(move)
        self.reference = current
        self.pending = None
        self.pending_count = 0
        self.unmatched_frames = 0
        return move
