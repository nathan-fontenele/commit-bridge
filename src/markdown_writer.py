"""Render exactly one activity line per Azure commit."""

from pathlib import Path
import re


def activity_path(root: Path, directory: str, sync_day):
    return root / directory / sync_day.strftime("%Y/%m/%Y-%m-%d.md")


def activity_line(commit, hash_length: int, timezone):
    # A commit's first message line is preserved; control characters cannot form a second row.
    project = "".join(char if char.isprintable() else " " for char in commit.project_name)
    repository = "".join(char if char.isprintable() else " " for char in commit.repository_name)
    message = "".join(char if char.isprintable() else " " for char in commit.message)
    local_time = commit.committed_at.astimezone(timezone)
    committed_at = local_time.strftime("%Y-%m-%d %H:%M:%S")
    utc_offset = local_time.strftime("%z")
    offset = f"{utc_offset[:3]}:{utc_offset[3:]}"
    return (f"[{committed_at} {offset}] [{project}] [{repository}] "
            f"[{message}] [{commit.sha[:hash_length]}]")


def append_line(path: Path, line: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    records = [record.rstrip() for record in existing if record.strip()]
    if line in records:
        raise ValueError(f"Activity line already exists without state entry: {path}")
    # Two trailing spaces turn a source newline into a visible break on GitHub.
    # Re-render earlier entries in this day's file while adding the next real commit.
    path.write_text("".join(f"{record}  \n" for record in [*records, line]), encoding="utf-8")


def normalize_activity_files(directory: Path):
    """Repair legacy daily files only when a new source commit will be published."""
    changed = []
    if not directory.exists():
        return changed
    for path in directory.rglob("*.md"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", path.name):
            continue
        original = path.read_text(encoding="utf-8")
        records = [record.rstrip() for record in original.splitlines() if record.strip()]
        normalized = "".join(f"{record}  \n" for record in records)
        if normalized != original:
            path.write_text(normalized, encoding="utf-8")
            changed.append(path)
    return changed
