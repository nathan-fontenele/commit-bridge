"""Publish one atomic Markdown/state commit for each source commit."""

import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .markdown_writer import (activity_line, activity_path, activity_row, append_line,
                              normalize_activity_files, repair_activity_files)
from .state_manager import load_state, save_state


LOG = logging.getLogger(__name__)


class Publisher:
    def __init__(self, root: Path, *, branch: str, email: str, name: str, output_dir: str,
                 hash_length: int, timezone: str):
        self.root = root
        self.branch = branch
        self.output_dir = output_dir
        self.hash_length = hash_length
        self.timezone = ZoneInfo(timezone)
        self.state_path = root / "state/synced_commits.json"
        self.git("config", "user.email", email)
        self.git("config", "user.name", name)
        if self.git("status", "--porcelain").stdout.strip():
            raise RuntimeError("The checkout must be clean before publishing")
        self.refresh()

    def git(self, *args, check=True, env=None):
        result = subprocess.run(["git", *args], cwd=self.root, text=True, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and result.returncode:
            raise RuntimeError(f"git {args[0]} failed with status {result.returncode}")
        return result

    def refresh(self):
        self.git("fetch", "origin", self.branch)
        # Only local commits created by this publisher can be discarded here.
        self.git("reset", "--hard", f"origin/{self.branch}")

    def repair_format(self, resolve=None):
        """Publish one maintenance commit only when legacy Markdown actually changes."""
        for attempt in range(3):
            if resolve:
                changed = repair_activity_files(self.root, self.output_dir,
                                                load_state(self.state_path), resolve,
                                                self.hash_length, self.timezone)
            else:
                changed = normalize_activity_files(self.root / self.output_dir)
            if not changed:
                return False
            self.git("add", "--", *(str(path.relative_to(self.root)) for path in changed))
            self.git("commit", "-m", "chore: format activity Markdown")
            pushed = self.git("push", "origin", f"HEAD:{self.branch}", check=False)
            if pushed.returncode == 0:
                return True
            LOG.warning("Format repair push failed (attempt %s)", attempt + 1)
            if attempt < 2:
                time.sleep(2**attempt)
                self.refresh()
        raise RuntimeError("Could not publish Markdown format repair after three attempts")

    def publish(self, commit):
        return self.publish_batch([commit]) > 0

    def publish_batch(self, commits):
        """Create one local commit per source commit, then push them together.

        Pushing per batch keeps backfills of hundreds of commits from hammering the remote.
        """
        for attempt in range(3):
            state = load_state(self.state_path)
            pending = [commit for commit in commits if commit.key not in state["synced"]]
            if not pending:
                return 0
            for commit in pending:
                self.commit_locally(commit)
            pushed = self.git("push", "origin", f"HEAD:{self.branch}", check=False)
            if pushed.returncode == 0:
                return len(pending)
            reason = [line.strip() for line in pushed.stderr.splitlines()
                      if line.lstrip().startswith(("!", "error:", "remote:", "fatal:"))]
            LOG.warning("Push failed (attempt %s): %s", attempt + 1, " / ".join(reason[:3]) or "no details")
            # Fetch the authoritative remote state. If the push actually succeeded,
            # the state entries will be present and the next loop will skip them.
            if attempt < 2:
                time.sleep(2**(attempt + 1))
                self.refresh()
        raise RuntimeError("Could not publish source commits after three attempts")

    def commit_locally(self, commit):
        state = load_state(self.state_path)
        now = datetime.now(self.timezone)
        # File and Git dates follow the original Azure commit, so backfills land on their real day.
        committed_at = commit.committed_at.astimezone(self.timezone)
        path = activity_path(self.root, self.output_dir, committed_at.date())
        repaired = normalize_activity_files(self.root / self.output_dir)
        line = activity_line(commit, self.hash_length, self.timezone)
        append_line(path, activity_row(commit, self.hash_length, self.timezone))
        state["synced"][commit.key] = {
            "synced_at": now.isoformat(timespec="seconds"),
            "file": path.relative_to(self.root).as_posix(),
        }
        save_state(self.state_path, state)
        changed_paths = {str(changed.relative_to(self.root)) for changed in [*repaired, path]}
        self.git("add", "--", *sorted(changed_paths), "state/synced_commits.json")
        date = committed_at.isoformat(timespec="seconds")
        self.git("commit", "-m", line,
                 env={**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
