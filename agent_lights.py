#!/usr/bin/env python3
"""Hook entry point, controller and local diagnostics for NuPhy Agent Lights."""
import argparse
import contextlib
import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from keyboard import DATA, Keyboard, working_brightness
from effort import LEVELS, codex_metadata, codex_transcript, known_level
from lifecycle import EVENTS, LIVE_SECONDS, PRODUCTS, reduce_event, summarize
from pixels import FRAME_SECONDS

SCRIPT = Path(__file__).resolve()
IDLE = ("idle", "idle")


@contextlib.contextmanager
def database():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(DATA / "sessions.sqlite", timeout=2)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS sessions(product, sid, expires REAL, state TEXT, PRIMARY KEY(product,sid))")
        db.execute("CREATE TABLE IF NOT EXISTS receipts(product PRIMARY KEY, event, received REAL)")
        db.execute("CREATE TABLE IF NOT EXISTS claude_context(sid TEXT PRIMARY KEY, percent INTEGER, updated REAL)")
        yield db
    finally:
        db.close()


def client_pid(product):
    # Walk executable names only. Prompts and tool arguments may be in argv.
    pid = os.getppid()
    names = {"codex"} if product == "codex" else {"claude", "claude.exe"}
    for _ in range(12):
        if pid <= 1:
            break
        out = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "ppid=,comm="],
                             capture_output=True, text=True).stdout.strip().split(None, 1)
        if len(out) != 2:
            break
        if Path(out[1]).name in names:
            return pid
        pid = int(out[0])
    return None


def snapshot(db, retire_exited=False, with_efforts=False, refresh=False, with_context=False):
    rows = db.execute("SELECT product,sid,state FROM sessions WHERE expires>?", (time.time(),)).fetchall()
    active = []
    for product, sid, raw in rows:
        row = json.loads(raw)
        if row.get("client_pid") and row["state"] in ("working", "waiting"):
            try:
                os.kill(row["client_pid"], 0)
            except (ProcessLookupError, PermissionError):
                if retire_exited:
                    db.execute("DELETE FROM sessions WHERE product=? AND sid=? AND state=?", (product, sid, raw))
                continue
        if refresh and product == "codex" and row["state"] == "working":
            previous = row.copy()
            level, percent = codex_metadata(row.get("transcript"), sid, row.get("turn"))
            if level:
                row["effort"] = level
            row["context_percent"] = percent
            if previous != row:
                db.execute("UPDATE sessions SET state=? WHERE product=? AND sid=? AND state=?",
                           (json.dumps(row), product, sid, raw))
        if with_context and product == "claude" and row["state"] == "working":
            value = db.execute("SELECT percent FROM claude_context WHERE sid=? AND updated>?",
                               (sid, time.time() - LIVE_SECONDS)).fetchone()
            row["context_percent"] = value[0] if value else None
        active.append((product, row))
    states = summarize(active)
    if not (with_efforts or with_context):
        return states
    efforts = []
    for product, state in zip(PRODUCTS, states):
        levels = [row["effort"] for p, row in active if p == product and state == row["state"] == "working"
                  and known_level(row.get("effort"))]
        efforts.append(max(levels, key=LEVELS.index, default=None))
    if with_context:
        usage = tuple(max((row["context_percent"] for p, row in active
                           if p == product and row["state"] == "working" and row.get("context_percent") is not None),
                          default=None) for product in PRODUCTS)
        return states, tuple(efforts), usage
    return states, tuple(efforts)


def hardware_status(**fields):
    with tempfile.NamedTemporaryFile(mode="w", dir=DATA, delete=False) as f:
        json.dump(dict(at=time.time(), **fields), f)
    os.replace(f.name, DATA / "hardware.json")


def owner_lock():
    handle = (DATA / "owner.lock").open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def start_worker(script=SCRIPT):
    handle = owner_lock()
    if handle:
        with handle:
            fd = handle.fileno()
            subprocess.Popen([sys.executable, "-EsB", script, "_worker", str(fd)], pass_fds=(fd,),
                             start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_hook(product, event):
    sid = event.get("session_id")
    if (not isinstance(sid, str) or not sid or event.get("agent_id")
            or event.get("hook_event_name") not in EVENTS[product]):
        return
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
        db.execute("INSERT OR REPLACE INTO receipts VALUES(?,?,?)",
                   (product, event["hook_event_name"], now))
        key = (product, sid)
        record = db.execute("SELECT state FROM sessions WHERE product=? AND sid=?", key).fetchone()
        row = reduce_event(json.loads(record[0]) if record else None, product, event, now)
        if row is not None:
            if row["state"] in ("working", "waiting"):
                if product == "claude":
                    effort = event.get("effort")
                    level = known_level(effort.get("level") if isinstance(effort, dict) else None)
                    level = level or known_level(os.environ.get("CLAUDE_EFFORT"))
                    if level:
                        row["effort"] = level
                elif not row.get("transcript") and (not event.get("turn_id") or event["turn_id"] == row.get("turn")):
                    path = codex_transcript(event.get("transcript_path"), sid)
                    if path:
                        row["transcript"] = path
            if event["hook_event_name"] == "UserPromptSubmit":
                row["client_pid"] = client_pid(product)
            db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)",
                       (*key, row["expires"], json.dumps(row)))
        elif record:
            db.execute("DELETE FROM sessions WHERE product=? AND sid=?", key)
        # The worker also releases its lock in a write transaction. A hook
        # arriving while it retires will either wake it or start a successor.
        if row or record or any(DATA.glob("lighting.profile-*.json")):
            start_worker()
        db.commit()


def claude_statusline(stream, passthrough):
    raw = stream.read()
    if passthrough:
        # The user's original command receives the identical JSON on stdin.
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
    try:
        event = json.loads(raw)
        if not isinstance(event, dict) or not isinstance(event.get("session_id"), str) or not event["session_id"]:
            return
        window = event.get("context_window")
        percent = window.get("used_percentage") if isinstance(window, dict) else None
        if type(percent) not in (int, float) or not 0 <= percent <= 100:
            percent = None
        else:
            percent = round(percent)
        now = time.time()
        with database() as db, db:
            db.execute("DELETE FROM claude_context WHERE updated<=?", (now - LIVE_SECONDS,))
            db.execute("INSERT INTO claude_context VALUES(?,?,?) ON CONFLICT(sid) DO UPDATE "
                       "SET percent=excluded.percent, updated=excluded.updated WHERE updated<=excluded.updated",
                       (event["session_id"], percent, now))
    except (OSError, ValueError, sqlite3.Error):
        pass  # A telemetry failure must not break the user's status line.


def worker(fd):
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    board = None
    next_health = 0
    next_metadata = 0
    with database() as db, os.fdopen(fd, "a") as owner:
        try:
            while not stopping:
                refresh = time.monotonic() >= next_metadata
                with db:
                    states, efforts, usage = snapshot(db, with_context=True, refresh=refresh)
                brightness = working_brightness(states, usage)
                if refresh:
                    next_metadata = time.monotonic() + 1
                pending = any(DATA.glob("lighting.profile-*.json"))
                try:
                    if not board and (pending or states != IDLE):
                        board = Keyboard()
                        board.connect()
                    if states == IDLE:
                        if board:
                            result = board.restore()
                            board.close()
                            board = None
                            if any(DATA.glob("lighting.profile-*.json")):
                                hardware_status(mode="recovery-pending", error="Switch back to the original Mac/Win profile")
                            else:
                                hardware_status(mode="idle", restored=result["verified"])
                        db.execute("BEGIN IMMEDIATE")
                        db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
                        if snapshot(db, retire_exited=True) == IDLE and not any(DATA.glob("lighting.profile-*.json")):
                            owner.close()
                            db.commit()
                            return
                        db.commit()
                        if pending:
                            time.sleep(3)
                    elif board.previous != states or board.efforts != efforts or board.side_brightness != brightness:
                        if board.previous != states or board.efforts != efforts:
                            board.render(states, brightness=brightness, efforts=efforts)
                        else:
                            board.set_side(states, board.palette, brightness)
                            board.animate()
                        hardware_status(mode="side" if board.side_only else "keys+side",
                                        codex=states[0], claude=states[1], effort=dict(zip(PRODUCTS, efforts)),
                                        context_percent=dict(zip(PRODUCTS, usage)), side_brightness=brightness)
                        next_health = time.monotonic() + 5
                    else:
                        if time.monotonic() >= next_health:
                            status = board.request("status")
                            if not status.get("protocolReady") or status.get("lightingProfile") != board.profile:
                                raise RuntimeError("Keyboard disconnected or changed profile")
                            next_health = time.monotonic() + 5
                        board.animate()
                except (OSError, RuntimeError, ValueError) as exc:
                    hardware_status(mode="retry", error=str(exc))
                    if board:
                        with contextlib.suppress(OSError, RuntimeError):
                            board.close()
                        board = None
                    time.sleep(3)
                time.sleep(FRAME_SECONDS if board and not board.side_only and "working" in states else 0.25)
        finally:
            if board:
                board.close()


@contextlib.contextmanager
def test_keyboard(bridge_path=None):
    """Hold the controller lock for a manual test and hand queued hooks back."""
    with database() as db:
        lock = owner_lock()
        if not lock:
            raise RuntimeError("Lights are in use; run the test after active sessions finish")
        with lock:
            try:
                board = Keyboard(bridge_path)
                try:
                    yield board, board.connect()
                finally:
                    board.close()
            finally:
                db.execute("BEGIN IMMEDIATE")
                lock.close()
                if snapshot(db) != IDLE or any(DATA.glob("lighting.profile-*.json")):
                    # A source-checkout studio can borrow the installed bridge.
                    script = bridge_path.with_name("agent_lights.py") if bridge_path else SCRIPT
                    start_worker(script)
                db.commit()


def demo():
    with test_keyboard() as (board, info):
        print(info["model"], info["firmwareVersion"], flush=True)
        samples = [
            (("working", "working"), ("low", "medium"), (10, 25), 2),
            (("working", "working"), ("high", "xhigh"), (90, 70), 6),
            (("working", "waiting"), ("xhigh", None), (90, None), 2),
            (("done", "waiting"), (None, None), (None, None), 2),
        ]
        for states, efforts, usage, seconds in samples:
            brightness = working_brightness(states, usage)
            board.render(states, brightness=brightness, efforts=efforts)
            print(states, efforts, "context", usage, "side brightness", brightness,
                  "side" if board.side_only else "keys+side", "verified", flush=True)
            board.display_for(seconds)
        result = board.restore()
        print("restore:", result.get("verification", "side"), "verified", flush=True)


def main():
    os.umask(0o077)
    cli = argparse.ArgumentParser(description=__doc__)
    subs = cli.add_subparsers(dest="action", required=True)
    subs.add_parser("hook").add_argument("product", choices=PRODUCTS)
    subs.add_parser("claude-statusline").add_argument("--passthrough", action="store_true")
    subs.add_parser("_worker").add_argument("fd", type=int)
    for name in ("install", "uninstall", "demo", "studio", "status", "recover"):
        subs.add_parser(name)
    args = cli.parse_args()
    if args.action == "hook":
        try:
            apply_hook(args.product, json.load(sys.stdin))
        except (ValueError, OSError, sqlite3.Error) as exc:
            print(f"NuPhy light event skipped: {type(exc).__name__}", file=sys.stderr)
        print("{}")
    elif args.action == "claude-statusline":
        claude_statusline(sys.stdin.buffer, args.passthrough)
    elif args.action == "_worker":
        worker(args.fd)
    elif args.action in ("install", "uninstall"):
        from hook_config import configure
        if args.action == "install" and not SCRIPT.with_name("HIDBridge").is_file():
            cli.error("Run ./scripts/install-source.sh from the repository root")
        configure(args.action == "install", DATA)
        if args.action == "uninstall":
            with database() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM sessions")
                db.execute("DELETE FROM claude_context")
                start_worker()
                db.commit()
    elif args.action == "studio":
        from studio_server import serve
        serve()
    elif args.action == "demo":
        demo()
    elif args.action == "recover":
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM claude_context")
            start_worker()
            db.commit()
        print("Active indicators cleared. Check status for verified restoration.")
    else:
        with database() as db:
            status = DATA / "hardware.json"
            states, efforts, usage = snapshot(db, with_context=True, refresh=True)
            print(json.dumps(dict(sessions=dict(zip(PRODUCTS, states)), effort=dict(zip(PRODUCTS, efforts)),
                                  context_percent=dict(zip(PRODUCTS, usage)),
                                  last_hooks={p: dict(event=e, at=t) for p, e, t in db.execute(
                                      "SELECT product,event,received FROM receipts")},
                                  last_hardware=json.loads(status.read_text()) if status.exists() else None,
                                  recovery_records=[p.name for p in DATA.glob("lighting.profile-*.json")]), indent=2))


if __name__ == "__main__":
    main()
