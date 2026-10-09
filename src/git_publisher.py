"""Publish one atomic Markdown/state commit for each source commit."""

import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .markdown_writer import activity_line, activity_path, append_line
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

    def git(self, *args, check=True):
        result = subprocess.run(["git", *args], cwd=self.root, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and result.returncode:
            raise RuntimeError(f"git {args[0]} failed with status {result.returncode}")
        return result

    def refresh(self):
        self.git("fetch", "origin", self.branch)
        # Only local commits created by this publisher can be discarded here.
        self.git("reset", "--hard", f"origin/{self.branch}")

    def publish(self, commit):
        for attempt in range(3):
            state = load_state(self.state_path)
            if commit.key in state["synced"]:
                return False
            now = datetime.now(self.timezone)
            path = activity_path(self.root, self.output_dir, now.date())
            append_line(path, activity_line(commit, self.hash_length))
            state["synced"][commit.key] = {
                "synced_at": now.isoformat(timespec="seconds"),
                "file": path.relative_to(self.root).as_posix(),
            }
            save_state(self.state_path, state)
            self.git("add", "--", str(path.relative_to(self.root)), "state/synced_commits.json")
            self.git("commit", "-m", f"sync: [{commit.project_name}] {commit.message.splitlines()[0]}")
            pushed = self.git("push", "origin", f"HEAD:{self.branch}", check=False)
            if pushed.returncode == 0:
                return True
            LOG.warning("Push failed (attempt %s)", attempt + 1)
            # Fetch the authoritative remote state. If the push actually succeeded,
            # the state entry will be present and the next loop will skip it.
            if attempt < 2:
                time.sleep(2**attempt)
                self.refresh()
        raise RuntimeError("Could not publish a source commit after three attempts")
