"""Synthetic Neo-board frames exercise move recognition without screen access."""

from pathlib import Path
import unittest

import chess
from PIL import Image, ImageDraw

from live_capture import LiveBoardTracker


PIECES = Path(__file__).resolve().parents[1] / "pieces"


def render(board: chess.Board, flipped: bool = False,
           highlights: tuple[int, ...] = ()) -> Image.Image:
    image = Image.new("RGB", (512, 512))
    draw = ImageDraw.Draw(image)
    for row in range(8):
        for col in range(8):
            file_ = 7 - col if flipped else col
            rank = row if flipped else 7 - row
            square = chess.square(file_, rank)
            color = "#f0d9b5" if (file_ + rank) % 2 else "#b58863"
            if square in highlights:
                color = "#cdd26a" if (file_ + rank) % 2 else "#a6ad55"
            left, top = col * 64, row * 64
            draw.rectangle((left, top, left + 63, top + 63), fill=color)
            piece = board.piece_at(square)
            if piece:
                name = f"{'w' if piece.color else 'b'}{piece.symbol().upper()}.png"
                sprite = Image.open(PIECES / name).convert("RGBA")
                image.paste(sprite, (left, top), sprite)
    return image


class LiveCaptureTests(unittest.TestCase):
    def test_tracks_both_sides_and_castling(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        self.assertIsNone(tracker.observe(render(board)))
        for san in ("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O"):
            move = board.parse_san(san)
            board.push(move)
            frame = render(board)
            self.assertIsNone(tracker.observe(frame))
            self.assertEqual(move, tracker.observe(frame), san)
        self.assertEqual(board.fen(), tracker.board.fen())

    def test_tracks_flipped_board(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), True)
        tracker.observe(render(board, True))
        move = board.parse_san("d4")
        board.push(move)
        frame = render(board, True)
        tracker.observe(frame)
        self.assertEqual(move, tracker.observe(frame))

    def test_last_move_highlights_do_not_hide_next_move(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        for san in ("e4", "e5", "Nf3"):
            move = board.parse_san(san)
            board.push(move)
            frame = render(board, highlights=(move.from_square, move.to_square))
            tracker.observe(frame)
            self.assertEqual(move, tracker.observe(frame))

    def test_capture_and_queen_promotion(self) -> None:
        board = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        move = board.parse_san("a8=Q+")
        board.push(move)
        frame = render(board)
        tracker.observe(frame)
        self.assertEqual(move, tracker.observe(frame))

    def test_en_passant(self) -> None:
        board = chess.Board()
        for san in ("e4", "a6", "e5", "d5"):
            board.push_san(san)
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        move = board.parse_san("exd6")
        board.push(move)
        frame = render(board)
        tracker.observe(frame)
        self.assertEqual(move, tracker.observe(frame))


if __name__ == "__main__":
    unittest.main()
