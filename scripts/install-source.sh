#!/bin/sh
# Deploy this checkout with Apple's local toolchain and Python interpreter.
set -eu
umask 077
repo=$(CDPATH= cd -P "$(dirname "$0")/.." && pwd)
if [ "$(/usr/bin/uname -s)" != Darwin ] || [ "$(/usr/sbin/sysctl -n hw.optional.arm64)" != 1 ] ||
   [ "$(/usr/bin/sw_vers -productVersion | cut -d. -f1)" -lt 13 ]; then
    echo '源码部署需要 Apple Silicon Mac 和 macOS 13 或更高版本。' >&2
    exit 1
fi
if ! /usr/bin/xcrun --find swiftc >/dev/null 2>&1 ||
   ! /usr/bin/python3 -EsB -c 'import sqlite3, sys; sys.exit(sys.version_info < (3, 9))'; then
    echo '请安装或更新 Xcode Command Line Tools（xcode-select --install），需要 Swift 和 Python 3.9 或更高版本。' >&2
    exit 1
fi
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/python/bin" "$stage/studio/dist"
ln -s /usr/bin/python3 "$stage/python/bin/python3"
cp "$repo/agent_lights.py" "$repo/keyboard.py" "$repo/pixels.py" "$repo/effort.py" \
   "$repo/lifecycle.py" "$repo/hook_config.py" "$repo/studio_server.py" "$repo/scripts/lights" "$stage/"
for asset in index.html pixels.js studio.css studio.js; do
    cp "$repo/studio/dist/$asset" "$stage/studio/dist/"
done
"$repo/scripts/build-bridge.sh" "$stage"
"$repo/scripts/install.command" "$stage"
