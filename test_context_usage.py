import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import agent_lights as app
from effort import codex_metadata
from hook_config import merge
from keyboard import COLORS, Keyboard, working_brightness


class ContextTests(unittest.TestCase):
    def test_codex_uses_latest_request_and_resets_on_compaction(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CODEX_HOME": tmp}):
            folder = Path(tmp) / "sessions"
            folder.mkdir()
            path = folder / "rollout-date-one.jsonl"
            def append(used, window):
                info = dict(last_token_usage=dict(total_tokens=used), model_context_window=window,
                            total_token_usage=dict(total_tokens=999999))
                with path.open("a") as out:
                    print(json.dumps(dict(type="event_msg", payload=dict(type="token_count", info=info))), file=out)
            path.write_text("x" * 1100000 + "\n")
            append(84, 100)
            self.assertEqual(codex_metadata(str(path), "one", "new"), (None, 84))
            self.assertEqual(codex_metadata(str(path), "other", "new"), (None, None))
            with path.open("a") as out:
                print('{"type":"compacted","payload":{}}', file=out)
            self.assertEqual(codex_metadata(str(path), "one", "new")[1], None)
            append(20, 200)
            self.assertEqual(codex_metadata(str(path), "one", "new")[1], 10)
            append(8, 0)
            self.assertIsNone(codex_metadata(str(path), "one", "new")[1])

    def test_statusline_is_scoped_to_active_sessions_and_can_drop(self):
        def report(sid, value):
            raw = json.dumps(dict(session_id=sid, context_window=dict(used_percentage=value))).encode()
            app.claude_statusline(io.BytesIO(raw), False)
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DATA", Path(tmp)), \
                patch.object(app, "client_pid", return_value=None), patch.object(app, "start_worker"):
            prompt = dict(session_id="a", hook_event_name="UserPromptSubmit")
            report("unused", 100)
            report("a", 85)
            app.apply_hook("claude", prompt)
            app.apply_hook("claude", dict(prompt, session_id="b"))
            report("b", 60)
            with app.database() as db:
                self.assertEqual(app.snapshot(db, with_context=True)[2], (None, 85))
                report("a", 10)
                self.assertEqual(app.snapshot(db, with_context=True)[2], (None, 60))
                app.apply_hook("claude", dict(prompt, session_id="b", hook_event_name="Stop"))
                self.assertEqual(app.snapshot(db, with_context=True)[2], (None, 10))
                report("a", None)
                self.assertEqual(app.snapshot(db, with_context=True)[2], (None, None))

    def test_usage_only_changes_side_and_higher_priority_notices_take_over(self):
        states = ("working", "working")
        board = Keyboard.__new__(Keyboard)
        board.previous, board.profile, board.side_only = None, 1, False
        board.request = Mock()
        board.render(states, brightness=working_brightness(states, (None, None)))
        for usage, brightness in [((0, None), 15), ((10, 50), 58), ((100, 50), 100)]:
            board.request.reset_mock()
            board.set_side(states, COLORS, working_brightness(states, usage))
            board.set_side(states, COLORS, working_brightness(states, usage))
            board.request.assert_called_once_with("side", color=COLORS["working"], brightness=brightness,
                                                  expectedProfile=1)
        for state in ("waiting", "error"):
            states = ("working", state)
            board.render(states, brightness=working_brightness(states, (100, None)))
            board.request.assert_called_with("side", color=COLORS[state], brightness=38, expectedProfile=1)

    def test_statusline_install_and_uninstall_preserve_existing_command(self):
        original = {"statusLine": {"type": "command", "command": "cat\n# comment", "padding": 3}}
        installed = merge(original, "claude", "hook", True)
        self.assertEqual(installed["statusLine"]["padding"], 3)
        self.assertEqual(merge(installed, "claude", "hook", True), installed)
        self.assertEqual(merge(installed, "claude", "hook", False)["statusLine"], original["statusLine"])
