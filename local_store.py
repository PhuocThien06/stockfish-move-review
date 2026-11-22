"""Local favorites and rolling 30-day PGN retention."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def favorites_path(directory: Path) -> Path:
    return directory.parent / "favorites.json"


def settings_path(directory: Path) -> Path:
    return directory.parent / "settings.json"


def load_last_username(directory: Path, default: str = "EnergeticCyborg") -> str:
    """Return the account used for the last sync, keeping settings on drive D."""
    try:
        data = json.loads(settings_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    username = data.get("last_username") if isinstance(data, dict) else None
    return username if isinstance(username, str) and re.fullmatch(
        r"[A-Za-z0-9_.-]{2,32}", username
    ) else default


def save_last_username(directory: Path, username: str) -> None:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", username):
        raise ValueError("Tên tài khoản không hợp lệ.")
    path = settings_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"last_username": username}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_favorites(directory: Path) -> set[str]:
    path = favorites_path(directory)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {name for name in data if isinstance(name, str)} if isinstance(data, list) else set()


def save_favorites(directory: Path, names: set[str]) -> None:
    path = favorites_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def prune_old_games(directory: Path, days: int = 30, now: float | None = None) -> int:
    """Remove only top-level, nonfavorite PGNs whose game/save age exceeds days."""
    if not directory.is_dir():
        return 0
    timestamp = time.time() if now is None else now
    cutoff = timestamp - days * 86400
    index = favorites_path(directory)
    if index.is_file():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Danh sách yêu thích bị lỗi; đã dừng dọn PGN để bảo toàn ván.") from exc
        if not isinstance(data, list) or any(not isinstance(name, str) for name in data):
            raise ValueError("Danh sách yêu thích không hợp lệ; đã dừng dọn PGN.")
        favorites = set(data)
    else:
        favorites = set()
    removed = 0
    for path in directory.glob("*.pgn"):
        if path.is_symlink() or not path.is_file() or path.name in favorites:
            continue
        match = re.match(r"chesscom-(\d{8})-(\d{6})-", path.name)
        if match:
            try:
                ended = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
                age_time = ended.replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                age_time = path.stat().st_mtime
        else:
            age_time = path.stat().st_mtime
        if age_time < cutoff:
            path.unlink()
            removed += 1
    return removed
