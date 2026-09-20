"""PermissionDecision: the pipeline's output, replacing AnalysisResult.

Kept deliberately SIMPLE per the trunk's scope correction: a `{decision,
reason}` container only. Leaf 20260915-010959 owns the RICH deny+hint
reason text (near-miss derivation, the equivalence-search skill pointer);
this leaf's reasons only need to be non-empty and locate the fired rule.
`decision` is one of allow/deny/ask/passthrough - this leaf produces only
allow/deny (ask/passthrough are leaf 7's escalation-policy outcomes), but
the vocabulary is defined here since it is this container's whole domain.
"""

from __future__ import annotations

_ALLOW = "allow"
_DENY = "deny"
_ASK = "ask"
_PASSTHROUGH = "passthrough"


class PermissionDecision:
    def __init__(self, decision, reason=None):
        self.decision = decision
        self.reason = reason

    @classmethod
    def allow(cls):
        return cls(_ALLOW, None)

    @classmethod
    def deny(cls, reason):
        return cls(_DENY, reason)

    @classmethod
    def ask(cls, reason=None):
        return cls(_ASK, reason)

    @classmethod
    def passthrough(cls, reason=None):
        return cls(_PASSTHROUGH, reason)

    @property
    def is_allow(self):
        return self.decision == _ALLOW

    def __eq__(self, other):
        if not isinstance(other, PermissionDecision):
            return NotImplemented
        return self.decision == other.decision and self.reason == other.reason

    def __repr__(self):
        return f"PermissionDecision(decision={self.decision!r}, reason={self.reason!r})"
