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
    return f"tiếp tục một nhánh lý thuyết tại ô {destination}"


def opening_explanation(positions: list[chess.Board], player_color: chess.Color,
                        guide: OpeningGuide | None = None,
                        turn_known: bool = True,
                        master_data: dict | None = None) -> str:
    """Explain a known opening position without claiming to know a player's intent."""
    if not positions:
        return ""
    guide = guide or get_opening_guide()
    board = positions[-1]
    node = guide.node(board)
    match = guide.name(positions)
    if node is None and match is None:
        return ""
    official = master_data.get("opening") if master_data else None
    if isinstance(official, dict) and official.get("eco") and official.get("name"):
        match = (official["eco"], official["name"])
    if match:
        lines = [f"Khai cuộc nhận diện: {match[0]} · {match[1]}."]
        if not node or not node.names:
            lines.append("Ván đã rời vị trí được đặt tên gần nhất; chưa có nước tiếp theo trong danh mục.")
    else:
        lines = ["Chưa đủ nước để xác định tên khai cuộc; bàn cờ vẫn ở một nhánh có trong danh mục."]

    if len(positions) > 1 and board.move_stack:
        previous = positions[-2]
        last_move = board.move_stack[-1]
        if last_move in previous.legal_moves:
            actor = "Bạn" if board.turn != player_color else "Đối phương"
            previous_name = guide.name(positions[:-1])
            change = ("; vị trí chuyển sang nhánh trên"
                      if match and match != previous_name else "; vẫn trong hướng khai cuộc này")
            lines.append(f"{actor} vừa đi {previous.san(last_move)}{change}.")

    if not turn_known:
        lines.append("Đã nhận diện quân, nhưng chưa xác định được bên tới lượt. "
                     "Bruno sẽ nêu nước tiếp theo khi ảnh cho biết lượt đi.")
        return "\n".join(lines)

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
    choices = choices[:3]
    if not choices:
        return "\n".join(lines)
    if board.turn == player_color:
        lines.append("Đến lượt bạn. Các hướng có trong danh mục:")
    else:
        lines.append("Đến lượt đối phương. Các hướng họ có thể chọn trong danh mục:")
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
