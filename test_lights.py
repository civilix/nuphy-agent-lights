import tempfile
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_lights as app
from hook_config import merge
from lifecycle import reduce_event, summarize


class LightsTests(unittest.TestCase):
    def test_effort_follows_the_current_turn_and_handles_late_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DATA", Path(tmp)), \
                patch.object(app, "start_worker"), patch.object(app, "client_pid", return_value=None), \
                patch.dict(os.environ, {"CODEX_HOME": tmp, "CLAUDE_EFFORT": ""}):
            sessions = Path(tmp) / "sessions"
            sessions.mkdir()
            log = sessions / "rollout-date-one.jsonl"
            def context(turn, level):
                return json.dumps(dict(type="turn_context", payload=dict(turn_id=turn, effort=level))) + "\n"
            log.write_text(context("old", "max"))
            prompt = dict(session_id="one", turn_id="new", hook_event_name="UserPromptSubmit", transcript_path=str(log))
            app.apply_hook("codex", prompt)
            with app.database() as db:
                self.assertEqual(app.snapshot(db, with_efforts=True, refresh=True)[1], (None, None))
            with log.open("a") as stream:
                stream.write(context("new", "xhigh"))
            app.apply_hook("claude", dict(prompt, effort={"level": "low"}))
            app.apply_hook("claude", dict(prompt, session_id="two", effort={"level": "high"}))
            app.apply_hook("claude", dict(prompt, agent_id="child", effort={"level": "max"}))
            with app.database() as db:
                self.assertEqual(app.snapshot(db, with_efforts=True, refresh=True)[1], ("xhigh", "high"))
                db.commit()
            app.apply_hook("claude", dict(prompt, session_id="two", hook_event_name="Stop"))
            app.apply_hook("codex", dict(prompt, turn_id="next"))
            with app.database() as db:
                self.assertEqual(app.snapshot(db, with_efforts=True, refresh=True)[1], (None, "low"))

    def test_waits_and_concurrent_products(self):
        def step(row, name, tool="", call="", **extra):
            return reduce_event(row, "codex", dict(hook_event_name=name, tool_name=tool,
                                                    tool_use_id=call, **extra), 100)
        codex = step(None, "UserPromptSubmit", turn_id="one")
        for tool, call in [("Bash", "a"), ("Edit", "b")]:
            step(codex, "PreToolUse", tool, call)
            step(codex, "PermissionRequest", tool)
        step(codex, "PostToolUse", "Bash", "a")
        step(codex, "Stop", turn_id="older")
        self.assertEqual(codex["state"], "waiting")
        claude = reduce_event(None, "claude", {"hook_event_name": "UserPromptSubmit"}, 100)
        reduce_event(claude, "claude", {"hook_event_name": "Stop"}, 101)
        self.assertEqual(summarize([("claude", claude), ("codex", codex)]), ("waiting", "done"))
        step(codex, "PostToolUse", "Edit", "b")
        self.assertEqual(codex["state"], "working")
        self.assertIsNone(step(codex, "Interrupt"))

    def test_ambiguous_and_async(self):
        row = reduce_event(None, "codex", dict(hook_event_name="UserPromptSubmit"), 0)
        for event, call in [("PreToolUse", "1"), ("PreToolUse", "2"), ("PermissionRequest", ""),
                            ("PostToolUse", "1"), ("PostToolUse", "2")]:
            reduce_event(row, "codex", dict(hook_event_name=event, tool_name="Bash", tool_use_id=call), 1)
        self.assertEqual(row["state"], "waiting")
        row = reduce_event(None, "codex", dict(hook_event_name="UserPromptSubmit"), 1)
        reduce_event(row, "codex", dict(hook_event_name="PreToolUse", tool_name="request_user_input_async"), 2)
        self.assertEqual(row["state"], "working")

    def test_config_preserves_others_and_is_idempotent(self):
        orig = {"model": "example", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}
        for product in ("codex", "claude"):
            installed = merge(orig, product, "our-hook", True)
            self.assertEqual(merge(installed, product, "our-hook", True), installed)
            self.assertEqual(merge(installed, product, "our-hook", False), orig)
            self.assertEqual(orig["hooks"]["Stop"][0]["hooks"][0]["command"], "other")

    def test_exited_cli_releases_waiting_session(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DATA", Path(tmp)), patch.object(app, "start_worker"), patch.object(app, "client_pid", return_value=123):
            app.apply_hook("claude", dict(hook_event_name="UserPromptSubmit", session_id="one"))
            with app.database() as db, patch.object(app.os, "kill", side_effect=ProcessLookupError):
                self.assertEqual(app.snapshot(db, retire_exited=True), ("idle", "idle"))
                self.assertEqual(db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)

    def test_session_isolation_cleanup_and_late_return(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DATA", Path(tmp)), patch.object(app, "start_worker"):
            event = dict(hook_event_name="UserPromptSubmit", session_id="shared")
            app.apply_hook("claude", event.copy())
            app.apply_hook("codex", event.copy())
            event.update(hook_event_name="StopFailure")
            app.apply_hook("claude", event)
            event.update(hook_event_name="PostToolUse", tool_name="Edit")
            app.apply_hook("claude", event)
            with app.database() as db:
                self.assertEqual(app.snapshot(db), ("working", "error"))
                db.execute("UPDATE sessions SET expires=0 WHERE product='claude'")
                db.commit()
                self.assertEqual(app.snapshot(db), ("working", "idle"))


if __name__ == "__main__":
    unittest.main()
