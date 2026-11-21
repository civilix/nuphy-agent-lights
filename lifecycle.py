"""Reduce local coding-agent hooks to one color per product."""
from collections import Counter

PRODUCTS = ("codex", "claude")
PRIORITY = ("idle", "done", "working", "error", "waiting")
LIVE_SECONDS = 4 * 60 * 60
NOTICE_SECONDS = 5
QUESTIONS = {"AskUserQuestion", "ExitPlanMode", "request_user_input", "functions.request_user_input"}
EVENTS = {
    "codex": ("UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "Stop", "SessionEnd", "Interrupt"),
    "claude": ("UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "Stop", "SessionEnd", "PostToolUseFailure", "StopFailure"),
}


def reduce_event(row, product, event, now):
    name = event.get("hook_event_name")
    turn = event.get("turn_id", "") if product == "codex" else ""
    if name not in EVENTS[product] or event.get("agent_id"):
        return row
    if name == "UserPromptSubmit":
        if row and turn and turn == row["turn"]:
            return row
        return dict(turn=turn, state="working", expires=now + LIVE_SECONDS,
                    calls={}, waits={}, uncertain=[])
    if row is None or (turn and row["turn"] and turn != row["turn"]):
        return row
    if name == "SessionEnd":
        return row if row["state"] in ("done", "error") else None
    if row["state"] in ("done", "error"):
        return row
    if name == "Interrupt":
        return None
    if name in ("Stop", "StopFailure"):
        row.update(state="error" if name == "StopFailure" else "done",
                   expires=now + NOTICE_SECONDS, calls={}, waits={}, uncertain=[])
        return row

    tool = event.get("tool_name", "")
    call = event.get("tool_use_id", "")
    if not tool:
        return row
    calls, waits = row["calls"], row["waits"]
    if name == "PreToolUse":
        if call:
            calls[call] = tool
        if tool in waits and call and call not in waits and tool not in row["uncertain"]:
            row["uncertain"].append(tool)
        if tool.split("__")[-1] in QUESTIONS:
            waits[call or tool] = tool
    elif name == "PermissionRequest":
        matches = [key for key, value in calls.items() if value == tool]
        if not call and (len(matches) > 1 or (not matches and tool in waits)):
            if tool not in row["uncertain"]:
                row["uncertain"].append(tool)
        else:
            waits[call or (matches[0] if matches else tool)] = tool
    elif name in ("PostToolUse", "PostToolUseFailure"):
        if call:
            calls.pop(call, None)
            waits.pop(call, None)
        # Older event shapes may provide only the name. Clear a name-only
        # wait when no other matching tool is in flight.
        if tool not in calls.values():
            waits.pop(tool, None)
    row["state"] = "waiting" if waits or row["uncertain"] else "working"
    row["expires"] = now + LIVE_SECONDS
    return row


def summarize(rows):
    counts = {p: Counter() for p in PRODUCTS}
    for product, row in rows:
        counts[product][row["state"]] += 1
    return tuple(next((s for s in reversed(PRIORITY) if counts[p][s]), "idle") for p in PRODUCTS)
