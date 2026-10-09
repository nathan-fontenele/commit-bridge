"""Validate, normalize, and order original Azure commits."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Commit:
    organization_id: str
    project_id: str
    project_name: str
    repository_id: str
    sha: str
    message: str
    author_email: str
    committed_at: datetime

    @property
    def key(self):
        return f"{self.organization_id}:{self.repository_id}:{self.sha}"


def normalize(raw, *, organization_id, project_id, project_name, repository_id, emails, earliest):
    sha = raw.get("commitId", "").lower()
    email = raw.get("author", {}).get("email", "").strip().casefold()
    date_text = raw.get("committer", {}).get("date", "")
    if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
        return None
    if email not in emails or not date_text:
        return None
    try:
        committed_at = datetime.fromisoformat(date_text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
    if committed_at < earliest:
        return None
    message = raw.get("comment", "").splitlines()
    if not message or not message[0]:
        return None
    return Commit(organization_id, project_id, project_name, repository_id, sha,
                  message[0], email, committed_at)


def unique_sorted(commits):
    by_key = {commit.key: commit for commit in commits}
    return sorted(by_key.values(), key=lambda commit: (commit.committed_at, commit.key))
