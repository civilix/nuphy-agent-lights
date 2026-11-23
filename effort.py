"""Read reasoning effort and context usage from local client metadata."""
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


def codex_metadata(raw_path, sid, turn):
    path = codex_transcript(raw_path, sid)
    if path:
        try:
            stat = Path(path).stat()
            if S_ISREG(stat.st_mode):
                return _read_metadata(path, turn if isinstance(turn, str) else None, stat.st_size, stat.st_mtime_ns)
        except (OSError, ValueError):
            pass
    return None, None


def context_percent(info):
    last = info.get("last_token_usage")
    used = last.get("total_tokens") if isinstance(last, dict) else None
    window = info.get("model_context_window")
    if type(used) is int and used >= 0 and type(window) is int and window > 0:
        return min(100, (100 * used + window // 2) // window)
    return None


@lru_cache(maxsize=64)
def _read_metadata(path, turn, size, mtime_ns):
    # Read a bounded tail, then cache only the effort and percentage.
    with open(path, "rb") as stream:
        start = max(0, size - 1024 * 1024)
        stream.seek(max(0, start - 1))
        if start and stream.read(1) != b"\n":
            stream.readline(size - start)
        lines = stream.read(max(0, size - stream.tell())).splitlines()
    level = percent = None
    # Forward order lets compaction invalidate the previous context estimate.
    markers = (b'"turn_context"', b'"token_count"', b'"compacted"')
    for line in lines:
        if not any(marker in line[:240] for marker in markers):
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("type")
        event = record.get("payload")
        if kind == "compacted":
            percent = None
        elif isinstance(event, dict):
            if kind == "turn_context" and turn and event.get("turn_id") == turn:
                level = known_level(event.get("effort"))
            elif kind == "event_msg" and event.get("type") == "token_count":
                info = event.get("info")
                if isinstance(info, dict):  # Some events only update rate limits.
                    percent = context_percent(info)
    return level, percent


def turn_effort(raw_path, sid, turn):
    return codex_metadata(raw_path, sid, turn)[0]
