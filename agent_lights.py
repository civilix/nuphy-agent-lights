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

from keyboard import DATA, Keyboard
from lifecycle import EVENTS, PRODUCTS, reduce_event, summarize
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


def snapshot(db, retire_exited=False):
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
        active.append((product, row))
    return summarize(active)


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
    if not isinstance(sid, str) or not sid or event.get("hook_event_name") not in EVENTS[product]:
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


def worker(fd):
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    board = None
    next_health = 0
    with database() as db, os.fdopen(fd, "a") as owner:
        try:
            while not stopping:
                states = snapshot(db)
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
                    elif board.previous != states:
                        board.render(states)
                        hardware_status(mode="side" if board.side_only else "keys+side",
                                        codex=states[0], claude=states[1])
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
        for states, seconds in [(("working", "working"), 6), (("working", "waiting"), 2),
                                (("done", "waiting"), 2)]:
            board.render(states)
            print(states, "side" if board.side_only else "keys+side", "verified", flush=True)
            board.display_for(seconds)
        result = board.restore()
        print("restore:", result.get("verification", "side"), "verified", flush=True)


def main():
    os.umask(0o077)
    cli = argparse.ArgumentParser(description=__doc__)
    subs = cli.add_subparsers(dest="action", required=True)
    subs.add_parser("hook").add_argument("product", choices=PRODUCTS)
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
    elif args.action == "_worker":
        worker(args.fd)
    elif args.action in ("install", "uninstall"):
        from hook_config import configure
        if args.action == "install" and not SCRIPT.with_name("HIDBridge").is_file():
            cli.error("Run install.command from the Apple Silicon package")
        configure(args.action == "install", DATA)
        if args.action == "uninstall":
            with database() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM sessions")
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
            start_worker()
            db.commit()
        print("Active indicators cleared. Check status for verified restoration.")
    else:
        with database() as db:
            status = DATA / "hardware.json"
            print(json.dumps(dict(sessions=dict(zip(PRODUCTS, snapshot(db))),
                                  last_hooks={p: dict(event=e, at=t) for p, e, t in db.execute(
                                      "SELECT product,event,received FROM receipts")},
                                  last_hardware=json.loads(status.read_text()) if status.exists() else None,
                                  recovery_records=[p.name for p in DATA.glob("lighting.profile-*.json")]), indent=2))


if __name__ == "__main__":
    main()
