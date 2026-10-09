"""Persist the deduplication index alongside each Markdown change."""

import json
from pathlib import Path


def load_state(path: Path):
    if not path.exists():
        return {"version": 1, "synced": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != 1 or not isinstance(state.get("synced"), dict):
        raise ValueError(f"Unsupported state file: {path}")
    return state


def save_state(path: Path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
