#!/bin/sh
set -eu
umask 077
dest=${1:?usage: build-bridge.sh OUTPUT_DIRECTORY}
mkdir -p "$dest"
dest=$(cd "$dest" && pwd)
build=$(mktemp -d "$dest/build.XXXXXX")
trap 'rm -rf "$build"' EXIT
base=https://raw.githubusercontent.com/bohu8264/NuPhyLab-next/1f1ae72dad5e61e363860fb34a2df00407b483bb
cd "$build"
curl -fsSL --retry 2 "$base/native/HIDBridge.swift" -o HIDBridge.swift
curl -fsSL --retry 2 "$base/LICENSE" -o NuPhyLab-LICENSE
echo '05c41d75b8002e8f4e72f3d2f25b8fa4da75fd0272285504bfaf6282b3a0548b  HIDBridge.swift' | shasum -a 256 -c -
swiftc -target arm64-apple-macosx13.0 HIDBridge.swift -o HIDBridge -framework IOKit -framework AppKit -framework ApplicationServices
codesign --force --sign - HIDBridge
if ./HIDBridge --self-test >self-test.log 2>&1; then
    tail -1 self-test.log
else
    tail -20 self-test.log >&2
    exit 1
fi
mv NuPhyLab-LICENSE HIDBridge "$dest/"
