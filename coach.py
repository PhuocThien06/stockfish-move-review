"""Evidence-first Vietnamese explanations of local Stockfish assessments."""

from __future__ import annotations

import chess

from analysis_core import LABELS, material_offer, variation_text


PIECE_NAMES = {
    chess.PAWN: "tốt", chess.KNIGHT: "mã", chess.BISHOP: "tượng",
    chess.ROOK: "xe", chess.QUEEN: "hậu", chess.KING: "vua",
}


def _observations(board: chess.Board, move: chess.Move) -> list[str]:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return []
    name = PIECE_NAMES[piece.piece_type]
    to = chess.square_name(move.to_square)
    facts = [f"Bạn đưa {name} tới {to}."]
    if board.is_capture(move):
        victim = board.piece_at(move.to_square)
        if victim is None and board.is_en_passant(move):
            facts.append("Đây là nước bắt tốt qua đường.")
        elif victim:
            facts.append(f"Bạn bắt {PIECE_NAMES[victim.piece_type]} của đối phương.")
    if board.is_castling(move):
        facts.append("Bạn nhập thành, đưa vua tới vị trí thường an toàn hơn và kích hoạt xe.")
    if move.promotion:
        facts.append(f"Tốt được phong cấp thành {PIECE_NAMES[move.promotion]}.")
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        facts.append("Nước này chiếu hết ngay lập tức.")
    elif after.is_check():
        facts.append("Nước này chiếu vua, buộc đối phương phải đáp trả đòn chiếu.")
    if piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) in (0, 7):
        facts.append("Quân nhẹ rời hàng xuất phát, góp phần phát triển lực lượng.")
    if piece.piece_type == chess.PAWN and chess.square_file(move.to_square) in (3, 4):
        facts.append("Tốt tiến vào hoặc tác động trực tiếp tới khu trung tâm.")
    if after.is_game_over() and not after.is_checkmate():
        facts.append(f"Vị trí sau nước đi kết thúc ván: {after.outcome().result() if after.outcome() else '?'}.")
    return facts


def _piece_pressure(board: chess.Board, move: chess.Move,
                    played_pv: list[chess.Move]) -> list[str]:
    """Name newly attacked pieces and show whether the next PV move moves one."""
    piece = board.piece_at(move.from_square)
    if piece is None:
        return []
    before_attacks = board.attacks(move.from_square)
    after = board.copy(stack=False)
    after.push(move)
    if after.piece_at(move.to_square) is None:
        return []
    targets = [
        (square, target) for square, target in after.piece_map().items()
        if target.color != piece.color and target.piece_type in (
            chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN
        ) and square in after.attacks(move.to_square) and square not in before_attacks
    ]
    targets.sort(key=lambda item: {chess.QUEEN: 9, chess.ROOK: 5,
                                   chess.BISHOP: 3, chess.KNIGHT: 3}[item[1].piece_type],
                 reverse=True)
    if not targets:
        return []
    square, target = targets[0]
    target_name = PIECE_NAMES[target.piece_type]
    details = [
        f"{PIECE_NAMES[piece.piece_type].capitalize()} trên {chess.square_name(move.to_square)} "
        f"vừa tạo sức ép trực tiếp lên {target_name} đối phương ở {chess.square_name(square)}."
    ]
    if len(played_pv) > 1 and played_pv[1] in after.legal_moves:
        reply = played_pv[1]
        if reply.from_square == square:
            details.append(
                f"Trong biến thể Stockfish, đối phương đáp {after.san(reply)}; "
                f"{target_name} rời ô {chess.square_name(square)}."
            )
    return details


def explain_move(board: chess.Board, move: chess.Move, assessment: dict, question: str = "") -> str:
    """Explain only verifiable board facts and engine lines; avoid invented plans."""
    san = board.san(move)
    label = LABELS[assessment["category"]][0]
    loss = assessment["ep_loss"]
    best_ep = assessment["best_ep"]
    played_ep = assessment["played_ep"]
    best_line = variation_text(board, assessment["best_pv"], 8)
    played_line = variation_text(board, assessment["played_pv"], 8)
    offer = assessment.get("material_offer") or material_offer(
        board, move, assessment["played_pv"]
    )
    possible_offer = assessment.get("available_material_offer")
    question_lower = question.strip().casefold()
    parts = [f"Bruno · {san} — {label}."]
    facts = _observations(board, move)
    if facts:
        parts.append("Trên bàn: " + " ".join(facts))
    parts.extend(_piece_pressure(board, move, assessment["played_pv"]))
    if assessment["category"] == "book":
        parts.append(f"{san} đưa ván cờ vào một vị trí có trong kho khai cuộc của ứng dụng.")
    elif assessment["category"] == "forced":
        parts.append(f"Trước {san}, bạn chỉ có một nước hợp lệ. Vì thế nhãn là Forced Move.")
    elif assessment["category"] == "brilliant":
        if offer and offer["net_material_loss"] >= 1:
            piece_name = PIECE_NAMES[offer["piece_type"]]
            parts.append(
                f"Đối phương có thể chơi {offer['reply_san']} để bắt {piece_name}. "
                f"Sau khi bạn đáp {offer['followup_san']}, bạn vẫn kém "
                f"{offer['net_material_loss']} điểm vật chất so với trước nước đi. "
                "Đây là thí quân thật, không phải đổi ngang giá."
            )
            if offer["followup_check"]:
                parts.append(
                    f"Điểm bù đắp thấy ngay trong biến thể: {offer['followup_san']} "
                    "chiếu vua, buộc đối phương xử lý đòn chiếu."
                )
            elif offer["followup_capture_type"]:
                captured = PIECE_NAMES[offer["followup_capture_type"]]
                parts.append(f"Điểm bù đắp thấy ngay: {offer['followup_san']} bắt {captured}.")
        elif possible_offer:
            piece_name = PIECE_NAMES[possible_offer["piece_type"]]
            parts.append(
                f"Đối phương có thể nhận {piece_name} bằng {possible_offer['reply_san']}; "
                f"dù tính cả khả năng bắt lại ngay trên ô đó, bạn vẫn mất ít nhất "
                f"{possible_offer['net_material_loss']} điểm vật chất. "
                "Trong biến thể mạnh nhất Stockfish lại không nhận quân này. "
                "Nước thí vẫn giữ điểm kỳ vọng gần phương án tốt nhất; "
                "hãy đi thử nước nhận quân trên bàn để xem đòn đáp cụ thể."
            )
        else:
            parts.append(
                "Biến thể này chưa chứng minh được thí quân thật; hãy phân tích sâu hơn "
                "trước khi tin nhãn Brilliant."
            )
    elif assessment["category"] == "great":
        parts.append(f"{san} giữ được lựa chọn mạnh trong thế cờ này; phương án đứng sau mà máy xét kém hơn rõ rệt.")
    elif assessment["category"] == "miss":
        parts.append(f"Máy tìm thấy cơ hội lớn hơn với {assessment['best_prior']}; {san} bỏ qua cơ hội đó.")
    if offer and offer["net_material_loss"] <= 0:
        piece_name = PIECE_NAMES[offer["piece_type"]]
        captured_type = offer["followup_capture_type"]
        if captured_type == offer["piece_type"]:
            parts.append(
                f"Nếu đối phương chơi {offer['reply_san']} để bắt {piece_name}, "
                f"{offer['followup_san']} bắt lại {piece_name} của họ. "
                f"Đây là đổi {piece_name} ngang giá, không phải thí {piece_name}."
            )
        else:
            parts.append(
                f"Nếu đối phương nhận {piece_name} bằng {offer['reply_san']}, "
                f"bạn đáp {offer['followup_san']} và không kém vật chất sau chuỗi đó."
            )
    best_prior = assessment["best_prior"]
    if best_prior and best_prior != san:
        gap = (
            "gần như ngang nhau trong lần phân tích này"
            if loss < 0.001 else f"chênh {loss * 100:.1f} điểm phần trăm"
        )
        parts.append(
            f"Máy ưu tiên {best_prior}; {san} giữ khoảng {played_ep * 100:.1f}% "
            f"điểm kỳ vọng, so với {best_ep * 100:.1f}% của phương án đầu. "
            f"Hai cách đi {gap}."
        )
    else:
        parts.append(
            f"{san} là phương án máy ưu tiên trong lần phân tích này "
            f"(khoảng {played_ep * 100:.1f}% điểm kỳ vọng)."
        )
    if played_ep < 0.30 and assessment["category"] in (
        "brilliant", "great", "best", "excellent", "good"
    ):
        parts.append(
            f"Thế cờ trước đó đã khó cho bạn: {best_ep * 100:.1f}% là mức "
            "của phương án mạnh nhất. Nhãn tốt ở đây chỉ nói nước này không làm "
            "giảm thêm nhiều cơ hội, không có nghĩa bạn đang hơn thế."
        )
    if best_line:
        parts.append(f"Thử phương án máy chọn: {best_line}")
    if played_line:
        parts.append(f"Nếu giữ nước {san}: {played_line}")
    if any(word in question_lower for word in ("thay", "khác", "tốt nhất", "nên đi")):
        parts.append(
            f"Để so sánh trực tiếp, bấm ‘Đi nước mạnh nhất trên bàn’ và thử "
            f"{best_prior or 'nước máy chọn'} từ vị trí trước {san}."
        )
    return "\n\n".join(parts)
