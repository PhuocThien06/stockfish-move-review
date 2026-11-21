"""Recover a live board without silently inventing skipped PGN moves."""

import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.analysis_patcher = patch.object(self.app, "_request_analysis")
        self.analysis_patcher.start()
        self.old_pgn = review.GAMES_DIR / "existing.pgn"
        self.old_pgn.write_text("previous segment\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.app._close()
        self.analysis_patcher.stop()
        review.GAMES_DIR = self.old_games_dir
        self.temp.cleanup()

    def _setup_capture(self, board: chess.Board) -> None:
        self.app.moves = []
        self.app.live_moves = self.app.moves
        self.app.live_positions = [board.copy(stack=True)]
        self.app.positions = self.app.live_positions
        self.app.live_branch_active = False
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
        with patch.object(review, "align_board", side_effect=AssertionError(
                "An unchanged board region should not need a new grid search")):
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
        for index in range(review.LIVE_RECOVERY_STABLE_FRAMES):
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

    def test_can_try_moves_and_go_back_while_live_capture_continues(self) -> None:
        self._setup_capture(chess.Board())
        self.app._play_move(self.app.positions[-1].parse_san("d4"))
        branch_path = self.app.manual_save_path
        self.assertTrue(self.app.live_branch_active)
        self.assertEqual("d4", chess.Board().san(self.app.moves[0]))

        self.app._apply_live_move(self.app.live_positions[-1].parse_san("e4"))
        self.assertEqual(1, len(self.app.live_moves))
        self.assertEqual("d4", chess.Board().san(self.app.moves[0]))
        self.app._play_move(self.app.positions[-1].parse_san("d5"))
        self.app._go_to(1)
        self.assertEqual(1, self.app.ply)
        self.app._go_to(2)
        self.assertEqual(2, self.app.ply)
        self.assertTrue(branch_path.is_file())
        self.assertIn("d4 d5", branch_path.read_text(encoding="utf-8"))

        self.app._return_to_live()
        self.assertFalse(self.app.live_branch_active)
        self.assertEqual("e4", chess.Board().san(self.app.moves[0]))
        self.assertEqual(1, self.app.ply)
        self.assertEqual(self.old_pgn, self.app.current_game_path)

    def test_recovery_keeps_open_trial_branch_separate(self) -> None:
        self._setup_capture(chess.Board())
        self.app._play_move(self.app.positions[-1].parse_san("d4"))
        branch_path = self.app.manual_save_path
        source_board = chess.Board()
        for san in ("e4", "e5", "Nf3"):
            last = source_board.push_san(san)

        self.app._recover_live_position(self._screenshot(source_board, last))
        self.assertTrue(self.app.live_branch_active)
        self.assertEqual("d4", chess.Board().san(self.app.moves[0]))
        self.assertEqual(branch_path, self.app.current_game_path)
        self.assertEqual(source_board.board_fen(),
                         self.app.live_positions[-1].board_fen())
        self.app._return_to_live()
        self.assertEqual(source_board.board_fen(),
                         self.app.positions[-1].board_fen())

    def test_can_step_back_without_live_moves_forcing_the_view_forward(self) -> None:
        self._setup_capture(chess.Board())
        self.app._apply_live_move(self.app.live_positions[-1].parse_san("e4"))
        self.app._go_to(0)
        self.app._apply_live_move(self.app.live_positions[-1].parse_san("e5"))
        self.assertEqual(0, self.app.ply)
        self.assertEqual(2, len(self.app.moves))
        self.app._play_move(self.app.positions[self.app.ply].parse_san("d4"))
        self.assertTrue(self.app.live_branch_active)
        self.assertEqual("d4", chess.Board().san(self.app.moves[0]))
        self.assertEqual(2, len(self.app.live_moves))


if __name__ == "__main__":
    unittest.main()
