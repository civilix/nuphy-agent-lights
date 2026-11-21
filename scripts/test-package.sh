#!/bin/sh
# Exercise an install in a fresh home, then remove the unpacked download.
set -eu
archive=${1:?usage: test-package.sh ARCHIVE}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export HOME="$work/New Mac Home"
export CODEX_HOME="$HOME/custom codex"
export CLAUDE_CONFIG_DIR="$HOME/claude settings"
export PATH=/usr/bin:/bin
mkdir -p "$CODEX_HOME" "$CLAUDE_CONFIG_DIR" "$work/Downloads"
echo '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"true"}]}]}}' > "$CODEX_HOME/hooks.json"
echo '{"language":"Chinese"}' > "$CLAUDE_CONFIG_DIR/settings.json"
tar -xzf "$archive" -C "$work/Downloads"
installer="$work/Downloads/NuPhy-Agent-Lights-macOS-arm64/install.command"
"$installer"
"$installer"
mv "$work/Downloads" "$work/moved download"
app="$HOME/Library/Application Support/NuPhy Agent Lights/current"
"$app/lights" status >/dev/null
"$app/python/bin/python3" -EsB - <<'PY'
import json, os, subprocess
from pathlib import Path
root = Path.home() / "Library/Application Support/NuPhy Agent Lights"
assert len(list((root / "versions").iterdir())) == 1
for product, env, filename in [("codex", "CODEX_HOME", "hooks.json"), ("claude", "CLAUDE_CONFIG_DIR", "settings.json")]:
    cfg = json.loads((Path(os.environ[env]) / filename).read_text())
    entries = cfg["hooks"]["SessionEnd"]
    assert len(entries) == 1
    command = entries[0]["hooks"][0]["command"]
    out = subprocess.check_output(command, shell=True, input=b'{"session_id":"test","hook_event_name":"SessionEnd"}')
    assert json.loads(out) == {}
status = json.loads(subprocess.check_output([root / "current/lights", "status"]))
assert all(status["last_hooks"][p]["event"] == "SessionEnd" for p in ("codex", "claude"))
PY
"$app/lights" uninstall
"$app/python/bin/python3" -EsB - <<'PY'
import json, os
from pathlib import Path
codex = json.loads((Path(os.environ["CODEX_HOME"]) / "hooks.json").read_text())
claude = json.loads((Path(os.environ["CLAUDE_CONFIG_DIR"]) / "settings.json").read_text())
assert codex["hooks"] == {"Stop":[{"hooks":[{"type":"command","command":"true"}]}]}
assert claude["language"] == "Chinese" and not claude.get("hooks")
PY
echo 'Portable install, repeated install, relocated download, both hooks and uninstall verified.'
