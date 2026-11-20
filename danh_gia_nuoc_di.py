"""Đánh giá các nước đã đi trong tệp PGN bằng Stockfish, không hiện gợi ý."""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

from analysis_core import LABELS, assess_move, configure_engine, open_engine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import chess
    import chess.engine
    import chess.pgn
except ImportError:
    print("Thiếu thư viện python-chess. Chạy: python -m pip install python-chess", file=sys.stderr)
    raise SystemExit(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chấm các nước trong ván PGN, không hiển thị nước đi tiếp theo."
    )
    parser.add_argument("pgn", type=Path, help="Tệp .pgn xuất từ Chess.com")
    parser.add_argument(
        "--stockfish", default="stockfish", help="Đường dẫn tới stockfish.exe"
    )
    parser.add_argument(
        "--time", type=float, default=0.5,
        help="Số giây Stockfish phân tích mỗi vị trí (mặc định: 0.5)",
    )
    parser.add_argument(
        "--player", help="Chỉ chấm nước của người chơi có tên này trong PGN"
    )
    parser.add_argument("--csv", type=Path, help="Lưu kết quả thành tệp CSV")
    args = parser.parse_args()
    if args.time <= 0:
        parser.error("--time phải lớn hơn 0")
    if not args.pgn.is_file():
        parser.error(f"Không tìm thấy tệp PGN: {args.pgn}")
    if args.csv is not None and not args.csv.is_absolute():
        args.csv = Path("D:/Chess/data/reports") / args.csv
    return args


def engine_path(value: str) -> str:
    found = shutil.which(value)
    if found:
        return found
    path = Path(value).expanduser()
    if path.is_file():
        return str(path.resolve())
    raise FileNotFoundError(
        "Không tìm thấy Stockfish. Hãy thêm --stockfish \"D:\\Chess\\engine\\stockfish.exe\"."
    )


def evaluate_move(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    move: chess.Move,
    seconds: float,
) -> tuple[str, str]:
    result = assess_move(engine, board, move, seconds)
    detail = f"mất {result['ep_loss'] * 100:.1f}% điểm kỳ vọng"
    return LABELS[result["category"]][0], detail


def review_game(
    engine: chess.engine.SimpleEngine,
    game: chess.pgn.Game,
    game_number: int,
    seconds: float,
    player: str | None,
    writer: csv.writer | None,
) -> int:
    white = game.headers.get("White", "Trắng")
    black = game.headers.get("Black", "Đen")
    print(f"\nVán {game_number}: {white} - {black}")
    board = game.board()
    count = 0
    for move in game.mainline_moves():
        color = board.turn
        san = board.san(move)
        move_number = board.fullmove_number
        name = white if color == chess.WHITE else black
        if player is None or name.casefold() == player.casefold():
            label, detail = evaluate_move(engine, board, move, seconds)
            notation = f"{move_number}{'.' if color == chess.WHITE else '...'} {san}"
            print(f"  {notation:<14} {label:<16} {detail}")
            if writer is not None:
                writer.writerow([game_number, move_number, name, notation, label, detail])
            count += 1
        board.push(move)
    return count


def main() -> int:
    args = parse_args()
    try:
        executable = engine_path(args.stockfish)
        engine = open_engine(executable)
        configure_engine(engine, False)
    except (FileNotFoundError, OSError, chess.engine.EngineError) as exc:
        print(f"Không mở được Stockfish: {exc}", file=sys.stderr)
        return 2

    csv_file = None
    try:
        if args.csv is not None:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            csv_file = args.csv.open("w", encoding="utf-8-sig", newline="")
            writer = csv.writer(csv_file)
            writer.writerow(["Ván", "Lượt", "Người chơi", "Nước đi", "Đánh giá", "Chi tiết"])
        else:
            writer = None

        games = 0
        moves = 0
        with args.pgn.open("r", encoding="utf-8-sig") as pgn_file:
            while (game := chess.pgn.read_game(pgn_file)) is not None:
                if game.errors:
                    raise ValueError(f"PGN lỗi ở ván {games + 1}: {game.errors[0]}")
                games += 1
                moves += review_game(
                    engine, game, games, args.time, args.player, writer
                )
        if games == 0:
            raise ValueError("Tệp PGN không có ván cờ nào.")
        print(f"\nĐã xem {games} ván, chấm {moves} nước.")
        if args.csv is not None:
            print(f"Đã lưu CSV: {args.csv.resolve()}")
        return 0
    except (OSError, ValueError, chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    finally:
        if csv_file is not None:
            csv_file.close()
        engine.quit()


if __name__ == "__main__":
    raise SystemExit(main())
