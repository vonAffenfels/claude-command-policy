#!/usr/bin/env python3
"""Test fixture: a describe contract breach - the response is valid JSON but
is missing the required `optionsWithValues` key."""

import json
import sys

payload = json.loads(sys.stdin.read())

if payload.get("describe"):
    print(json.dumps({"publishesNestedCommands": False, "namedValues": []}))
else:
    print(json.dumps({"named": {}}))
