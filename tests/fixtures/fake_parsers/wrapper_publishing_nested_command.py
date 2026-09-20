#!/usr/bin/env python3
"""Test fixture: a wrapper-style parser used by test_allowed_command_policy.py.

Recognises a leading `--dry-run` as its own option; publishes every
remaining argument, joined verbatim (flags and all), as ONE nested command
on the `nestedCommands` channel - so a case can still exercise the entry's
own filters (optionPresent on `--dry-run`) and the nested-command filter's
recursion from the exact same fixture script.
"""

import json
import sys

payload = json.loads(sys.stdin.read())
arguments = payload.get("arguments", [])

options = []
remainder = list(arguments)
if remainder and remainder[0] == "--dry-run":
    options.append({"name": "--dry-run", "arguments": []})
    remainder = remainder[1:]

result = {
    "options": options,
    "positionals": [{"index": i, "value": v} for i, v in enumerate(remainder)],
}
if remainder:
    result["nestedCommands"] = [{"text": " ".join(remainder), "shape": "shell"}]

print(json.dumps(result))
