"""SensitivePathsPolicy: Pass 0, the absolute veto.

Matches on a plain substring scan of the command's own raw text rather than
walking the parsed Statement tree: the check is deliberately over-matching
(Flag List D1) and must reach "any literal argument or redirect target
anywhere in the statement, recursing into sub-statements" - the full raw
text already contains everything at every nesting depth, so a substring scan
against it is a strict superset of a tree walk, simpler, and exercised
identically whether this policy binds the top-level command or a
recursively-entered nested/substituted command (each recursion constructs
its own SensitivePathsPolicy against its own command text - see config.py).

Cannot be escalated by anything (leaf 7's bypass-policy still cannot lift
this - see the improvement's Interface section).
"""

from __future__ import annotations

from pass_ import Pass
from permission_decision import PermissionDecision
from policy import Policy
from reason import SensitivePathReferenced


class SensitivePathsPolicy(Policy):
    pass_ = Pass.SENSITIVE_PATHS

    def __init__(self, sensitive_paths, command_text):
        super().__init__()
        self._sensitive_paths = tuple(sensitive_paths)
        self._command_text = command_text

    def _matched(self):
        return sorted(
            {sp.literal for sp in self._sensitive_paths if sp.literal and sp.literal in self._command_text}
        )

    def matches(self):
        return bool(self._matched())

    def decision(self):
        return PermissionDecision.deny(tuple(SensitivePathReferenced(path) for path in self._matched()))
