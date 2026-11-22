"""User preferences remain on drive D across app launches."""

import tempfile
import unittest
from pathlib import Path

from local_store import load_last_username, save_last_username, settings_path


class LastUsernameTests(unittest.TestCase):
    def test_uses_current_username_until_first_search_and_remembers_new_search(self) -> None:
        scratch = Path(__file__).resolve().parents[1] / "work"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            games = Path(temporary) / "games"
            self.assertEqual("EnergeticCyborg", load_last_username(games))
            save_last_username(games, "  AnotherPlayer  ")
            self.assertEqual("AnotherPlayer", load_last_username(games))
            self.assertEqual(games.parent / "settings.json", settings_path(games))

    def test_invalid_or_damaged_settings_do_not_replace_last_good_search(self) -> None:
        scratch = Path(__file__).resolve().parents[1] / "work"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            games = Path(temporary) / "games"
            save_last_username(games, "EnergeticCyborg")
            with self.assertRaises(ValueError):
                save_last_username(games, "bad name!")
            self.assertEqual("EnergeticCyborg", load_last_username(games))
            settings_path(games).write_text("{invalid json", encoding="utf-8")
            self.assertEqual("EnergeticCyborg", load_last_username(games))


if __name__ == "__main__":
    unittest.main()
