"""Publish one atomic Markdown/state commit for each source commit."""

import logging
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
        for attempt in range(3):
            state = load_state(self.state_path)
            if commit.key in state["synced"]:
                return False
            now = datetime.now(self.timezone)
            path = activity_path(self.root, self.output_dir, now.date())
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
            self.git("commit", "-m", line)
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
