"""SensitivePath: one literal path text that vetoes any command mentioning it.

Matching (deliberately over-matching substring containment against any
literal in the command) is the pipeline leaf's job (20260914-213652); this
value object only carries the configured literal and explains itself.
"""

from __future__ import annotations


class SensitivePath:
    def __init__(self, literal):
        self.literal = literal

    @classmethod
    def from_entry(cls, entry):
        return cls(literal=entry)

    def explain(self):
        return f"- {self.literal}: any command mentioning this text is denied."

    def __eq__(self, other):
        if not isinstance(other, SensitivePath):
            return NotImplemented
        return self.literal == other.literal

    def __hash__(self):
        return hash(self.literal)

    def __repr__(self):
        return f"SensitivePath({self.literal!r})"
