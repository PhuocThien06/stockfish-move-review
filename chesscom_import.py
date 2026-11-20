"""User-triggered import of completed public games from Chess.com's PubAPI."""

from __future__ import annotations

import json
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_ROOT = "https://api.chess.com/pub/player"
USER_AGENT = (
    "StockfishMoveReview/1.1 "
    "(https://github.com/PhuocThien06/stockfish-move-review; personal local PGN importer)"
)


def _get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError("Không tìm thấy tài khoản hoặc kho ván công khai này.") from exc
        if exc.code == 429:
            raise ValueError("Chess.com đang giới hạn truy cập API. Hãy thử lại sau.") from exc
        raise ValueError(f"Chess.com trả về lỗi HTTP {exc.code}.") from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("Không kết nối được tới API công khai của Chess.com.") from exc


def fetch_recent_games(username: str, limit: int | None = None) -> list[dict]:
    """Fetch finished standard games from the latest two archive months."""
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", username):
        raise ValueError("Tên tài khoản chỉ gồm chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.")
    encoded = quote(username, safe="")
    archives = _get_json(f"{API_ROOT}/{encoded}/games/archives").get("archives", [])
    if not isinstance(archives, list):
        raise ValueError("Danh sách ván công khai không hợp lệ.")
    games: list[dict] = []
    now = time.time()
    for archive in reversed(archives[-2:]):
        match = re.search(r"/games/(\d{4})/(\d{2})$", str(archive))
        if not match:
            continue
        year, month = match.groups()
        time.sleep(0.25)
        payload = _get_json(f"{API_ROOT}/{encoded}/games/{year}/{month}")
        for game in payload.get("games", []):
            if not isinstance(game, dict):
                continue
            end_time = game.get("end_time")
            if (game.get("rules", "chess") != "chess" or not isinstance(end_time, int)
                    or end_time > now or end_time < now - 30 * 86400 or not game.get("pgn")):
                continue
            games.append(game)
    games.sort(key=lambda game: game["end_time"], reverse=True)
    return games[:limit] if limit is not None else games


def sync_recent_games(username: str, directory: Path) -> dict:
    """Save each recent completed PGN once under D:/Chess/data/games."""
    games = fetch_recent_games(username)
    directory.mkdir(parents=True, exist_ok=True)
    newest: Path | None = None
    created = 0
    for game in reversed(games):
        source = str(game.get("uuid") or game.get("url") or game["pgn"])
        fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        stamp = datetime.fromtimestamp(game["end_time"], timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"chesscom-{stamp}-{username.casefold()}-{fingerprint}.pgn"
        target = directory / filename
        if not target.is_file():
            temporary = target.with_suffix(".part")
            temporary.write_text(game["pgn"].rstrip() + "\n", encoding="utf-8")
            temporary.replace(target)
            created += 1
        newest = target
    return {"created": created, "total": len(games), "latest": newest}
