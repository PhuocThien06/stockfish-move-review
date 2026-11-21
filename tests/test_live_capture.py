"""Synthetic Neo-board frames exercise move recognition without screen access."""

from pathlib import Path
import unittest

import chess
from PIL import Image, ImageDraw

from live_capture import (LiveBoardTracker, _highlighted_squares, align_board,
                          infer_turn, recognize_board)


PIECES = Path(__file__).resolve().parents[1] / "pieces"


def confirm(tracker: LiveBoardTracker, frame: Image.Image) -> list[chess.Move]:
    """A position is recorded only after the same frame has settled."""
    assert tracker.observe(frame, now=0) == []
    return tracker.observe(frame, now=1)


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


def annotate(image: Image.Image, red: tuple[int, ...] = (),
             arrows: tuple[tuple[int, int], ...] = ()) -> Image.Image:
    """Approximate the translucent red squares and gold arrows on Chess.com."""
    result = image.convert("RGBA")
    overlay = Image.new("RGBA", result.size)
    draw = ImageDraw.Draw(overlay)
    for square in red:
        x = chess.square_file(square) * 64
        y = (7 - chess.square_rank(square)) * 64
        draw.rectangle((x, y, x + 63, y + 63), fill=(235, 55, 45, 135))
    for start, end in arrows:
        x1, y1 = chess.square_file(start) * 64 + 32, (7 - chess.square_rank(start)) * 64 + 32
        x2, y2 = chess.square_file(end) * 64 + 32, (7 - chess.square_rank(end)) * 64 + 32
        draw.line((x1, y1, x2, y2), fill=(245, 170, 25, 220), width=14)
    return Image.alpha_composite(result, overlay).convert("RGB")


class LiveCaptureTests(unittest.TestCase):
    def test_right_click_annotations_do_not_record_moves_or_stop_tracking(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(), False)
        tracker.observe(render(board))
        frame = annotate(render(board), red=(chess.E4, chess.E5),
                         arrows=((chess.G1, chess.F3), (chess.D2, chess.D4)))
        for index in range(60):
            self.assertEqual([], tracker.observe(frame, now=index * .1))
        self.assertEqual(0, tracker.unmatched_frames)
        self.assertEqual(board.fen(), tracker.board.fen())
        self.assertIsNone(_highlighted_squares(frame, False))
        move = board.push_san("e4")
        clean = render(board, highlights=(move.from_square, move.to_square))
        self.assertEqual([move], confirm(tracker, clean))

    def test_red_markers_do_not_override_last_move_highlights(self) -> None:
        board = chess.Board()
        move = board.push_san("e4")
        frame = annotate(render(board, highlights=(move.from_square, move.to_square)),
                         red=(chess.B3, chess.C4))
        self.assertEqual({move.from_square, move.to_square},
                         _highlighted_squares(frame, False))
        self.assertEqual(chess.BLACK, infer_turn(frame, board, False))

    def test_marks_on_move_squares_are_not_a_fake_move(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(), False)
        tracker.observe(render(board))
        marked = annotate(render(board), red=(chess.E2, chess.E4),
                          arrows=((chess.E2, chess.E4),))
        for index in range(8):
            self.assertEqual([], tracker.observe(marked, now=index * .2))
        self.assertEqual(board.fen(), tracker.board.fen())
        move = board.push_san("e4")
        self.assertEqual([move], tracker.observe(render(board), now=2.0)
                         + tracker.observe(render(board), now=2.6))

    def test_move_with_persistent_annotations_still_records(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(), False)
        before = annotate(render(board), red=(chess.B3,),
                          arrows=((chess.G1, chess.F3),))
        tracker.observe(before)
        move = board.push_san("e4")
        after = annotate(render(board), red=(chess.B3,),
                         arrows=((chess.G1, chess.F3),))
        self.assertEqual([move], confirm(tracker, after))

    def test_move_under_persistent_red_square_and_arrow_still_records(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(), False)
        arrows = ((chess.E2, chess.E4), (chess.G1, chess.F3))
        before = annotate(render(board), red=(chess.E2, chess.E4), arrows=arrows)
        tracker.observe(before)
        move = board.push_san("e4")
        after = annotate(render(board), red=(chess.E2, chess.E4), arrows=arrows)
        self.assertEqual([move], confirm(tracker, after))

    def test_tracks_both_sides_and_castling(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        self.assertEqual([], tracker.observe(render(board)))
        for san in ("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O"):
            move = board.parse_san(san)
            board.push(move)
            frame = render(board)
            self.assertEqual([move], confirm(tracker, frame), san)
        self.assertEqual(board.fen(), tracker.board.fen())

    def test_tracks_flipped_board(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), True)
        tracker.observe(render(board, True))
        move = board.parse_san("d4")
        board.push(move)
        frame = render(board, True)
        self.assertEqual([move], confirm(tracker, frame))

    def test_last_move_highlights_do_not_hide_next_move(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        for san in ("e4", "e5", "Nf3"):
            move = board.parse_san(san)
            board.push(move)
            frame = render(board, highlights=(move.from_square, move.to_square))
            self.assertEqual([move], confirm(tracker, frame))

    def test_capture_and_queen_promotion(self) -> None:
        board = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        move = board.parse_san("a8=Q+")
        board.push(move)
        frame = render(board)
        self.assertEqual([move], confirm(tracker, frame))

    def test_en_passant(self) -> None:
        board = chess.Board()
        for san in ("e4", "a6", "e5", "d5"):
            board.push_san(san)
        tracker = LiveBoardTracker(board.copy(stack=True), False)
        tracker.observe(render(board))
        move = board.parse_san("exd6")
        board.push(move)
        frame = render(board)
        self.assertEqual([move], confirm(tracker, frame))

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
        self.assertEqual([move], confirm(tracker, render(board)))

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
        self.assertEqual([first, second], confirm(tracker, render(initial)))
        self.assertEqual(initial.fen(), tracker.board.fen())

    def test_two_fast_replay_clicks_skip_transient_animation(self) -> None:
        initial = chess.Board()
        tracker = LiveBoardTracker(initial.copy(), False)
        tracker.observe(render(initial))
        transient = initial.copy()
        transient.push_san("e3")
        self.assertEqual([], tracker.observe(render(transient), now=0))
        first = initial.push_san("e4")
        second = initial.push_san("e5")
        final = render(initial, highlights=(second.from_square, second.to_square))
        self.assertEqual([], tracker.observe(final, now=.08))
        self.assertEqual([first, second], tracker.observe(final, now=.4))

    def test_two_fast_replay_clicks_with_right_click_marks(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(), False)
        marks = dict(red=(chess.B3,), arrows=((chess.B1, chess.C3),))
        tracker.observe(annotate(render(board), **marks))
        first = board.push_san("e4")
        second = board.push_san("e5")
        final = annotate(render(board, highlights=(second.from_square,
                                                   second.to_square)), **marks)
        self.assertEqual([], tracker.observe(final, now=0))
        self.assertEqual([first, second], tracker.observe(final, now=.4))

    def test_unmatched_counter_counts_stable_frames_only(self) -> None:
        board = chess.Board()
        tracker = LiveBoardTracker(board.copy(), False)
        tracker.observe(render(board))
        for san in ("e4", "e5", "Nf3"):
            board.push_san(san)
        first = render(board)
        tracker.observe(first, now=0)
        self.assertEqual(1, tracker.unmatched_frames)
        tracker.observe(first, now=.1)
        self.assertEqual(2, tracker.unmatched_frames)
        board.push_san("Nc6")
        tracker.observe(render(board), now=.2)
        self.assertEqual(1, tracker.unmatched_frames)

    def test_queued_premove_is_recorded_only_after_opponent_moves(self) -> None:
        board = chess.Board()
        previous = board.push_san("e4")
        tracker = LiveBoardTracker(board.copy(), False)
        tracker.observe(render(board, highlights=(previous.from_square, previous.to_square)))
        queued = annotate(render(board, highlights=(previous.from_square,
                                                   previous.to_square)),
                          red=(chess.G1, chess.F3))
        for index in range(8):
            self.assertEqual([], tracker.observe(queued, now=index * .1))
        self.assertEqual(board.board_fen(), tracker.board.board_fen())
        opponent = board.push_san("e5")
        premove = board.push_san("Nf3")
        final = render(board, highlights=(premove.from_square, premove.to_square))
        self.assertEqual([], tracker.observe(final, now=1.0))
        self.assertEqual([opponent, premove], tracker.observe(final, now=1.4))

    def test_can_start_capture_while_premove_is_queued(self) -> None:
        board = chess.Board()
        last = board.push_san("e4")
        queued = annotate(render(board, highlights=(last.from_square,
                                                    last.to_square)),
                          red=(chess.G1, chess.F3))
        recognized = recognize_board(queued, False, chess.BLACK)
        self.assertEqual(board.board_fen(), recognized.board_fen())
        _, aligned, _ = align_board(queued, (0, 0, 512, 512), False, chess.BLACK)
        self.assertEqual(board.board_fen(), aligned.board_fen())
        self.assertEqual(chess.BLACK, infer_turn(queued, aligned, False))

    def test_cancelled_premove_does_not_change_position(self) -> None:
        board = chess.Board()
        previous = board.push_san("e4")
        tracker = LiveBoardTracker(board.copy(), False)
        plain = render(board, highlights=(previous.from_square, previous.to_square))
        tracker.observe(plain)
        queued = annotate(plain, red=(chess.G1, chess.F3))
        self.assertEqual([], tracker.observe(queued, now=0))
        self.assertEqual([], tracker.observe(plain, now=.5))
        opponent = board.push_san("e5")
        final = render(board, highlights=(opponent.from_square, opponent.to_square))
        self.assertEqual([], tracker.observe(final, now=.6))
        self.assertEqual([opponent], tracker.observe(final, now=1.0))

    def test_next_queued_premove_does_not_hide_two_completed_moves(self) -> None:
        board = chess.Board()
        board.push_san("e4")
        tracker = LiveBoardTracker(board.copy(), False)
        tracker.observe(render(board))
        opponent = board.push_san("e5")
        executed = board.push_san("Nf3")
        # A new Bc4 premove is queued while Black thinks. Its red source
        # square obscures a bishop; the completed e5 and Nf3 must still count.
        final = annotate(render(board), red=(chess.F1, chess.C4))
        self.assertEqual([], tracker.observe(final, now=0))
        self.assertEqual([opponent, executed], tracker.observe(final, now=.6))

    def test_obscured_premove_is_not_invented_from_opponent_move(self) -> None:
        board = chess.Board()
        board.push_san("e4")
        tracker = LiveBoardTracker(board.copy(), False)
        tracker.observe(render(board))
        opponent = board.push_san("e5")
        queued = annotate(render(board), red=(chess.G1, chess.F3))
        self.assertEqual([], tracker.observe(queued, now=0))
        self.assertEqual([opponent], tracker.observe(queued, now=.6))
        executed = board.push_san("Nf3")
        clear = render(board)
        self.assertEqual([], tracker.observe(clear, now=.7))
        self.assertEqual([executed], tracker.observe(clear, now=1.3))

    def test_does_not_record_pawn_on_intermediate_animation_square(self) -> None:
        initial = chess.Board()
        tracker = LiveBoardTracker(initial.copy(), False)
        tracker.observe(render(initial))
        intermediate = initial.copy()
        intermediate.push_san("e3")
        self.assertEqual([], tracker.observe(render(intermediate), now=0))
        final = initial.copy()
        move = final.push_san("e4")
        self.assertEqual([], tracker.observe(render(final), now=.08))
        self.assertEqual([move], tracker.observe(render(final), now=.6))
        self.assertEqual(final.fen(), tracker.board.fen())

    def test_last_move_highlight_rejects_intermediate_destination(self) -> None:
        initial = chess.Board()
        tracker = LiveBoardTracker(initial.copy(), False)
        tracker.observe(render(initial))
        intermediate = initial.copy()
        intermediate.push_san("e3")
        highlight = (chess.E2, chess.E4)
        self.assertEqual([], tracker.observe(render(intermediate, highlights=highlight), now=0))
        final = initial.copy()
        move = final.push_san("e4")
        frame = render(final, highlights=highlight)
        self.assertEqual([], tracker.observe(frame, now=.08))
        self.assertEqual([move], tracker.observe(frame, now=.5))

    def test_infers_turn_from_last_move_highlight(self) -> None:
        board = chess.Board()
        self.assertEqual(chess.WHITE, infer_turn(render(board), board, False))
        move = board.push_san("e4")
        self.assertEqual(chess.BLACK, infer_turn(
            render(board, highlights=(move.from_square, move.to_square)),
            board, False,
        ))
        self.assertIsNone(infer_turn(render(board), board, False))

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
                         confirm(tracker, render(board, light="#ffffff", dark="#ffdda3")))

    def test_aligns_selected_border_at_start_and_midgame(self) -> None:
        for opening in ((), ("e4",), ("e4", "e5", "Nf3")):
            board = chess.Board()
            for san in opening:
                board.push_san(san)
            framed = Image.new("RGB", (526, 526), "#deb230")
            framed.paste(render(board), (7, 7))
            box, found, _ = align_board(framed, (0, 0, 526, 526), False, board.turn)
            self.assertEqual(board.board_fen(), found.board_fen())
            self.assertTrue(4 <= box[0] <= 10)

    def test_aligns_small_flipped_midgame_with_arrow_and_uneven_border(self) -> None:
        board = chess.Board("r4rk1/1Q3pbp/4n1p1/4p3/4P3/2P5/PP3PPP/R4RK1 w - - 0 1")
        frame = annotate(render(board, True, light="#e0d1b9", dark="#c6936c"),
                         arrows=((chess.E5, chess.F4),))
        source = Image.new("RGB", (700, 700), "#14223b")
        source.paste(frame.resize((392, 392), Image.Resampling.BILINEAR), (149, 221))
        selected = (143, 219, 553, 620)
        aligned, found, _ = align_board(source, selected, True, chess.WHITE)
        self.assertEqual(board.board_fen(), found.board_fen())
        self.assertNotEqual(selected, aligned)

    def test_aligns_large_board_with_asymmetric_selection(self) -> None:
        board = chess.Board()
        source = Image.new("RGB", (1920, 1032), "#14223b")
        source.paste(render(board).resize((776, 776), Image.Resampling.BILINEAR),
                     (253, 187))
        selected = (234, 175, 1037, 972)
        aligned, found, _ = align_board(source, selected, False, chess.WHITE)
        self.assertEqual(board.board_fen(), found.board_fen())
        self.assertLessEqual(abs(aligned[0] - 253), 4)
        self.assertLessEqual(abs(aligned[1] - 187), 4)

    def test_alignment_does_not_invent_starting_pieces_on_empty_board(self) -> None:
        empty = render(chess.Board(None))
        with self.assertRaises(ValueError):
            align_board(empty, (0, 0, 512, 512), False, chess.WHITE)


if __name__ == "__main__":
    unittest.main()
