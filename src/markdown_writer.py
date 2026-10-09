"""Render one Markdown table row per original Azure commit."""

from pathlib import Path
import re

TABLE_HEADER = "| Data e hora (Brasília) | Projeto | Repositório Azure | Mensagem | Hash |"
TABLE_SEPARATOR = "| --- | --- | --- | --- | --- |"
LEGACY_BRACKET = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{2}:\d{2})\] "
    r"\[(.*?)\] \[(.*?)\] \[(.*)\] \[([0-9a-fA-F]{1,40})\]$")
LEGACY_PLAIN = re.compile(r"^\[(.*?)\] (.*) - ([0-9a-fA-F]{1,40})$")
TABLE_HASH = re.compile(r"\| ([0-9a-fA-F]{1,40}) \|$")


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


def table_cell(value: str):
    printable = "".join(char if char.isprintable() else " " for char in value)
    return printable.replace("\\", "\\\\").replace("|", "\\|")


def table_row(date: str, project: str, repository: str, message: str, sha: str):
    return "| " + " | ".join(table_cell(value) for value in
                             (date, project, repository, message, sha)) + " |"


def activity_row(commit, hash_length: int, timezone):
    local_time = commit.committed_at.astimezone(timezone)
    committed_at = local_time.strftime("%Y-%m-%d %H:%M:%S %z")
    committed_at = committed_at[:-2] + ":" + committed_at[-2:]
    return table_row(committed_at, commit.project_name, commit.repository_name,
                     commit.message, commit.sha[:hash_length])


def legacy_row(line: str):
    bracket = LEGACY_BRACKET.fullmatch(line)
    if bracket:
        return table_row(*bracket.groups())
    plain = LEGACY_PLAIN.fullmatch(line)
    if plain:
        project, message, sha = plain.groups()
        return table_row("—", project, "—", message, sha)
    raise ValueError("Unrecognized activity record in daily Markdown")


def read_rows(content: str):
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if not lines:
        return []
    if lines[:2] == [TABLE_HEADER, TABLE_SEPARATOR]:
        rows = lines[2:]
        if any(not row.startswith("| ") or not TABLE_HASH.search(row) for row in rows):
            raise ValueError("Malformed activity table")
        return rows
    return [legacy_row(line) for line in lines]


def render_table(rows):
    if not rows:
        return ""
    return "\n".join((TABLE_HEADER, TABLE_SEPARATOR, *rows)) + "\n"


def append_line(path: Path, line: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    rows = read_rows(existing)
    if line in rows:
        raise ValueError(f"Activity line already exists without state entry: {path}")
    path.write_text(render_table([*rows, line]), encoding="utf-8")


def normalize_activity_files(directory: Path):
    """Convert legacy daily files to tables alongside a real source commit."""
    changed = []
    if not directory.exists():
        return changed
    for path in directory.rglob("*.md"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", path.name):
            continue
        original = path.read_text(encoding="utf-8")
        normalized = render_table(read_rows(original))
        if normalized != original:
            path.write_text(normalized, encoding="utf-8")
            changed.append(path)
    return changed


def repair_activity_files(root: Path, directory: str, state, resolve, hash_length: int, timezone):
    """Convert daily files to tables and fill missing fields from saved Azure commits."""
    activity_root = (root / directory).resolve()
    entries_by_file = {}
    for key, entry in state["synced"].items():
        try:
            organization, repository_id, sha = key.rsplit(":", 2)
            relative = Path(entry["file"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Invalid state entry") from exc
        if not organization or not repository_id or len(sha) != 40 or any(
                char not in "0123456789abcdef" for char in sha):
            raise ValueError("Invalid state key")
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
        rows = read_rows(original)
        for key, sha in entries_by_file.get(path, []):
            short_sha = sha[:hash_length]
            matches = [index for index, row in enumerate(rows)
                       if row.endswith(f"| {short_sha} |")]
            if len(matches) != 1:
                raise ValueError(f"Could not uniquely locate a saved commit in {path}")
            index = matches[0]
            if rows[index].startswith("| — |"):
                commit = resolve(key)
                if commit.key != key:
                    raise ValueError("Azure commit identity differs from saved state")
                rows[index] = activity_row(commit, hash_length, timezone)
        if any(row.startswith("| — |") for row in rows):
            raise ValueError(f"Activity file has rows without matching state entries: {path}")
        updated = render_table(rows)
        if updated != original:
            updates[path] = updated
    for path, content in updates.items():
        path.write_text(content, encoding="utf-8")
    return list(updates)
