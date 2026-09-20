#!/usr/bin/env python3
"""Probe: does a PreToolUse-forced `ask` survive bypassPermissions / an allow rule?

Forces `ask` on any Bash command containing the sentinel, and logs EVERY
invocation. The log is what distinguishes "the hook fired and its ask was
overridden" from "the hook never fired at all" - two results that look
identical if you only check whether the command ran.
"""

import datetime
import json
import pathlib
import sys

SENTINEL = "PROBEASK7731"
LOG = pathlib.Path(__file__).parent / "hook-invocations.log"


def log(message):
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with LOG.open("a") as handle:
        handle.write(f"{stamp} {message}\n")


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log(f"FIRED but stdin was not JSON: {raw[:200]!r}")
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if SENTINEL not in command:
        log(f"FIRED, no sentinel, abstaining: {command[:120]!r}")
        return 0

    log(f"FIRED, sentinel present, returning ask: {command[:120]!r}")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": (
                "PROBE: forced ask. If this command ran without a dialog, "
                "the forced ask was overridden."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
