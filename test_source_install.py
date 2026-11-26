import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(sys.platform == "darwin" and os.uname().machine == "arm64", "Apple Silicon deployment")
class SourceInstallTests(unittest.TestCase):
    def test_upgrade_reinstall_and_failed_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = base / "source checkout"
            for name in ("scripts", "studio"):
                shutil.copytree(ROOT / name, checkout / name)
            for source in ROOT.glob("*.py"):
                shutil.copy2(source, checkout)
            # Exercise deployment without a network request or a hardware build.
            bridge = checkout / "scripts/build-bridge.sh"
            bridge.write_text('#!/bin/sh\nset -eu\nprintf fixture > "$1/HIDBridge"\n')
            data = base / "Library/Application Support/NuPhy Agent Lights"
            old = data / "versions/old-package"
            old.mkdir(parents=True)
            current = data / "current"
            current.symlink_to("versions/old-package")
            codex = base / "codex settings"
            claude = base / "claude settings"
            claude.mkdir()
            config = claude / "settings.json"
            original = {"statusLine": {"type": "command", "command": "cat"}, "language": "Chinese"}
            config.write_text(json.dumps(original))
            env = dict(os.environ, HOME=str(base), CODEX_HOME=str(codex), CLAUDE_CONFIG_DIR=str(claude))

            def install(check=True):
                return subprocess.run([checkout / "scripts/install-source.sh"], env=env, check=check,
                                      capture_output=True, text=True)

            install()
            release = current.resolve()
            self.assertNotEqual(release, old)
            self.assertTrue(old.is_dir())
            self.assertEqual(os.readlink(current / "python/bin/python3"), "/usr/bin/python3")
            self.assertEqual((current / "studio/dist/index.html").read_bytes(),
                             (checkout / "studio/dist/index.html").read_bytes())
            installed = config.read_bytes()
            self.assertIn(b"claude-statusline", installed)
            install()
            self.assertEqual(current.resolve(), release)
            self.assertEqual(config.read_bytes(), installed)
            # A new payload with invalid client settings must leave current usable.
            with (checkout / "pixels.py").open("a") as stream:
                stream.write("\n# updated checkout\n")
            config.write_text("{")
            self.assertNotEqual(install(check=False).returncode, 0)
            self.assertEqual(current.resolve(), release)
            self.assertEqual(config.read_text(), "{")
            config.write_bytes(installed)
            checkout.rename(base / "moved checkout")
            status = subprocess.check_output([current / "lights", "status"], env=env)
            self.assertEqual(json.loads(status)["recovery_records"], [])
            subprocess.run([current / "lights", "uninstall"], env=env, check=True, capture_output=True)
            self.assertEqual(json.loads(config.read_text())["statusLine"], original["statusLine"])
