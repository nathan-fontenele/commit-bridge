import tempfile
import unittest
from pathlib import Path

from src.markdown_writer import append_line, normalize_activity_files


class MarkdownWriterTests(unittest.TestCase):
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
