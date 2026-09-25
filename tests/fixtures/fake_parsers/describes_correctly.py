#!/usr/bin/env python3
"""Test fixture: answers the describe protocol correctly, and otherwise
behaves like echoes_named_value.py."""

import json
import sys

payload = json.loads(sys.stdin.read())

if payload.get("describe"):
    print(
        json.dumps(
            {
                "publishesNestedCommands": True,
                "namedValues": ["echoed"],
                "optionsWithValues": ["-m"],
            }
        )
    )
else:
    arguments = payload.get("arguments", [])
    print(json.dumps({"named": {"echoed": arguments[0] if arguments else None}}))
