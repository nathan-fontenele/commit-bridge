import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.commit_filter import Commit
from src.main import main, read_config


class MainTests(unittest.TestCase):
    def test_private_environment_overrides_public_template(self):
        template = Path(__file__).resolve().parents[1] / "config.yaml"
        with patch.dict("src.main.os.environ", {
            "AZURE_DEVOPS_ORGANIZATION": "private-org",
            "AZURE_AUTHOR_EMAILS": "one@example.com, two@example.com",
        }):
            config, emails = read_config(template)
        self.assertEqual(config["azure_devops"]["organization"], "private-org")
        self.assertEqual(emails, {"one@example.com", "two@example.com"})

    def test_deduplication_reads_state_from_separate_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            subprocess.run(["git", "init", str(destination)], check=True, capture_output=True)
            commit = Commit("org", "project", "Project", "repo", "sample-repo", "a" * 40,
                            "real change", "me@example.com", datetime.now(timezone.utc))
            (destination / "state").mkdir()
            (destination / "state/synced_commits.json").write_text(json.dumps({
                "version": 1, "synced": {commit.key: {"synced_at": "today", "file": "activity/today.md"}}
            }))
            config = {"azure_devops": {"organization": "org"}, "sync": {"lookback_days": 7}}
            with patch.object(sys, "argv", ["sync", "--destination", str(destination)]), \
                 patch.dict("src.main.os.environ", {"AZURE_DEVOPS_PAT": "fake"}), \
                 patch("src.main.read_config", return_value=(config, {"me@example.com"})), \
                 patch("src.main.collect", return_value=[commit]), \
                 patch("src.main.Publisher") as publisher:
                main()
                publisher.assert_not_called()

    def test_public_dry_run_log_hides_commit_details(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            subprocess.run(["git", "init", str(destination)], check=True, capture_output=True)
            commit = Commit("private-org", "project", "Confidential Project", "repo", "sample-repo", "a" * 40,
                            "secret commit message", "me@example.com", datetime.now(timezone.utc))
            config = {"azure_devops": {"organization": "private-org"}, "sync": {"lookback_days": 7}}
            with patch.object(sys, "argv", ["sync", "--destination", str(destination), "--dry-run"]), \
                 patch.dict("src.main.os.environ", {"AZURE_DEVOPS_PAT": "fake"}), \
                 patch("src.main.read_config", return_value=(config, {"me@example.com"})), \
                 patch("src.main.collect", return_value=[commit]), \
                 self.assertLogs("src.main", level="INFO") as logs:
                main()
            output = "\n".join(logs.output)
            for sensitive in (commit.project_name, commit.message, commit.sha, commit.organization_id):
                self.assertNotIn(sensitive, output)
