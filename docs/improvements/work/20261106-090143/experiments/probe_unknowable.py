"""Probe: which commands carrying $VAR / $(...) the live user config allows.

Run from the worktree root: python3 docs/improvements/work/20261106-090143/experiments/probe_unknowable.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "lib"))
from config import Config  # noqa: E402

with open(os.path.expanduser("~/.claude/command-policy.json")) as handle:
    config = Config.from_dict(json.load(handle))

for command in [
    "grep $(echo pat) README.md",
    "grep $HOME README.md",
    'grep "$(echo pat)" README.md',
    "rg $(echo pat) README.md",
    "rg pat README.md",
    "echo $(echo hi)",
    "chmod $(echo 755) bin/explain-policy",
    'git commit -m "$(echo msg)"',
    "spawn-claude $(echo name)",
]:
    decision = config.decision_for(command)
    print(command, "->", decision.decision, decision.reason)
