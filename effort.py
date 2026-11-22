"""Read the selected reasoning effort from local client metadata."""
import json
import os
from functools import lru_cache
from pathlib import Path
from stat import S_ISREG

LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
DEFAULT_EFFORTS = (None, None)


def known_level(value):
    return value if isinstance(value, str) and value in LEVELS else None


def codex_transcript(raw_path, sid):
    if not isinstance(raw_path, str) or not raw_path or not sid:
        return None
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        path = Path(raw_path).resolve()
        if path.is_relative_to((root / "sessions").resolve()) and path.name.endswith(f"-{sid}.jsonl"):
            return str(path)
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def turn_effort(raw_path, sid, turn):
    path = codex_transcript(raw_path, sid)
    if not path or not isinstance(turn, str) or not turn:
        return None
    try:
        stat = Path(path).stat()
        if S_ISREG(stat.st_mode):
            return _read_context(path, turn, stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError):
        pass
    return None


@lru_cache(maxsize=64)
def _read_context(path, turn, size, mtime_ns):
    # Include the modification time in the key so a late write triggers a retry.
    try:
        with open(path, "rb") as stream:
            start = max(0, size - 1024 * 1024)
            stream.seek(start)
            lines = stream.read(size - start).splitlines()
        for line in reversed(lines[1:] if start else lines):
            if b'"turn_context"' not in line[:160]:
                continue
            try:
                record = json.loads(line)
            except (UnicodeError, ValueError):
                continue
            if not isinstance(record, dict) or record.get("type") != "turn_context":
                continue
            context = record.get("payload")
            if isinstance(context, dict) and context.get("turn_id") == turn:
                return known_level(context.get("effort"))
    except (OSError, ValueError):
        pass
    return None
