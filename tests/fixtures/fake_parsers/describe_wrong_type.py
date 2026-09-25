#!/usr/bin/env python3
"""Test fixture: a describe contract breach - `publishesNestedCommands` is
the string "false" rather than a JSON boolean."""

import json
import sys

payload = json.loads(sys.stdin.read())

if payload.get("describe"):
    print(json.dumps({"publishesNestedCommands": "false", "namedValues": [], "optionsWithValues": []}))
else:
    print(json.dumps({"named": {}}))
