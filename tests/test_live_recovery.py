"""Recover a live board without silently inventing skipped PGN moves."""

import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import chess
from PIL import Image

import stockfish_review as review
from live_capture import LiveBoardTracker
from tests.test_live_capture import render


@unittest.skipUnless(sys.platform == "win32", "Tk live capture is a Windows feature")
class LiveRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[1] / "work"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.old_games_dir = review.GAMES_DIR
        review.GAMES_DIR = Path(self.temp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = review.ChessReviewApp(self.root)
        self.app.user_acted = True
        self.old_pgn = review.GAMES_DIR / "existing.pgn"
        self.old_pgn.write_text("previous segment\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.app._close()
        review.GAMES_DIR = self.old_games_dir
        self.temp.cleanup()

    def _setup_capture(self, board: chess.Board) -> None:
        self.app.positions = [board.copy(stack=True)]
        self.app.moves = []
        self.app.ply = 0
        self.app.live_tracker = LiveBoardTracker(board.copy(stack=True), False)
        self.app.live_tracker.observe(render(board))
        self.app.live_region = (80, 80, 592, 592)
        self.app.live_selection_region = self.app.live_region
        self.app.live_game_path = self.old_pgn

    @staticmethod
    def _screenshot(board: chess.Board, last: chess.Move) -> Image.Image:
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(board, highlights=(last.from_square, last.to_square)), (80, 80))
        return source

    def test_recovers_single_missed_move_in_existing_pgn(self) -> None:
        board = chess.Board("rnbqk2r/ppp2ppp/3b1n2/3p4/8/1P3N2/"
                            "PBPP1PPP/RN1QKB1R w KQkq - 0 1")
        self._setup_capture(board)
        move = board.push_san("h3")
        self.app._recover_live_position(self._screenshot(board, move))
        self.assertEqual([move], self.app.moves)
        self.assertEqual(self.old_pgn, self.app.live_game_path)
        self.assertEqual(board.board_fen(), self.app.positions[-1].board_fen())

    def test_resumes_from_visible_position_when_three_moves_were_missed(self) -> None:
        board = chess.Board()
        self._setup_capture(board)
        for san in ("e4", "e5", "Nf3"):
            last = board.push_san(san)
        source = self._screenshot(board, last)
        frame = render(board, highlights=(last.from_square, last.to_square))
        for index in range(50):
            self.app.live_tracker.observe(frame, now=index * .1)

        class FakeStream:
            closed = False

            def drain(self, _limit: int) -> list[Image.Image]:
                return [source]

            def close(self) -> None:
                self.closed = True

        self.app.live_stream = FakeStream()
        self.app.live_window = 1
        self.app._capture_live_tick()
        self.assertIsNotNone(self.app.live_tracker)
        self.assertFalse(self.app.live_stream.closed)
        self.assertEqual([], self.app.moves)
        self.assertEqual(board.board_fen(), self.app.positions[-1].board_fen())
        self.assertNotEqual(self.old_pgn, self.app.live_game_path)
        self.assertEqual("previous segment\n", self.old_pgn.read_text(encoding="utf-8"))
        self.assertTrue(self.app.live_game_path.is_file())


if __name__ == "__main__":
    unittest.main()
