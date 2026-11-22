"""Navigation stays responsive while Stockfish works in the background."""

import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from stockfish_review import ChessReviewApp
from local_store import load_last_username


@unittest.skipUnless(sys.platform == "win32", "The desktop UI is tested on Windows")
class UiResponsivenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ChessReviewApp(self.root)
        self.app.user_acted = True
        board = chess.Board()
        self.app.positions = [board.copy(stack=True)]
        self.app.moves = []
        for san in ("e4", "e5", "Nf3"):
            self.app.moves.append(board.push_san(san))
            self.app.positions.append(board.copy(stack=True))
        self.app._fill_moves()

    def tearDown(self) -> None:
        self.app._close()

    def test_rapid_navigation_analyses_only_the_last_position(self) -> None:
        with patch.object(self.app, "_request_analysis") as request:
            self.app._go_to(1)
            self.app._go_to(2)
            self.app._go_to(3)
            self.assertEqual(3, self.app.ply)
            self.assertEqual(0, request.call_count)
            self.root.after(140, self.root.quit)
            self.root.mainloop()
            self.assertEqual(1, request.call_count)

    def test_updating_a_grade_preserves_other_rows_and_selection(self) -> None:
        self.app.move_list.selection_set(1)
        first = self.app.move_list.get(0)
        self.app.analysis_cache[(2, False)] = {"category": "best"}
        self.app._update_move_row(1)
        self.assertEqual(first, self.app.move_list.get(0))
        self.assertIn("Best Move", self.app.move_list.get(1))
        self.assertEqual((1,), self.app.move_list.curselection())

    def test_search_name_is_saved_before_a_failed_network_sync(self) -> None:
        scratch = Path(__file__).resolve().parents[1] / "work"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            games = Path(temporary) / "games"
            self.app.username_var.set("EnergeticCyborg")
            with patch("stockfish_review.GAMES_DIR", games), patch(
                "stockfish_review.sync_recent_games", side_effect=ValueError("offline")
            ):
                self.app._sync_games()
                with self.assertRaises(ValueError):
                    self.app.sync_future.result()
                self.assertEqual("EnergeticCyborg", load_last_username(games))


if __name__ == "__main__":
    unittest.main()
