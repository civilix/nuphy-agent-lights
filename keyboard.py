"""Small JSONL client for the version-pinned NuPhy Lab HID bridge."""
import json
import os
import select
import subprocess
import time
from pathlib import Path

from lifecycle import PRIORITY
from effort import DEFAULT_EFFORTS
from pixels import FRAME_SECONDS, PERIMETER, key_frame

DATA = Path.home() / "Library/Application Support/NuPhy Agent Lights"
COLORS = {"idle": "#090909", "working": "#1466C8", "waiting": "#FF8C10",
          "done": "#18AE54", "error": "#EF2842"}


def working_brightness(states, usage):
    percent = max((p for p in usage if p is not None), default=None)
    if max(states, key=PRIORITY.index) == "working" and percent is not None:
        return 15 + (85 * percent + 50) // 100
    return 38


class BridgeError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code


class Keyboard:
    def __init__(self, bridge_path=None):
        self.proc = subprocess.Popen(
            [bridge_path or Path(__file__).resolve().with_name("HIDBridge"), "--backup", DATA / "lighting.json"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0)
        self.buffer = b""
        self.seq = 0
        self.profile = None
        self.previous = None
        self.side_only = False

    def request(self, op, **fields):
        self.seq += 1
        packet = dict(id=self.seq, op=op, **fields)
        self.proc.stdin.write(json.dumps(packet).encode() + b"\n")
        deadline = time.monotonic() + 12
        while True:
            if b"\n" not in self.buffer:
                timeout = max(0, deadline - time.monotonic())
                if not select.select([self.proc.stdout], [], [], timeout)[0]:
                    raise TimeoutError(f"HID bridge timed out during {op}")
                chunk = os.read(self.proc.stdout.fileno(), 32768)
                if not chunk:
                    raise OSError("HID bridge stopped")
                self.buffer += chunk
                continue
            line, self.buffer = self.buffer.split(b"\n", 1)
            reply = json.loads(line)
            if reply.get("id") != self.seq:
                continue
            if not reply.get("ok"):
                error = reply["error"]
                raise BridgeError(error["code"], error["message"])
            return reply["result"]

    def connect(self):
        info = self.request("connect")
        if (info.get("model"), info.get("firmwareVersion"), info.get("protocolReady")) != (
                "Air75 V3 ANSI", "2.0.0.7", True):
            raise RuntimeError("Expected a wired Air75 V3 ANSI 2.0.0.7 with verified protocol")
        self.profile = info["lightingProfile"]
        if info["recoveryPending"]:
            self.restore()
        return info

    def render(self, states, colors=None, brightness=38, efforts=DEFAULT_EFFORTS):
        palette = COLORS if colors is None else colors
        if self.previous is None:
            try:
                self.request("arm")
            except BridgeError as exc:
                if exc.code not in ("AIRLINK_COLOR_RESTORE_UNVERIFIED", "AIRLINK_ORIGINAL_MODE_UNVERIFIED"):
                    raise
                self.side_only = True
        if not self.previous or "working" not in self.previous:
            self.phase = 0
        if not self.side_only:
            self.request("paint", colors=key_frame(states, palette, self.phase, efforts), verify=True)
        self.set_side(states, palette, brightness)
        self.previous = states
        self.efforts = efforts
        self.palette = palette
        self.next_frame = time.monotonic() + FRAME_SECONDS

    def set_side(self, states, palette, brightness):
        color = palette[max(states, key=PRIORITY.index)]
        if self.previous is None or self.side_brightness != brightness or self.side_color != color:
            self.request("side", color=color, brightness=brightness, expectedProfile=self.profile)
            self.side_brightness = brightness
            self.side_color = color

    def animate(self):
        if self.side_only or not self.previous or "working" not in self.previous:
            return
        if time.monotonic() >= self.next_frame:
            self.phase = (self.phase + 1) % len(PERIMETER)
            self.request("paint", colors=key_frame(self.previous, self.palette, self.phase, self.efforts), verify=False)
            self.next_frame = time.monotonic() + FRAME_SECONDS

    def display_for(self, seconds):
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(remaining, FRAME_SECONDS))
            if time.monotonic() < deadline:
                self.animate()

    def restore(self):
        result = self.request("restore", expectedProfile=self.profile)
        if not result.get("verified"):
            raise RuntimeError("HID restoration did not verify")
        self.previous = None
        self.side_only = False
        return result

    def close(self):
        # EOF asks the helper to restore and close, including after an exception.
        try:
            self.proc.stdin.close()
        finally:
            try:
                code = self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
                raise TimeoutError("HID bridge did not exit; check the recovery journal")
            finally:
                self.proc.stdout.close()
        if code:
            raise RuntimeError(f"HID bridge exited with status {code}; check the recovery journal")
