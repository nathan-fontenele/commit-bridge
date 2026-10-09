import unittest
from datetime import datetime, timezone

from src.commit_filter import normalize, unique_sorted


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.earliest = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.raw = {
            "commitId": "a" * 40,
            "author": {"email": "Me@Example.com"},
            "committer": {"date": "2026-10-07T15:00:00Z"},
            "comment": "feat: original first line\nmore detail",
        }
        self.kwargs = dict(organization_id="org", project_id="project-id", project_name="Payment API",
                           repository_id="repo-id", emails={"me@example.com"}, earliest=self.earliest)

    def test_author_date_message_and_identity(self):
        commit = normalize(self.raw, **self.kwargs)
        self.assertEqual(commit.message, "feat: original first line")
        self.assertEqual(commit.key, f"org:repo-id:{'a' * 40}")
        self.assertIsNone(normalize({**self.raw, "author": {"email": "other@example.com"}}, **self.kwargs))
        self.assertIsNone(normalize({**self.raw, "committer": {"date": "2026-09-30T00:00:00Z"}}, **self.kwargs))

    def test_duplicate_branch_result_is_one_event(self):
        commit = normalize(self.raw, **self.kwargs)
        other = normalize({**self.raw, "commitId": "b" * 40,
                           "committer": {"date": "2026-10-08T00:00:00Z"}}, **self.kwargs)
        self.assertEqual(unique_sorted([other, commit, commit]), [commit, other])
