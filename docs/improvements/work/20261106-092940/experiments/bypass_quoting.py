"""Measures how bypass_transform's joined-text re-analysis treats quoted arguments.
Run from the repository root: bypass-policy python3 docs/improvements/work/20261106-092940/experiments/bypass_quoting.py
"""

import sys

sys.path.insert(0, "lib")
from config import Config

config = Config.from_dict({"allowedCommands": ["echo"], "blockedCommands": ["rm"]})
for command in [
    'bypass-policy echo "some long text"',
    'bypass-policy echo "a; rm x"',
    'bypass-policy echo "a > /etc/foo"',
    'echo "a; rm x"',
]:
    decision = config.decision_for(command)
    print(repr(command), "->", decision.decision)
