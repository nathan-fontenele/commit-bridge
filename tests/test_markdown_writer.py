import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.commit_filter import Commit
from src.markdown_writer import (activity_line, append_line, normalize_activity_files,
                                 repair_activity_files)


class MarkdownWriterTests(unittest.TestCase):
    def test_failed_repair_does_not_partially_rewrite_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            one = root / "activity/2026/10/2026-10-08.md"
            two = root / "activity/2026/10/2026-10-09.md"
            one.parent.mkdir(parents=True)
            one.write_text("[Project] first - aaaaaaaa\n", encoding="utf-8")
            two.write_text("[Project] second - bbbbbbbb\n", encoding="utf-8")
            state = {"synced": {
                "org:repo:" + "a" * 40: {"file": one.relative_to(root).as_posix()},
                "org:repo:" + "b" * 40: {"file": two.relative_to(root).as_posix()},
            }}
            def resolve(key):
                if key.endswith("b" * 40):
                    raise RuntimeError("Azure commit unavailable")
                return Commit("org", "project", "Project", "repo", "repository", "a" * 40,
                              "first", "me@example.com", datetime(2026, 10, 8, tzinfo=timezone.utc))

            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                repair_activity_files(root, "activity", state, resolve, 8,
                                      ZoneInfo("America/Sao_Paulo"))
            self.assertEqual(one.read_text(), "[Project] first - aaaaaaaa\n")
            self.assertEqual(two.read_text(), "[Project] second - bbbbbbbb\n")

    def test_activity_line_has_original_commit_time_project_repository_message_and_hash(self):
        commit = Commit("org", "project", "Payment API", "repo-id", "payment-service",
                        "a" * 40, "feat: add invoice validation", "me@example.com",
                        datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc))
        self.assertEqual(activity_line(commit, 8, ZoneInfo("America/Sao_Paulo")),
                         "[2026-10-09 12:30:00 -03:00] [Payment API] [payment-service] "
                         "[feat: add invoice validation] [aaaaaaaa]")

    def test_legacy_entries_gain_visible_breaks_with_next_real_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "activity/2026/10/2026-10-09.md"
            path.parent.mkdir(parents=True)
            path.write_text("[Project] first - aaaaaaaa\n[Project] second - bbbbbbbb\n", encoding="utf-8")
            append_line(path, "[Project] third - cccccccc")
            self.assertEqual(path.read_text(encoding="utf-8"),
                             "[Project] first - aaaaaaaa  \n"
                             "[Project] second - bbbbbbbb  \n"
                             "[Project] third - cccccccc  \n")
            with self.assertRaises(ValueError):
                append_line(path, "[Project] first - aaaaaaaa")

    def test_new_file_has_one_record_per_source_line(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "activity/2026/10/2026-10-09.md"
            append_line(path, "[Project] first - aaaaaaaa")
            self.assertEqual(path.read_text(encoding="utf-8"), "[Project] first - aaaaaaaa  \n")

    def test_old_daily_files_are_repaired_without_touching_other_markdown(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "activity"
            old = directory / "2026/10/2026-10-08.md"
            notes = directory / "README.md"
            old.parent.mkdir(parents=True)
            old.write_text("[Project] first - aaaaaaaa\n[Project] second - bbbbbbbb\n", encoding="utf-8")
            notes.write_text("Keep this file unchanged\n", encoding="utf-8")
            self.assertEqual(normalize_activity_files(directory), [old])
            self.assertEqual(old.read_text(encoding="utf-8"),
                             "[Project] first - aaaaaaaa  \n[Project] second - bbbbbbbb  \n")
            self.assertEqual(notes.read_text(encoding="utf-8"), "Keep this file unchanged\n")
            self.assertEqual(normalize_activity_files(directory), [])
