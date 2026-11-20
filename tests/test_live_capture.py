"""Synthetic Neo-board frames exercise move recognition without screen access."""

from pathlib import Path
import unittest

import chess
from PIL import Image, ImageDraw

from live_capture import LiveBoardTracker, recognize_board


PIECES = Path(__file__).resolve().parents[1] / "pieces"


def render(board: chess.Board, flipped: bool = False,
           highlights: tuple[int, ...] = (),
           light: str = "#f0d9b5", dark: str = "#b58863") -> Image.Image:
    image = Image.new("RGB", (512, 512))
    draw = ImageDraw.Draw(image)
    for row in range(8):
        for col in range(8):
            file_ = 7 - col if flipped else col
            rank = row if flipped else 7 - row
            square = chess.square(file_, rank)
            color = light if (file_ + rank) % 2 else dark
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
        self.assertEqual([], tracker.observe(render(board)))
        for san in ("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O"):
            move = board.parse_san(san)
            board.push(move)
            frame = render(board)
            self.assertEqual([move], tracker.observe(frame), san)
        self.assertEqual(board.fen(), tracker.board.fen())

    def test_tracks_flipped_board(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), True)
        tracker.observe(render(board, True))
        move = board.parse_san("d4")
        board.push(move)
        frame = render(board, True)
        self.assertEqual([move], tracker.observe(frame))

    def test_last_move_highlights_do_not_hide_next_move(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        for san in ("e4", "e5", "Nf3"):
            move = board.parse_san(san)
            board.push(move)
            frame = render(board, highlights=(move.from_square, move.to_square))
            self.assertEqual([move], tracker.observe(frame))

    def test_capture_and_queen_promotion(self) -> None:
        board = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        move = board.parse_san("a8=Q+")
        board.push(move)
        frame = render(board)
        self.assertEqual([move], tracker.observe(frame))

    def test_en_passant(self) -> None:
        board = chess.Board()
        for san in ("e4", "a6", "e5", "d5"):
            board.push_san(san)
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        move = board.parse_san("exd6")
        board.push(move)
        frame = render(board)
        self.assertEqual([move], tracker.observe(frame))

    def test_starts_from_midgame_position(self) -> None:
        board = chess.Board()
        for san in ("e4", "e5", "Nf3"):
            board.push_san(san)
        found = recognize_board(render(board), False, board.turn)
        self.assertEqual(board.board_fen(), found.board_fen())
        self.assertEqual(board.turn, found.turn)
        tracker = LiveBoardTracker(found, False)
        tracker.observe(render(board))
        move = board.parse_san("Nc6")
        board.push(move)
        self.assertEqual([move], tracker.observe(render(board)))

    def test_reads_flipped_midgame_with_highlights(self) -> None:
        board = chess.Board()
        for san in ("d4", "d5", "c4"):
            board.push_san(san)
        move = board.peek()
        found = recognize_board(render(board, True,
                                      highlights=(move.from_square, move.to_square)),
                                True, board.turn)
        self.assertEqual(board.board_fen(), found.board_fen())

    def test_recovers_two_moves_between_frames(self) -> None:
        initial = chess.Board()
        tracker = LiveBoardTracker(initial.copy(), False)
        tracker.observe(render(initial))
        first = initial.parse_san("e4")
        initial.push(first)
        second = initial.parse_san("e5")
        initial.push(second)
        self.assertEqual([first, second], tracker.observe(render(initial)))
        self.assertEqual(initial.fen(), tracker.board.fen())

    def test_reads_bright_board_without_changing_system_hdr(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(), False)
        tracker.observe(render(board, light="#ffffff", dark="#ffdda3"))
        board.push_san("e4")
        board.push_san("e5")
        found = recognize_board(render(board, light="#ffffff", dark="#ffdda3"),
                                False, board.turn)
        self.assertEqual(board.board_fen(), found.board_fen())
        self.assertEqual(list(board.move_stack),
                         tracker.observe(render(board, light="#ffffff", dark="#ffdda3")))


if __name__ == "__main__":
    unittest.main()
