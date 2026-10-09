import unittest
from unittest.mock import patch

from src.azure_client import AzureClient, PAGE_SIZE
from src.main import collect


class ClientTests(unittest.TestCase):
    def test_collect_multiple_projects_and_branches(self):
        class FakeClient:
            def projects(self):
                return [{"id": "p1", "name": "Payment"}, {"id": "p2", "name": "Auth"}]

            def repositories(self, project_id):
                return [{"id": project_id + "-r", "name": "repo"}]

            def branches(self, project_id, repository_id):
                return ["main", "feature"]

            def commits(self, project_id, repository_id, branch, from_date):
                return [{"commitId": ("a" if project_id == "p1" else "b") * 40,
                         "author": {"email": "me@example.com"},
                         "committer": {"date": "2026-10-07T15:00:00Z"},
                         "comment": "real commit"}]

        from datetime import datetime, timezone
        config = {"azure_devops": {"organization": "org"}}
        commits = collect(FakeClient(), config, {"me@example.com"},
                          earliest=datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(len(commits), 2)
        self.assertEqual({commit.project_name for commit in commits}, {"Payment", "Auth"})

    def test_projects_and_refs_follow_continuation(self):
        client = AzureClient("org", "fake")
        with patch.object(client, "get", side_effect=[
            ({"value": [{"id": "one"}]}, {"x-ms-continuationtoken": "next"}),
            ({"value": [{"id": "two"}]}, {}),
        ]) as get:
            self.assertEqual([x["id"] for x in client.projects()], ["one", "two"])
            self.assertEqual(get.call_args_list[1].args[1]["continuationToken"], "next")
        with patch.object(client, "get", side_effect=[
            ({"value": [{"name": "refs/heads/main"}]}, {"x-ms-continuationtoken": "next"}),
            ({"value": [{"name": "refs/heads/feature/x"}]}, {}),
        ]):
            self.assertEqual(list(client.branches("project", "repo")), ["main", "feature/x"])

    def test_commit_pages_advance_skip(self):
        client = AzureClient("org", "fake")
        with patch.object(client, "get", side_effect=[
            ({"value": [{}] * PAGE_SIZE}, {}),
            ({"value": [{}]}, {}),
        ]) as get:
            self.assertEqual(len(list(client.commits("project", "repo", "main", "2026-10-01"))), PAGE_SIZE + 1)
            self.assertEqual(get.call_args_list[1].args[1]["searchCriteria.$skip"], PAGE_SIZE)
