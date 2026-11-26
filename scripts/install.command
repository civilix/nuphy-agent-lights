#!/bin/sh
set -eu
umask 077
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" != 1 ] || [ "$(/usr/bin/sw_vers -productVersion | cut -d. -f1)" -lt 13 ]; then
    echo '需要 Apple Silicon Mac 和 macOS 13 或更高版本。' >&2
    exit 1
fi
src=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
payload=${1:-"$src/payload"}
exec "$payload/python/bin/python3" -EsB - "$payload" <<'PY'
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

payload = Path(sys.argv[1])
data = Path.home() / "Library/Application Support/NuPhy Agent Lights"
versions = data / "versions"
versions.mkdir(parents=True, exist_ok=True)
# Identical payloads share a release. Keep prior releases for active controllers.
digest = hashlib.sha256()
for entry in sorted(payload.rglob("*")):
    digest.update(os.fsencode(entry.relative_to(payload)) + b"\0")
    if entry.is_symlink():
        digest.update(os.fsencode(os.readlink(entry)))
    elif entry.is_file():
        with entry.open("rb") as stream:
            content = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                content.update(block)
            digest.update(content.digest())
release = versions / digest.hexdigest()[:24]
with (data / "install.lock").open("a") as lock, tempfile.TemporaryDirectory(dir=data) as tmp:
    fcntl.flock(lock, fcntl.LOCK_EX)
    stage = Path(tmp)
    if not release.exists():
        shutil.copytree(payload, stage / "app", symlinks=True)
        (stage / "app").rename(release)
    (stage / "current").symlink_to(release.relative_to(data))
    # The hook commands always use current/lights. Validate and merge settings
    # with the new release before replacing a working installation.
    subprocess.run([release / "lights", "install"], check=True)
    os.replace(stage / "current", data / "current")
print("已安装。请在 Codex 的 /hooks 或 Settings → Hooks 审阅灯控命令，然后开启新的本地会话。")
print(f'查看状态用 "{data}/current/lights" status，卸载 hook 用 uninstall。')
PY
