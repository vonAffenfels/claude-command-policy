"""Action: the block/required inversion, today duplicated identically across
eight of the nine filter classes, now in exactly one place.

Composes with a Matcher's three-state MatchOutcome: TARGET_ABSENT always
fails the filter regardless of action kind (fail-closed), MATCHED/NOT_MATCHED
invert under `block` and pass through under `required`.

An action value other than block/required (default) raises `ConfigError`
(leaf 20260914-213652) rather than silently coercing to `block` the way
today's engine does for every one of its nine filter implementations - a
typo'd action ('blcok') must not silently turn a restriction into a no-op
that widens the allowlist (`test_unknown_filter_action_is_rejected_at_
config_load_time`). This mirrors `Filter.from_definition`'s own ConfigError
for an unrecognised filter type; deliberately no `.filter_type`/`.pattern`
attributes are set on this exception, since only the uncompilable-pattern
case degrades to a warning (see allowed_command_policy.py) - an unrecognised
action must propagate and fail config load outright.
"""

from __future__ import annotations

from config import ConfigError
from match_outcome import MatchOutcome

_REQUIRED = "required"
_BLOCK = "block"


class Action:
    def __init__(self, kind):
        self._kind = kind

    @classmethod
    def from_definition(cls, definition):
        kind = definition.get("action", _BLOCK)
        if kind not in (_REQUIRED, _BLOCK):
            raise ConfigError(f"unrecognised filter action {kind!r} (expected 'block' or 'required')")
        return cls(kind)

    @property
    def is_required(self):
        return self._kind == _REQUIRED

    def applies_to(self, outcome):
        if outcome is MatchOutcome.TARGET_ABSENT:
            return False

        matched = outcome is MatchOutcome.MATCHED
        return matched if self.is_required else not matched

    def explain(self):
        return self._kind

    def __eq__(self, other):
        if not isinstance(other, Action):
            return NotImplemented
        return self._kind == other._kind

    def __hash__(self):
        return hash(self._kind)

    def __repr__(self):
        return f"Action({self._kind!r})"
