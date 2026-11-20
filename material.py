"""Captured pieces and material balance for a selected chess position."""

from __future__ import annotations

from collections import Counter

import chess


PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}
DISPLAY_ORDER = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def material_snapshot(initial: chess.Board, moves: list[chess.Move], ply: int) -> dict:
    """Replay through ply so captured icons also follow review navigation/branches."""
    board = initial.copy(stack=False)
    captured = {chess.WHITE: Counter(), chess.BLACK: Counter()}
    for move in moves[:ply]:
        if board.is_en_passant(move):
            captured[board.turn][chess.PAWN] += 1
        elif board.is_capture(move):
            victim = board.piece_at(move.to_square)
            if victim is not None and victim.piece_type in PIECE_VALUES:
                captured[board.turn][victim.piece_type] += 1
        board.push(move)
    points = {
        color: sum(PIECE_VALUES.get(piece.piece_type, 0)
                   for piece in board.piece_map().values() if piece.color == color)
        for color in (chess.WHITE, chess.BLACK)
    }
    return {
        "captured": captured,
        "points": points,
        "balance": points[chess.WHITE] - points[chess.BLACK],
    }
