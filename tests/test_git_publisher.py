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
            git(checkout, "add", ".")
            git(checkout, "commit", "-m", "initial")
            git(checkout, "push", "origin", "HEAD:main")
            git(checkout, "checkout", "main")
            commits = [Commit("org", "project", "Payment API", "repo", x * 40,
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
            self.assertEqual(len(activity), 1)
            self.assertEqual(len(activity[0].read_text().splitlines()), 3)
            self.assertEqual(git(root, "--git-dir", str(bare), "rev-list", "--count", "main"), "4")

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
            commit = Commit("org", "project", "Payment API", "repo", "a" * 40,
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
