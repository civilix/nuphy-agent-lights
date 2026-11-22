import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import agent_lights
import studio_server
from keyboard import BridgeError, COLORS, Keyboard
from pixels import CLAUDE, CODEX, studio_asset


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.profile = dict(version=1, codex="waiting", claude="error", colors=COLORS, brightness=62)

    def test_invalid_profiles_never_open_device(self):
        with patch.object(agent_lights, "test_keyboard") as open_board:
            for change in ({"version": True}, {"codex": ["idle"]}, {"colors": {}},
                           {"colors": dict(COLORS, waiting="red")}, {"brightness": False},
                           {"brightness": 101}, {"codex": "idle", "claude": "idle"}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    studio_server.test_profile(dict(self.profile, **change))
            open_board.assert_not_called()

    def test_manual_render_keeps_default_hook_palette(self):
        board = Keyboard.__new__(Keyboard)
        board.request = Mock()
        board.previous, board.profile, board.side_only = None, 2, False
        colors = dict(COLORS, waiting="#285234")
        board.render(("waiting", "error"), colors, 62)
        paint = board.request.call_args_list[1]
        frame = paint.kwargs["colors"]
        self.assertEqual(len(frame), 84)
        self.assertEqual(frame[:3], [COLORS["idle"], "#285234", COLORS["error"]])
        self.assertEqual((frame[17], frame[21]), (CODEX["color"], CLAUDE["color"]))
        board.request.assert_called_with("side", color="#285234", brightness=62, expectedProfile=2)
        self.assertEqual(COLORS["waiting"], "#FF8C10")

    def test_animation_only_moves_running_products(self):
        board = Keyboard.__new__(Keyboard)
        board.previous, board.profile, board.side_only = None, 2, False
        board.request = Mock()
        with patch("keyboard.time.monotonic", return_value=0) as clock:
            board.render(("waiting", "working"))
            first = board.request.call_args_list[1].kwargs["colors"]
            board.request.reset_mock()
            board.animate()
            board.request.assert_not_called()
            clock.return_value = 1
            board.animate()
            second = board.request.call_args.kwargs["colors"]
            board.request.assert_called_once_with("paint", colors=second, verify=False)
            self.assertEqual({i for i in range(84) if first[i] != second[i]}, {63, 64, 67, 68})
            board.render(("working", "idle"))
            clock.return_value = 2
            board.animate()
            frame = board.request.call_args.kwargs["colors"]
            self.assertEqual(frame[49], COLORS["idle"])
            self.assertNotIn(CLAUDE["color"], frame)
            board.render(("waiting", "done"))
            board.request.reset_mock()
            clock.return_value = 3
            board.animate()
            board.request.assert_not_called()

    def test_side_only_never_writes_animation_frames(self):
        board = Keyboard.__new__(Keyboard)
        board.previous, board.profile, board.side_only = None, 2, False
        board.request = Mock(side_effect=[BridgeError("AIRLINK_COLOR_RESTORE_UNVERIFIED", ""), {}])
        board.render(("working", "working"))
        board.next_frame = 0
        board.animate()
        self.assertEqual([call.args[0] for call in board.request.call_args_list], ["arm", "side"])

    def test_offline_preview_uses_current_sprite_frames(self):
        self.assertEqual((studio_server.ROOT / "studio/dist/pixels.js").read_text(), studio_asset())

    def test_failed_manual_test_releases_device_and_hands_off_queued_hook(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agent_lights, "DATA", Path(tmp)), \
                patch.object(agent_lights, "Keyboard") as keyboard, patch.object(agent_lights, "start_worker") as wake:
            bridge = Path(tmp) / "HIDBridge"
            with self.assertRaises(OSError):
                with agent_lights.test_keyboard(bridge):
                    self.assertIsNone(agent_lights.owner_lock())
                    agent_lights.apply_hook("codex", dict(hook_event_name="UserPromptSubmit", session_id="new"))
                    raise OSError("bridge disconnected")
            keyboard.return_value.close.assert_called_once()
            wake.assert_called_with(bridge.with_name("agent_lights.py"))
            with agent_lights.owner_lock() as released:
                self.assertFalse(released.closed)
