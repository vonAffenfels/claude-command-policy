"""RedirectOperator: shfmt's integer redirect-operator token, named.

A redirect's `Op` in shfmt's JSON AST is an integer, never a string, and no
mapping for it exists anywhere else in the repo. It is not a dedicated
redirect-operator enum either - it is a sparse slice of ONE shared token
space spanning mvdan/sh's entire grammar (pipe '|'=13, a case-pattern
terminator=35, extglob '!('=143, ...). This value object provides an
explicit finite mapping over the 12 values verified live against shfmt 3.13.1
covering every standard bash redirect form.

An Op integer outside that table is not an error: it retains the raw integer
for diagnostics rather than raising or silently mapping to a lossy 'unknown'
sentinel - mirroring Statement's own UnrecognizedCmd fail-visible philosophy
of never silently dropping information.
"""

from __future__ import annotations

_SYMBOL_BY_OP = {
    63: ">",
    64: ">>",
    65: "<",
    66: "<>",
    67: "<&",
    68: ">&",
    69: ">|",
    71: "<<",
    72: "<<-",
    73: "<<<",
    74: "&>",
    76: "&>>",
}


class RedirectOperator:
    def __init__(self, op, symbol):
        self.op = op
        self.symbol = symbol

    @classmethod
    def from_op(cls, op):
        return cls(op, _SYMBOL_BY_OP.get(op))

    @property
    def is_recognized(self):
        return self.symbol is not None

    def explain(self):
        if self.symbol is not None:
            return f"{self.symbol} (Op={self.op})"
        return f"<unrecognized redirect Op={self.op}>"

    def __eq__(self, other):
        if not isinstance(other, RedirectOperator):
            return NotImplemented
        return self.op == other.op

    def __hash__(self):
        return hash(self.op)

    def __repr__(self):
        return f"RedirectOperator(op={self.op!r}, symbol={self.symbol!r})"
