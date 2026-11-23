"""Merge the two clients' user-level JSON hook configurations."""
import copy
import json
import os
import shutil
import tempfile
from pathlib import Path

from lifecycle import EVENTS


STATUS_COMMAND = '"$HOME/Library/Application Support/NuPhy Agent Lights/current/lights" claude-statusline'
PIPE_PREFIX = STATUS_COMMAND + " --passthrough | (\n"


def merge_statusline(settings, install):
    line = settings.get("statusLine")
    if "statusLine" not in settings and install:
        settings["statusLine"] = {"type": "command", "command": STATUS_COMMAND}
    elif isinstance(line, dict) and line.get("type") == "command":
        command = line.get("command")
        if command == STATUS_COMMAND:
            if not install:
                del settings["statusLine"]
        elif isinstance(command, str) and command:
            wrapped = command.startswith(PIPE_PREFIX) and command.endswith("\n)")
            if install and not wrapped:
                line["command"] = PIPE_PREFIX + command + "\n)"
            elif wrapped and not install:
                line["command"] = command[len(PIPE_PREFIX):-2]


def merge(original, product, command, install):
    result = copy.deepcopy(original)
    hooks = result.setdefault("hooks", {})
    for event in EVENTS[product]:
        groups = hooks.get(event, [])
        remaining = []
        for group in groups:
            handlers = group.get("hooks", [])
            keep = [h for h in handlers if h.get("command") != command or h.get("type") != "command"]
            if keep == handlers:
                remaining.append(group)
            elif keep:
                remaining.append(dict(group, hooks=keep))
        if install:
            remaining.append({"hooks": [{"type": "command", "command": command, "timeout": 3}]})
        if remaining:
            hooks[event] = remaining
        elif event in hooks:
            del hooks[event]
    if not hooks and "hooks" not in original:
        del result["hooks"]
    if product == "claude":
        merge_statusline(result, install)
    return result


def configure(install, data):
    paths = {
        "codex": Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json",
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json",
    }
    edits = []
    for product, path in paths.items():
        path = path.expanduser().resolve()
        command = f'"$HOME/Library/Application Support/NuPhy Agent Lights/current/lights" hook {product}'
        raw = path.read_bytes() if path.exists() else None
        original = json.loads(raw) if raw is not None else {}
        result = merge(original, product, command, install)
        if result != original:
            edits.append((path, raw, result))
    for path, raw, result in edits:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (path.read_bytes() if path.exists() else None) != raw:
            raise RuntimeError(f"Concurrent settings change: {path}. Run the command again.")
        if raw is not None:
            backups = data / "hook-backups"
            backups.mkdir(parents=True, mode=0o700, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=path.name + ".", dir=backups, delete=False) as backup:
                backup.write(raw)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as out:
            json.dump(result, out, indent=2, ensure_ascii=False)
            out.write("\n")
        if raw is not None:
            shutil.copymode(path, out.name)
        os.replace(out.name, path)
        print(f"Updated {path}")
