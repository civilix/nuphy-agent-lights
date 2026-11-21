#!/bin/sh
set -eu
umask 077
repo=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
out="$repo/dist"
mkdir -p "$out"
work=$(mktemp -d "$out/.build.XXXXXX")
trap 'rm -rf "$work"' EXIT
name=NuPhy-Agent-Lights-macOS-arm64
app="$work/$name"
mkdir -p "$app/payload"
"$repo/scripts/build-bridge.sh" "$app/payload"
archive=cpython-3.12.16%2B20261110-aarch64-apple-darwin-install_only_stripped.tar.gz
url="https://github.com/astral-sh/python-build-standalone/releases/download/20261110/$archive"
curl -fsSL --retry 2 "$url" -o "$work/python.tgz"
(cd "$work" && echo '2f11b8aa3726bdbd87dd9eb76568412faddf4f47e26913fa45d6a2e424972acd  python.tgz' | shasum -a 256 -c -)
tar -xzf "$work/python.tgz" -C "$app/payload"
cp "$repo"/agent_lights.py "$repo"/keyboard.py "$repo"/lifecycle.py "$repo"/hook_config.py "$repo"/scripts/lights "$app/payload/"
cp "$repo/scripts/install.command" "$repo/README.md" "$app/"
COPYFILE_DISABLE=1 tar -czf "$work/package.tar.gz" -C "$work" "$name"
mv "$work/package.tar.gz" "$out/$name.tar.gz"
(cd "$out" && shasum -a 256 "$name.tar.gz" > "$name.tar.gz.sha256")
echo "$out/$name.tar.gz"
