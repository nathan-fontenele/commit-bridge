"""Render exactly one activity line per Azure commit."""

from pathlib import Path


def activity_path(root: Path, directory: str, sync_day):
    return root / directory / sync_day.strftime("%Y/%m/%Y-%m-%d.md")


def activity_line(commit, hash_length: int):
    # A commit's first message line is preserved; control characters cannot form a second row.
    project = "".join(char if char.isprintable() else " " for char in commit.project_name)
    message = "".join(char if char.isprintable() else " " for char in commit.message)
    return f"[{project}] {message} - {commit.sha[:hash_length]}"


def append_line(path: Path, line: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if line in existing.splitlines():
        raise ValueError(f"Activity line already exists without state entry: {path}")
    with path.open("a", encoding="utf-8") as output:
        if existing and not existing.endswith("\n"):
            output.write("\n")
        output.write(line + "\n")
