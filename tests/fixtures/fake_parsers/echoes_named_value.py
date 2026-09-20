#!/usr/bin/env python3
"""Test fixture: echoes its first argument back as a named value."""

import json
import sys

payload = json.loads(sys.stdin.read())
arguments = payload.get("arguments", [])
print(json.dumps({"named": {"echoed": arguments[0] if arguments else None}}))
