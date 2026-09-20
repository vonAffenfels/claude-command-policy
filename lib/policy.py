"""Policy: the protocol every pass implements.

    map(lambda policy: policy.decision(),
        filter(lambda policy: policy.matches(),
               map(lambda policy: policy.forStatement(self), self.policies)))

`for_statement(statement)` binds a policy to what it evaluates, copy-on-write
(a shallow copy with the statement attached - a policy's own config fields
are never mutated). `matches()` says whether this policy OBJECTS to the
statement; `decision()` is only ever called on a policy that matched, and
`pass_` orders objections against every other policy's.

Every concrete Policy subclass owns its own config-derived construction; this
base only supplies the shared for_statement/binding boilerplate so that
never needs re-deriving per subclass.
"""

from __future__ import annotations

import copy


class Policy:
    pass_ = None

    def __init__(self):
        self._statement = None

    def for_statement(self, statement):
        bound = copy.copy(self)
        bound._statement = statement
        return bound

    @property
    def statement(self):
        return self._statement

    def matches(self):
        raise NotImplementedError

    def decision(self):
        raise NotImplementedError
