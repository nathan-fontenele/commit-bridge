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


def repair_activity_files(root: Path, directory: str, state, resolve, hash_length: int, timezone):
    """Upgrade tracked legacy rows using their original Azure commits, then fix line breaks."""
    activity_root = (root / directory).resolve()
    entries_by_file = {}
    for key, entry in state["synced"].items():
        try:
            organization, repository_id, sha = key.rsplit(":", 2)
            relative = Path(entry["file"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Invalid state entry: {key}") from exc
        if not organization or not repository_id or len(sha) != 40 or any(
                char not in "0123456789abcdef" for char in sha):
            raise ValueError(f"Invalid state key: {key}")
        path = (root / relative).resolve()
        if not path.is_relative_to(activity_root) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}\.md", path.name):
            raise ValueError(f"Invalid activity file in state: {relative}")
        entries_by_file.setdefault(path, []).append((key, sha))

    updates = {}
    paths = set(entries_by_file)
    if activity_root.exists():
        paths.update(path.resolve() for path in activity_root.rglob("*.md")
                     if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", path.name))
    for path in sorted(paths):
        if not path.is_file():
            raise ValueError(f"Missing activity file referenced by state: {path}")
        original = path.read_text(encoding="utf-8")
        rows = [row.rstrip() for row in original.splitlines() if row.strip()]
        for key, sha in entries_by_file.get(path, []):
            short_sha = sha[:hash_length]
            old = [index for index, row in enumerate(rows) if row.endswith(f" - {short_sha}")]
            new = [index for index, row in enumerate(rows) if row.endswith(f"[{short_sha}]")]
            if len(old) + len(new) != 1:
                raise ValueError(f"Could not uniquely locate saved commit {key} in {path}")
            if old:
                commit = resolve(key)
                if commit.key != key:
                    raise ValueError(f"Azure commit identity differs from saved state: {key}")
                rows[old[0]] = activity_line(commit, hash_length, timezone)
        updated = "".join(f"{row}  \n" for row in rows)
        if updated != original:
            updates[path] = updated
    for path, content in updates.items():
        path.write_text(content, encoding="utf-8")
    return list(updates)
