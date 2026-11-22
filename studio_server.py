"""Open the Signal Studio page with a loopback-only physical keyboard test."""
import errno
import json
import os
import re
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import agent_lights
from keyboard import COLORS, DATA

ROOT = Path(__file__).resolve().parent
ASSETS = {"": ("index.html", "text/html; charset=utf-8"),
          "pixels.js": ("pixels.js", "text/javascript"),
          "studio.css": ("studio.css", "text/css"),
          "studio.js": ("studio.js", "text/javascript")}


def validate(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("配置版本无效")
    states = (data.get("codex"), data.get("claude"))
    colors = data.get("colors")
    brightness = data.get("brightness")
    if not all(isinstance(s, str) and s in COLORS for s in states):
        raise ValueError("状态无效")
    if not isinstance(colors, dict) or not all(
        isinstance(colors.get(s), str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", colors[s]) for s in COLORS
    ):
        raise ValueError("状态颜色无效")
    if type(brightness) is not int or not 0 <= brightness <= 100:
        raise ValueError("亮度必须为 0 到 100 的整数")
    return states, colors, brightness


def test_profile(data):
    states, colors, brightness = validate(data)
    if states == agent_lights.IDLE:
        raise ValueError("两个状态都为空闲时使用原灯效。请选择至少一个活动状态再测试。")
    bridge = ROOT / "HIDBridge"
    if not bridge.is_file():
        bridge = DATA / "current/HIDBridge"
    if not bridge.is_file():
        raise ValueError("未找到 HIDBridge，请先安装本项目的 macOS 安装包。")
    with agent_lights.test_keyboard(bridge) as (board, _):
        board.render(states, colors, brightness)
        board.display_for(3)
        side_only = board.side_only
        board.restore()
        return "侧灯测试完成，已验证恢复原灯效。" if side_only else "按键与侧灯测试完成，已验证恢复原灯效。"


class Handler(BaseHTTPRequestHandler):
    def log_request(self, *args):
        pass

    def reply(self, status, mime, content):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        asset = ASSETS.get(self.path[1:]) if self.path.startswith("/") else None
        if not asset or self.headers.get("Host") != self.server.authority:
            self.send_error(404)
            return
        name, mime = asset
        self.reply(200, mime, (ROOT / "studio/dist" / name).read_bytes())

    def do_POST(self):
        if (self.path != "/test" or self.headers.get("Host") != self.server.authority
                or self.headers.get("Origin") != "http://" + self.server.authority
                or self.headers.get("X-Studio-Session") != self.server.ticket):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 8192 or self.headers.get_content_type() != "application/json":
                raise ValueError("无效的配置请求")
            message = test_profile(json.loads(self.rfile.read(length)))
            status = 200
        except ValueError as exc:
            status, message = 400, str(exc)
        except (OSError, RuntimeError) as exc:
            status, message = 409, str(exc)
        self.reply(status, "application/json", json.dumps({"message": message}).encode())


def serve():
    os.umask(0o077)
    # A stable origin keeps browser profiles across launches.
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with httpd as server:
        # Let in-flight restore finish if the user stops the launcher during a test.
        server.daemon_threads = False
        server.authority = f"127.0.0.1:{server.server_port}"
        server.ticket = secrets.token_urlsafe(32)
        url = f"http://{server.authority}/#session={server.ticket}"
        print("打开本机工作台（Ctrl+C 关闭）", url, flush=True)
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    serve()
