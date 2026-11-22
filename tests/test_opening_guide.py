import unittest

import chess

from opening_guide import get_opening_guide, opening_explanation


def play(*sans):
    board = chess.Board()
    positions = [board.copy(stack=True)]
    for san in sans:
        board.push_san(san)
        positions.append(board.copy(stack=True))
    return positions


class OpeningGuideTests(unittest.TestCase):
    def test_identifies_italian_game_and_legal_book_moves(self):
        positions = play("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5")
        guide = get_opening_guide()
        self.assertIn("Italian Game", guide.name(positions)[1])
        moves = {positions[-1].san(move) for move, _ in guide.continuations(positions[-1], 20)}
        self.assertTrue({"c3", "d3"}.issubset(moves))

    def test_master_counts_rank_common_continuations_above_catalog_coverage(self):
        positions = play("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5")
        master_data = {
            "opening": {"eco": "C50", "name": "Italian Game: Giuoco Piano"},
            "moves": [
                {"san": "c3", "white": 3900, "draws": 8000, "black": 3000},
                {"san": "d3", "white": 1200, "draws": 2000, "black": 1000},
                {"san": "b4", "white": 500, "draws": 600, "black": 400},
            ],
        }
        explanation = opening_explanation(positions, chess.WHITE, master_data=master_data)
        self.assertLess(explanation.index("• c3"), explanation.index("• b4"))
        self.assertIn("Đối phương vừa đi Bc5", explanation)
        self.assertIn("14,900 ván cao thủ", explanation)

    def test_does_not_recommend_a_side_when_turn_is_unknown(self):
        positions = play("e4", "e5")
        explanation = opening_explanation(positions, chess.WHITE, turn_known=False)
        self.assertIn("chưa xác định được bên tới lượt", explanation)
        self.assertNotIn("• ", explanation)

    def test_does_not_invent_an_opening_from_unrecognized_midgame_position(self):
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 40")
        self.assertEqual("", opening_explanation([board], chess.WHITE))


if __name__ == "__main__":
    unittest.main()
