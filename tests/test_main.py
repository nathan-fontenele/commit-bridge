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
    def test_repair_resolves_old_state_keys_from_azure(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            subprocess.run(["git", "init", str(destination)], check=True, capture_output=True)
            sha = "a" * 40
            config = {"azure_devops": {"organization": "org"},
                      "sync": {"timezone": "America/Sao_Paulo"},
                      "output": {"directory": "activity", "hash_length": 8}}

            class FakeClient:
                def __init__(self, organization, pat):
                    self.organization = organization

                def projects(self):
                    return [{"id": "project-id", "name": "Payment API"}]

                def repositories(self, project_id):
                    return [{"id": "repo-id", "name": "payment-service"}]

                def commit(self, project_id, repository_id, commit_sha):
                    self.requested = (project_id, repository_id, commit_sha)
                    return {"commitId": sha, "author": {"email": "me@example.com"},
                            "committer": {"date": "2026-10-09T15:30:00Z"},
                            "comment": "feat: original\nsecond line"}

            with patch.object(sys, "argv", ["sync", "--destination", str(destination), "--repair-format"]), \
                 patch.dict("src.main.os.environ", {
                     "AZURE_DEVOPS_PAT": "fake", "GITHUB_COMMIT_EMAIL": "bot@example.com",
                     "GITHUB_COMMIT_NAME": "bot", "GITHUB_DEFAULT_BRANCH": "main"}), \
                 patch("src.main.read_config", return_value=(config, {"me@example.com"})), \
                 patch("src.main.AzureClient", FakeClient), \
                 patch("src.main.Publisher") as publisher:
                main()
                resolver = publisher.return_value.repair_format.call_args.kwargs["resolve"]
                commit = resolver(f"org:repo-id:{sha}")
            self.assertEqual(commit.project_name, "Payment API")
            self.assertEqual(commit.repository_name, "payment-service")
            self.assertEqual(commit.message, "feat: original")

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
