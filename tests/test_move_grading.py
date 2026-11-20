import unittest

import chess
import chess.engine

from analysis_core import classify_move, material_offer
from coach import explain_move


def info(pv, cp=0):
    return {"score": chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE),
            "pv": pv}


class SacrificeGradingTests(unittest.TestCase):
    def test_coach_names_rook_pressure_on_queen(self):
        board = chess.Board("r4q1k/1p4bp/p1n1Qpp1/5n2/3p4/P2P1N2/BPPB1PPP/R5K1 b - - 0 20")
        move = board.parse_san("Re8")
        after = board.copy()
        after.push(move)
        reply = after.parse_san("Qb3")
        best = board.parse_san("Ne5")
        assessment = {
            "category": "excellent", "ep_loss": 0.004,
            "best_ep": 0.172, "played_ep": 0.168,
            "best_pv": [best], "played_pv": [move, reply],
            "best_prior": "Ne5", "material_offer": None,
        }
        explanation = explain_move(board, move, assessment, "Tại sao Re8 xuất sắc?")
        self.assertIn("hậu đối phương ở e6", explanation)
        self.assertIn("Qb3", explanation)
        self.assertIn("17.2%", explanation)
        self.assertIn("16.8%", explanation)
        self.assertNotIn("Cách đọc biến thể", explanation)

    def test_queen_exchange_is_not_brilliant(self):
        # Real PGN position: 21.Qf7 Qxf7 22.Bxf7 trades queens.
        board = chess.Board("4rq1k/1p4bp/p1n1Qpp1/5n2/3p4/P2P1N2/BPPB1PPP/R5K1 w - - 1 21")
        move = board.parse_san("Qf7")
        reply_board = board.copy()
        reply_board.push(move)
        reply = reply_board.parse_san("Qxf7")
        reply_board.push(reply)
        followup = reply_board.parse_san("Bxf7")
        pv = [move, reply, followup]

        offer = material_offer(board, move, pv)
        self.assertIsNotNone(offer)
        self.assertEqual(offer["net_material_loss"], 0)
        best = board.parse_san("Qd7")
        assessment = classify_move(board, move, info([best]), info(pv), None)
        self.assertNotEqual(assessment["category"], "brilliant")
        explanation = explain_move(board, move, assessment, "Tại sao thí hậu này thiên tài?")
        self.assertIn("đổi hậu ngang giá", explanation)
        self.assertIn("Qxf7", explanation)
        self.assertIn("Bxf7", explanation)

    def test_real_sacrifice_explains_compensation(self):
        board = chess.Board("6k1/6pp/8/8/8/3B1N2/6PP/3Q2K1 w - - 0 1")
        move = board.parse_san("Bxh7+")
        reply_board = board.copy()
        reply_board.push(move)
        reply = reply_board.parse_san("Kxh7")
        reply_board.push(reply)
        followup = reply_board.parse_san("Ng5+")
        pv = [move, reply, followup]

        assessment = classify_move(board, move, info(pv), info(pv), None)
        self.assertEqual(assessment["category"], "brilliant")
        self.assertEqual(assessment["material_offer"]["net_material_loss"], 2)
        explanation = explain_move(board, move, assessment, "Vì sao đây là nước thiên tài?")
        self.assertIn("Kxh7", explanation)
        self.assertIn("Ng5+", explanation)
        self.assertIn("chiếu vua", explanation)
        self.assertIn("kém 2 điểm vật chất", explanation)


if __name__ == "__main__":
    unittest.main()
