"""Offline opening names and continuations from lichess-org/chess-openings."""

from collections import Counter
import csv
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import chess
import chess.polyglot


SOURCE_DIR = Path(__file__).resolve().parent / "openings" / "source"
MOVE_NUMBER = re.compile(r"\d+\.(?:\.\.)?")


@dataclass
class OpeningNode:
    names: list[tuple[str, str]] = field(default_factory=list)
    next_moves: Counter[str] = field(default_factory=Counter)


class OpeningGuide:
    def __init__(self, source_dir: Path = SOURCE_DIR) -> None:
        self.nodes: dict[int, OpeningNode] = {}
        for letter in "abcde":
            path = source_dir / f"{letter}.tsv"
            if not path.is_file():
                continue
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    board = chess.Board()
                    try:
                        for san in MOVE_NUMBER.sub("", row["pgn"]).split():
                            move = board.parse_san(san)
                            self.nodes.setdefault(self.key(board), OpeningNode()).next_moves[move.uci()] += 1
                            board.push(move)
                    except (KeyError, ValueError):
                        continue
                    names = self.nodes.setdefault(self.key(board), OpeningNode()).names
                    entry = (row["eco"], row["name"])
                    if entry not in names:
                        names.append(entry)

    @staticmethod
    def key(board: chess.Board) -> int:
        return chess.polyglot.zobrist_hash(board)

    def node(self, board: chess.Board) -> OpeningNode | None:
        return self.nodes.get(self.key(board))

    def name(self, positions: list[chess.Board]) -> tuple[str, str] | None:
        for board in reversed(positions):
            node = self.node(board)
            if node and node.names:
                return max(node.names, key=lambda entry: len(entry[1]))
        return None

    def continuations(self, board: chess.Board, limit: int = 3) -> list[tuple[chess.Move, int]]:
        node = self.node(board)
        if node is None:
            return []
        moves = []
        for uci, count in node.next_moves.most_common():
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                moves.append((move, count))
            if len(moves) == limit:
                break
        return moves

    def reentries(self, board: chess.Board) -> list[tuple[chess.Move, OpeningNode]]:
        """Legal one-move transpositions back into a catalogued position."""
        found = []
        for move in board.legal_moves:
            after = board.copy(stack=False)
            after.push(move)
            node = self.node(after)
            if node is not None:
                found.append((move, node))
        return found


@lru_cache(maxsize=1)
def get_opening_guide() -> OpeningGuide:
    return OpeningGuide()


def fetch_master_opening(board: chess.Board) -> dict:
    """Read anonymous aggregate move counts for one position; never send a PGN or username."""
    query = urlencode({"fen": board.fen(), "moves": 12, "topGames": 0})
    request = Request("https://explorer.lichess.org/masters?" + query,
                      headers={"User-Agent": "Stockfish-Move-Review/1.0"})
    with urlopen(request, timeout=3) as response:
        data = json.load(response)
    if not isinstance(data, dict) or not isinstance(data.get("moves"), list):
        raise ValueError("Invalid opening explorer response")
    return data


def _reason(board: chess.Board, move: chess.Move) -> str:
    piece = board.piece_at(move.from_square)
    destination = chess.square_name(move.to_square)
    if board.is_castling(move):
        return "đưa vua vào nơi an toàn và nối hai xe"
    if board.is_capture(move):
        return f"bắt quân hoặc tốt ở {destination}"
    if piece and piece.piece_type == chess.PAWN and chess.square_file(move.to_square) == 2:
        if chess.square_rank(move.to_square) in (2, 5):
            return "chuẩn bị đẩy tốt d để tranh trung tâm"
    if piece and piece.piece_type == chess.PAWN and chess.square_file(move.to_square) == 3:
        if chess.square_rank(move.to_square) in (2, 5):
            return "củng cố tốt e và mở đường cho tượng"
    if piece and piece.piece_type == chess.PAWN and chess.square_file(move.to_square) in (3, 4):
        return "tranh chấp các ô trung tâm"
    if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) in (0, 7):
        return "phát triển quân ra khỏi hàng cuối"
    if board.gives_check(move):
        return "tạo nước chiếu buộc đối phương đáp lại"
    return f"cải thiện vị trí quân tại {destination}"


def opening_explanation(positions: list[chess.Board], player_color: chess.Color,
                        guide: OpeningGuide | None = None,
                        turn_known: bool = True,
                        master_data: dict | None = None,
                        waiting_for_stats: bool = False,
                        engine_move: chess.Move | None = None,
                        engine_line: list[chess.Move] | None = None) -> str:
    """Explain a known opening position without claiming to know a player's intent."""
    if not positions:
        return ""
    guide = guide or get_opening_guide()
    board = positions[-1]
    node = guide.node(board)
    current_name = (max(node.names, key=lambda entry: len(entry[1]))
                    if node and node.names else None)
    previous_name = guide.name(positions[:-1])
    if (node is None and previous_name is None and master_data is None
            and not (board.fullmove_number <= 12 and engine_move is not None)):
        return ""
    official = master_data.get("opening") if master_data else None
    if (current_name and isinstance(official, dict)
            and official.get("eco") and official.get("name")):
        current_name = (official["eco"], official["name"])
    if current_name:
        lines = [f"Vị trí hiện tại khớp danh mục: {current_name[0]} · {current_name[1]}."]
        if board.fullmove_number <= 3:
            lines.append("Mới có vài nước: đây là tên của vị trí, chưa thể biết ý định khai cuộc của đối phương.")
    elif node and previous_name:
        lines = [f"Tên được nhận diện gần nhất: {previous_name[0]} · {previous_name[1]}. "
                 "Vị trí mới có trong danh mục nhưng chưa có tên biến thể riêng."]
    elif node:
        lines = ["Vị trí này nằm trong danh mục, nhưng còn quá sớm để xác định tên khai cuộc."]
    elif previous_name:
        lines = [f"Tên ở vị trí trước: {previous_name[0]} · {previous_name[1]}. "
                 "Vị trí hiện tại không còn trong danh mục khai cuộc cục bộ."]
    else:
        lines = ["Chưa xác định được tên khai cuộc từ vị trí này."]

    if len(positions) > 1 and board.move_stack:
        previous = positions[-2]
        last_move = board.move_stack[-1]
        if last_move in previous.legal_moves:
            actor = "Bạn" if board.turn != player_color else "Đối phương"
            lines.append(f"{actor} vừa đi {previous.san(last_move)}.")
    if node is None:
        lines.append("Nước vừa đi có thể vẫn thuộc giai đoạn khai cuộc, nhưng không khớp "
                     "danh mục này; tên cũ không phải tên của thế cờ hiện tại.")
    elif not node.next_moves:
        lines.append("Danh mục dừng tại vị trí này. Nước tiếp theo sẽ không tự mang nhãn "
                     "Book Move, trừ khi chuyển vị vào một thế cờ đã được ghi lại.")

    if not turn_known:
        lines.append("Đã nhận diện quân, nhưng chưa xác định được bên tới lượt. "
                     "Bruno sẽ nêu nước tiếp theo khi ảnh cho biết lượt đi.")
        return "\n".join(lines)

    if waiting_for_stats:
        lines.append("Đang tra các nước từng được chơi trong ván cao thủ Lichess…")

    out_of_catalog = node is None or not node.next_moves
    valid_engine_move = engine_move is not None and engine_move in board.legal_moves
    if out_of_catalog and board.turn == player_color:
        reentries = guide.reentries(board)
        if valid_engine_move:
            san = board.san(engine_move)
            match = next((entry for move, entry in reentries if move == engine_move), None)
            if match is not None:
                target = max(match.names, key=lambda entry: len(entry[1])) if match.names else None
                suffix = f" ({target[0]} · {target[1]})" if target else ""
                lines.append(f"Stockfish ưu tiên {san}: {_reason(board, engine_move)}. "
                             f"Nước này chuyển vị trở lại danh mục{suffix}.")
            else:
                lines.append(f"Stockfish ưu tiên {san}: {_reason(board, engine_move)}. "
                             "Đây là kế hoạch phù hợp với thế cờ hiện tại, không tự mang nhãn Book Move.")
            if engine_line and engine_line[0] == engine_move:
                legal_line = []
                continuation = board.copy(stack=False)
                for move in engine_line[:3]:
                    if move not in continuation.legal_moves:
                        break
                    legal_line.append(move)
                    continuation.push(move)
                if len(legal_line) >= 2:
                    lines.append("Một phản hồi có thể xảy ra nếu hai bên chơi chính xác: "
                                 + board.variation_san(legal_line) + ".")
        else:
            lines.append("Đang chờ Stockfish kiểm tra nước phù hợp với vị trí hiện tại.")
        other_reentries = [(move, entry) for move, entry in reentries if move != engine_move]
        if other_reentries:
            names = ", ".join(board.san(move) for move, _ in other_reentries[:3])
            lines.append(f"Có đường chuyển vị trực tiếp về danh mục qua {names}; "
                         "đó là các nước hợp lệ, chưa được xác nhận là nước mạnh nhất.")
        elif not reentries:
            lines.append("Chưa có nước hợp lệ nào chuyển ngay về danh mục; "
                         "hãy giữ nguyên tắc phát triển quân, tranh trung tâm và bảo vệ vua.")
    elif out_of_catalog and board.turn != player_color:
        lines.append("Đến lượt đối phương. Bruno sẽ cập nhật kế hoạch của bạn sau nước họ đi thật.")

    choices = guide.continuations(board, 100)
    master_moves: dict[str, dict] = {}
    if master_data:
        for item in master_data.get("moves", []):
            try:
                move = board.parse_san(item["san"])
            except (KeyError, ValueError):
                continue
            master_moves[move.uci()] = item
        if choices:
            choices.sort(key=lambda pair: sum(
                master_moves.get(pair[0].uci(), {}).get(key, 0)
                for key in ("white", "draws", "black")
            ), reverse=True)
        else:
            for item in master_data.get("moves", []):
                try:
                    move = board.parse_san(item["san"])
                except (KeyError, ValueError):
                    continue
                games = sum(item.get(key, 0) for key in ("white", "draws", "black"))
                if games:
                    choices.append((move, 0))
    choices = choices[:3]
    if not choices:
        if master_data is not None and not (out_of_catalog and valid_engine_move):
            lines.append("Cơ sở ván cao thủ cũng chưa có đủ dữ liệu cho vị trí này; "
                         "Bruno không đoán nước tiếp theo.")
        return "\n".join(lines)
    source = ("danh mục" if node and node.next_moves
              else "ván cao thủ (chưa chắc là Book Move)")
    if board.turn == player_color:
        lines.append(f"Đến lượt bạn. Các hướng từ {source}:")
    else:
        lines.append(f"Đến lượt đối phương. Các hướng họ có thể chọn từ {source}:")
    for move, count in choices:
        san = board.san(move)
        item = master_moves.get(move.uci())
        games = sum(item.get(key, 0) for key in ("white", "draws", "black")) if item else 0
        evidence = f"{games:,} ván cao thủ" if games else f"{count} nhánh danh mục"
        variation = item.get("opening") if item else None
        named = f" → {variation['name']}" if isinstance(variation, dict) and variation.get("name") else ""
        lines.append(f"• {san}: {_reason(board, move)} ({evidence}){named}.")
    if board.turn != player_color:
        lines.append("Chờ đối phương đi thật rồi Bruno sẽ chọn các hướng lý thuyết từ vị trí mới.")
    lines.append("Số ván là thống kê cao thủ Lichess; số nhánh là độ phủ danh mục, "
                 "không phải tỷ lệ thắng của bạn. Biểu tượng sách còn phụ thuộc đánh giá Stockfish.")
    return "\n".join(lines)
