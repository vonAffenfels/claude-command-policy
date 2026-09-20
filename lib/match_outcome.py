"""MatchOutcome: the three-state result a Matcher produces.

Four of today's eight action-bearing filters short-circuit to 'filter fails'
BEFORE the action is applied when their target is absent (an out-of-bounds
index, a missing named value, a missing option) - that is NOT the same as
`matched = False`. A naive boolean composition inverts those four filters'
outcome under a `block` action. TARGET_ABSENT is therefore a distinct third
state that Action always treats as 'filter fails', regardless of action kind.
"""

from __future__ import annotations

import enum


class MatchOutcome(enum.Enum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    TARGET_ABSENT = "target_absent"
