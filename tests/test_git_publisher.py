import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.commit_filter import Commit
from src.git_publisher import Publisher


def git(directory, *args):
    return subprocess.run(["git", *args], cwd=directory, check=True, capture_output=True, text=True).stdout.strip()


class PublisherTests(unittest.TestCase):
    def test_repair_upgrades_saved_legacy_row_without_changing_state_or_republishing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bare = root / "remote.git"
            checkout = root / "checkout"
            git(root, "init", "--bare", str(bare))
            git(root, "clone", str(bare), str(checkout))
            git(checkout, "config", "user.name", "Initial")
            git(checkout, "config", "user.email", "initial@example.com")
            commit = Commit("org", "project", "Payment API", "repo", "payment-service", "a" * 40,
                            "feat: original", "me@example.com",
                            datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc))
            relative = "activity/2026/10/2026-10-09.md"
            path = checkout / relative
            path.parent.mkdir(parents=True)
            path.write_text("[Payment API] feat: original - aaaaaaaa\n", encoding="utf-8")
            state_path = checkout / "state/synced_commits.json"
            state_path.parent.mkdir()
            state = {"version": 1, "synced": {
                commit.key: {"synced_at": "2026-10-09T12:31:00-03:00", "file": relative}}}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            git(checkout, "add", ".")
            git(checkout, "commit", "-m", "initial")
            git(checkout, "push", "origin", "HEAD:main")
            git(checkout, "checkout", "main")
            publisher = Publisher(checkout, branch="main",
                                  email="41898282+github-actions[bot]@users.noreply.github.com",
                                  name="github-actions[bot]", output_dir="activity", hash_length=8,
                                  timezone="America/Sao_Paulo")
            original_state = state_path.read_text()
            self.assertTrue(publisher.repair_format(resolve=lambda key: commit))
            self.assertFalse(publisher.repair_format(resolve=lambda key: commit))
            self.assertEqual(path.read_text(),
                             "[2026-10-09 12:30:00 -03:00] [Payment API] [payment-service] "
                             "[feat: original] [aaaaaaaa]  \n")
            self.assertEqual(state_path.read_text(), original_state)
            self.assertEqual(git(root, "--git-dir", str(bare), "rev-list", "--count", "main"), "2")

    def test_format_repair_uses_one_bot_commit_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bare = root / "remote.git"
            checkout = root / "checkout"
            git(root, "init", "--bare", str(bare))
            git(root, "clone", str(bare), str(checkout))
            git(checkout, "config", "user.name", "Initial")
            git(checkout, "config", "user.email", "initial@example.com")
            legacy = checkout / "activity/2026/10/2026-10-09.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("[Project] first - aaaaaaaa\n[Project] second - bbbbbbbb\n", encoding="utf-8")
            git(checkout, "add", ".")
            git(checkout, "commit", "-m", "initial")
            git(checkout, "push", "origin", "HEAD:main")
            git(checkout, "checkout", "main")
            publisher = Publisher(checkout, branch="main",
                                  email="41898282+github-actions[bot]@users.noreply.github.com",
                                  name="github-actions[bot]", output_dir="activity", hash_length=8,
                                  timezone="America/Sao_Paulo")
            self.assertTrue(publisher.repair_format())
            self.assertFalse(publisher.repair_format())
            self.assertEqual(git(root, "--git-dir", str(bare), "rev-list", "--count", "main"), "2")
            self.assertEqual(git(checkout, "log", "-1", "--format=%ae"),
                             "41898282+github-actions[bot]@users.noreply.github.com")
            self.assertEqual(legacy.read_text(encoding="utf-8"),
                             "[Project] first - aaaaaaaa  \n[Project] second - bbbbbbbb  \n")

    def test_one_remote_commit_per_event_and_idempotence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bare = root / "remote.git"
            checkout = root / "checkout"
            git(root, "init", "--bare", str(bare))
            git(root, "clone", str(bare), str(checkout))
            git(checkout, "config", "user.name", "Initial")
            git(checkout, "config", "user.email", "initial@example.com")
            (checkout / "state").mkdir()
            (checkout / "state/synced_commits.json").write_text('{"version": 1, "synced": {}}\n')
            legacy = checkout / "activity/2020/01/2020-01-01.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("[Legacy] older commit - 12345678\n", encoding="utf-8")
            git(checkout, "add", ".")
            git(checkout, "commit", "-m", "initial")
            git(checkout, "push", "origin", "HEAD:main")
            git(checkout, "checkout", "main")
            commits = [Commit("org", "project", "Payment API", "repo", "payment-service", x * 40,
                              f"feat: change {x}", "me@example.com", datetime.now(timezone.utc))
                       for x in "abc"]
            publisher = Publisher(checkout, branch="main", email="verified@example.com", name="Me",
                                  output_dir="activity", hash_length=8, timezone="America/Sao_Paulo")
            for commit in commits:
                self.assertTrue(publisher.publish(commit))
            self.assertFalse(publisher.publish(commits[0]))
            self.assertEqual(int(git(checkout, "rev-list", "--count", "HEAD")), 4)
            state = json.loads((checkout / "state/synced_commits.json").read_text())
            self.assertEqual(len(state["synced"]), 3)
            activity = list((checkout / "activity").rglob("*.md"))
            self.assertEqual(len(activity), 2)
            current = next(path for path in activity if path != legacy)
            self.assertEqual(len(current.read_text().splitlines()), 3)
            first_line = current.read_text().splitlines()[0].rstrip()
            self.assertIn("[Payment API] [payment-service] [feat: change a] [aaaaaaaa]", first_line)
            self.assertEqual(git(checkout, "log", "-1", "--format=%s"),
                             current.read_text().splitlines()[-1].rstrip())
            self.assertEqual(git(root, "--git-dir", str(bare), "rev-list", "--count", "main"), "4")
            remote_legacy = subprocess.run(["git", "--git-dir", str(bare), "show",
                                            "main:activity/2020/01/2020-01-01.md"],
                                           check=True, capture_output=True, text=True).stdout
            self.assertEqual(remote_legacy, "[Legacy] older commit - 12345678  \n")

    def test_push_failure_reconciles_remote_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bare = root / "remote.git"
            checkout = root / "checkout"
            git(root, "init", "--bare", str(bare))
            git(root, "clone", str(bare), str(checkout))
            git(checkout, "config", "user.name", "Initial")
            git(checkout, "config", "user.email", "initial@example.com")
            (checkout / "state").mkdir()
            (checkout / "state/synced_commits.json").write_text('{"version": 1, "synced": {}}\n')
            git(checkout, "add", ".")
            git(checkout, "commit", "-m", "initial")
            git(checkout, "push", "origin", "HEAD:main")
            git(checkout, "checkout", "main")
            publisher = Publisher(checkout, branch="main", email="verified@example.com", name="Me",
                                  output_dir="activity", hash_length=8, timezone="America/Sao_Paulo")
            commit = Commit("org", "project", "Payment API", "repo", "payment-service", "a" * 40,
                            "feat: test", "me@example.com", datetime.now(timezone.utc))
            original_git = publisher.git

            def fake_git(*args, **kwargs):
                if args[0] == "push":
                    original_git(*args)  # Remote succeeded; only the response was lost.
                    return subprocess.CompletedProcess(args, 1, "", "network response lost")
                return original_git(*args, **kwargs)

            with patch.object(publisher, "git", side_effect=fake_git):
                self.assertFalse(publisher.publish(commit))
            self.assertEqual(git(root, "--git-dir", str(bare), "rev-list", "--count", "main"), "2")
