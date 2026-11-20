"""Evidence-first Vietnamese explanations of local Stockfish assessments."""

from __future__ import annotations

import chess

from analysis_core import LABELS, variation_text


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


def explain_move(board: chess.Board, move: chess.Move, assessment: dict, question: str = "") -> str:
    """Explain only verifiable board facts and engine lines; avoid invented plans."""
    san = board.san(move)
    label = LABELS[assessment["category"]][0]
    loss = assessment["ep_loss"]
    best_ep = assessment["best_ep"]
    played_ep = assessment["played_ep"]
    best_line = variation_text(board, assessment["best_pv"], 8)
    played_line = variation_text(board, assessment["played_pv"], 8)
    question = question.strip()
    question_lower = question.casefold()
    introduction = f"Bạn hỏi: {question}\n\n" if question else ""
    parts = [introduction + f"Bruno · {san} được xếp loại {label}."]
    parts.append(
        f"Vì sao? Stockfish so sánh các nước hợp lệ từ cùng một thế cờ. "
        f"Điểm kỳ vọng của phương án tốt nhất là {best_ep * 100:.1f}%, "
        f"còn nước {san} là {played_ep * 100:.1f}%. "
        f"Chênh lệch là {loss * 100:.1f} điểm phần trăm. "
        "Đây là thước đo từ xác suất thắng/hòa/thua của Stockfish, không phải tỷ lệ thắng chắc chắn của bạn."
    )
    if assessment["category"] == "book":
        parts.append("Nước đi nằm trong cơ sở dữ liệu khai cuộc và không làm giảm đáng kể điểm kỳ vọng.")
    elif assessment["category"] == "forced":
        parts.append("Trước khi đi, chỉ có đúng một nước hợp lệ nên nước này được xếp là bắt buộc.")
    elif assessment["category"] == "brilliant":
        parts.append("Đây là một nước hy sinh quân rõ ràng trong biến thể máy tính, nhưng vẫn giữ được thế cờ tốt. Nhãn này là ước lượng của ứng dụng.")
    elif assessment["category"] == "great":
        parts.append("Nước này nổi bật vì phương án đứng thứ hai kém hơn rõ rệt theo Stockfish. Nhãn này là ước lượng của ứng dụng.")
    elif assessment["category"] == "miss":
        parts.append("Trước nước đi có cơ hội lớn; sau nước đi lợi thế giảm mạnh. So sánh hai biến thể dưới đây để thấy cơ hội đã bỏ lỡ.")
    elif assessment["category"] in ("inaccuracy", "mistake", "blunder"):
        parts.append("Nước đi làm giảm đáng kể điểm kỳ vọng. Hãy xem nước thay thế và câu trả lời dự kiến của đối phương; nguyên nhân cụ thể nằm trong biến thể, không thể suy ra chỉ từ con số.")
    else:
        parts.append("Nước đi giữ phần lớn giá trị của vị trí. Nhãn phụ thuộc vào độ sâu và thời gian Stockfish được chạy.")
    parts.append("Trên bàn cờ: " + " ".join(_observations(board, move)))
    if best_line:
        parts.append(f"Nếu đi phương án mạnh nhất: {best_line}")
    if played_line:
        parts.append(f"Sau nước bạn đã đi, máy dự kiến: {played_line}")
    if assessment["best_prior"] and assessment["best_prior"] != san:
        parts.append(f"Nước máy ưu tiên tại thời điểm đó: {assessment['best_prior']}.")
    if any(word in question_lower for word in ("thay", "khác", "tốt nhất", "nên đi")):
        parts.append(
            f"Để thử nước thay thế, quay lại thế cờ trước {san} và đi {assessment['best_prior'] or 'nước đầu tiên trong biến thể mạnh nhất'}. "
            "Sau đó so sánh câu trả lời của đối phương và thanh đánh giá. "
            "Một biến thể chỉ là dự báo trong điều kiện chơi chính xác, không phải nước bắt buộc."
        )
    elif any(word in question_lower for word in ("chiến thuật", "bắt quân", "hy sinh", "chiếu")):
        parts.append(
            "Khi kiểm tra chiến thuật, hãy nhìn trước tiên vào nước chiếu, nước bắt quân và đòn đe dọa sau nước đầu tiên "
            "của mỗi biến thể. Những dữ kiện trên bàn được liệt kê ở đoạn 'Trên bàn cờ'; "
            "mình không gán tên chiến thuật nếu chưa thể chứng minh bằng chuỗi nước đi."
        )
    elif "khai cuộc" in question_lower:
        parts.append(
            "Trong khai cuộc, hãy kiểm tra việc phát triển mã/tượng, tranh trung tâm và an toàn vua. "
            "Nếu đây là nước lý thuyết, nhãn 'Theo lý thuyết' chỉ nói rằng vị trí có trong cơ sở dữ liệu khai cuộc."
        )
    parts.append(
        "Cách đọc biến thể: mỗi nước sau dấu đầu tiên là câu trả lời mạnh dự kiến khi cả hai bên đều chơi chính xác. "
        "Bạn có thể quay về vị trí trước nước này và thử các nước trên bàn để tự kiểm chứng. "
        "Nếu muốn, hãy hỏi tiếp về khai cuộc, chiến thuật, hoặc nước thay thế; phần mềm sẽ giải thích bằng dữ kiện đang có."
    )
    return "\n\n".join(parts)
