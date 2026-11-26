"""Recover a live board without silently inventing skipped PGN moves."""

import sys
import tempfile
import time
import tkinter as tk
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine
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
        self.app.live_flipped = False
        self.app.live_turn_uncertain = False
        self.app.ply = 0
        self.app.live_tracker = LiveBoardTracker(board.copy(stack=True), False)
        self.app.live_tracker.observe(render(board))
        self.app.live_region = (80, 80, 592, 592)
        self.app.live_selection_region = self.app.live_region
        self.app.live_game_path = self.old_pgn

    def _complete_capture_tick(self) -> None:
        task = self.app.live_processing
        self.assertIsNotNone(task)
        task.result(timeout=5)
        if self.app.live_job is not None:
            self.root.after_cancel(self.app.live_job)
            self.app.live_job = None
        self.app._capture_live_tick()

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
        self._complete_capture_tick()
        self.assertIsNotNone(self.app.live_tracker)
        self.assertFalse(self.app.live_stream.closed)
        self.assertEqual([], self.app.moves)
        self.assertEqual(board.board_fen(), self.app.positions[-1].board_fen())
        self.assertNotEqual(self.old_pgn, self.app.live_game_path)
        self.assertEqual("previous segment\n", self.old_pgn.read_text(encoding="utf-8"))
        self.assertFalse(self.app.live_game_path.is_file())
        self.app._apply_live_move(self.app.live_positions[-1].parse_san("Nc6"))
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

    def test_new_game_switches_to_black_and_clears_previous_evaluation(self) -> None:
        self._setup_capture(chess.Board())
        for san in ("e4", "e5"):
            self.app._apply_live_move(self.app.live_positions[-1].parse_san(san))
        old_path = self.app.live_game_path
        self.app.score_cache[2] = (chess.engine.Cp(450), 0.85)
        self.app.bar_last_score = chess.engine.Cp(450)
        self.app.bar_display_share = self.app.bar_target_share = 0.85
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(chess.Board(), True), (80, 80))

        self.app._recover_live_position(source)
        self.assertTrue(self.app.flipped, self.app.live_status_var.get())
        self.assertTrue(self.app.live_tracker.flipped)
        self.assertEqual(chess.STARTING_BOARD_FEN,
                         self.app.positions[-1].board_fen())
        self.assertEqual([], self.app.moves)
        self.assertEqual({}, self.app.score_cache)
        self.assertIsNone(self.app.bar_last_score)
        self.assertEqual(0.5, self.app.bar_target_share)
        self.assertEqual("0.00", self.app.eval_var.get())
        self.assertNotEqual(old_path, self.app.live_game_path)
        self.assertTrue(old_path.is_file())
        self.app._draw_bar(chess.engine.Cp(-100), 0.4)
        self.assertEqual("+1.00", self.app.eval_var.get())
        self.assertAlmostEqual(0.6, self.app.bar_target_share)

    def test_new_game_on_same_side_also_clears_previous_evaluation(self) -> None:
        self._setup_capture(chess.Board())
        self.app._apply_live_move(self.app.live_positions[-1].parse_san("e4"))
        self.app.bar_last_score = chess.engine.Cp(-600)
        self.app.bar_display_share = self.app.bar_target_share = 0.1
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(chess.Board()), (80, 80))

        self.app._recover_live_position(source)
        self.assertFalse(self.app.flipped)
        self.assertEqual(chess.STARTING_BOARD_FEN,
                         self.app.positions[-1].board_fen())
        self.assertIsNone(self.app.bar_last_score)
        self.assertEqual(0.5, self.app.bar_target_share)

    def test_detects_next_game_after_its_first_move_with_opposite_color(self) -> None:
        self._setup_capture(chess.Board())
        for san in ("e4", "e5", "Nf3"):
            self.app._apply_live_move(self.app.live_positions[-1].parse_san(san))
        next_game = chess.Board()
        last = next_game.push_san("d4")
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(next_game, True,
                            highlights=(last.from_square, last.to_square)), (80, 80))

        self.app._recover_live_position(source)
        self.assertTrue(self.app.flipped, self.app.live_status_var.get())
        self.assertTrue(self.app.live_tracker.flipped)
        self.assertEqual(next_game.board_fen(),
                         self.app.positions[-1].board_fen())
        self.assertFalse(self.app.positions[-1].turn)
        self.assertIsNone(self.app.bar_last_score)

    def test_checkmate_keeps_window_capture_ready_for_next_game(self) -> None:
        board = chess.Board()
        for san in ("f3", "e5", "g4"):
            board.push_san(san)
        self._setup_capture(board)
        self.app._apply_live_move(board.parse_san("Qh4#"))
        self.assertIsNotNone(self.app.live_tracker)
        self.assertTrue(self.app.live_positions[-1].is_checkmate())
        self.assertTrue(self.app.live_game_path.is_file())

        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(chess.Board(), True), (80, 80))
        frame = render(chess.Board(), True)
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
        self._complete_capture_tick()
        self.assertTrue(self.app.flipped)
        self.assertEqual(chess.STARTING_BOARD_FEN,
                         self.app.live_positions[-1].board_fen())

    def test_live_color_change_does_not_flip_an_open_trial_branch(self) -> None:
        self._setup_capture(chess.Board())
        self.app._play_move(self.app.positions[-1].parse_san("d4"))
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(chess.Board(), True), (80, 80))
        self.app._recover_live_position(source)
        self.assertFalse(self.app.flipped)
        self.assertTrue(self.app.live_flipped)
        self.app._return_to_live()
        self.assertTrue(self.app.flipped)

    def test_recreates_clear_board_even_when_turn_is_not_visible(self) -> None:
        self._setup_capture(chess.Board())
        shown = chess.Board()
        for san in ("e4", "e5", "Nf3"):
            last = shown.push_san(san)
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(shown), (80, 80))

        self.app._recover_live_position(source)
        self.assertEqual(shown.board_fen(), self.app.positions[-1].board_fen())
        self.assertTrue(self.app.live_turn_uncertain)
        self.assertEqual([], self.app.moves)
        self.assertFalse(self.app.live_game_path.is_file())
        self.assertEqual("Chưa rõ lượt đi", self.app.grade_var.get())

        confirmed = Image.new("RGB", (700, 700), "#14223b")
        confirmed.paste(render(shown,
                               highlights=(last.from_square, last.to_square)), (80, 80))

        class FakeStream:
            closed = False

            def drain(self, _limit: int) -> list[Image.Image]:
                return [confirmed]

            def close(self) -> None:
                self.closed = True

        self.app.live_stream = FakeStream()
        self.app.live_window = 1
        self.app.live_recovery_after = 0
        self.app._capture_live_tick()
        self._complete_capture_tick()
        self.assertFalse(self.app.live_turn_uncertain)
        self.assertEqual(shown.turn, self.app.positions[-1].turn)
        self.assertEqual(shown.board_fen(), self.app.positions[-1].board_fen())

    def test_save_error_does_not_stop_board_following(self) -> None:
        self._setup_capture(chess.Board())
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            self.app._apply_live_move(self.app.live_positions[-1].parse_san("e4"))
        self.assertIsNotNone(self.app.live_tracker)
        self.assertEqual("e4", chess.Board().san(self.app.live_moves[-1]))
        self.assertEqual(self.app.live_positions[-1].board_fen(),
                         self.app.positions[-1].board_fen())
        self.assertIn("Không lưu được PGN", self.app.live_status_var.get())

    def test_slow_recovery_keeps_tk_event_loop_responsive(self) -> None:
        self._setup_capture(chess.Board())
        self.app.live_tracker.unmatched_frames = review.LIVE_RECOVERY_STABLE_FRAMES
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(render(chess.Board()), (80, 80))

        class FakeStream:
            closed = False

            def drain(self, _limit: int) -> list[Image.Image]:
                return [source]

            def close(self) -> None:
                self.closed = True

        self.app.live_stream = FakeStream()
        self.app.live_window = 1

        def slow_read(*_args):
            time.sleep(0.25)
            return None, []

        with patch.object(review, "_read_live_recovery", side_effect=slow_read):
            self.app._capture_live_tick()
            started = time.perf_counter()
            self.root.after(20, self.root.quit)
            self.root.mainloop()
            self.assertLess(time.perf_counter() - started, 0.15)
            self._complete_capture_tick()

    def test_background_move_result_updates_live_board(self) -> None:
        board = chess.Board()
        self._setup_capture(board)
        move = board.parse_san("e4")

        class FakeStream:
            closed = False

            def drain(self, _limit: int) -> list[Image.Image]:
                return []

            def close(self) -> None:
                self.closed = True

        self.app.live_stream = FakeStream()
        self.app.live_window = 1
        completed = Future()
        completed.set_result([move])
        self.app.live_processing = completed
        self.app.live_processing_kind = "observe"
        self.app.live_processing_tracker = self.app.live_tracker
        self.app.live_processing_source = render(board)
        self.app._capture_live_tick()

        self.assertEqual([move], self.app.live_moves)
        self.assertEqual("e4", board.san(move))
        self.assertEqual(1, self.app.ply)


if __name__ == "__main__":
    unittest.main()
