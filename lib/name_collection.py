"""The three plain-name veto/allow collections: blockedCommands,
sensitiveVariables and additionalAllowedPathPrefixes.

All three share one shape - an ordered collection of literal names that
UNIONS across config layers, never narrows - so they share a NameCollection
base and differ only in their domain identity and what their explain() header
says.
"""

from __future__ import annotations


class NameCollection:
    _label = "names"

    def __init__(self, names):
        self.names = tuple(names)

    @classmethod
    def from_entries(cls, entries):
        return cls(entries or ())

    def union(self, other):
        return type(self)(self.names + other.names)

    def explain(self):
        if not self.names:
            return f"{self._label}: (none configured)"
        return f"{self._label}: {', '.join(self.names)}"

    def __eq__(self, other):
        if not isinstance(other, NameCollection) or type(other) is not type(self):
            return NotImplemented
        return self.names == other.names

    def __hash__(self):
        return hash((type(self), self.names))

    def __repr__(self):
        return f"{type(self).__name__}({self.names!r})"


class BlockedCommands(NameCollection):
    """Programs that are denied outright, overriding any allowedCommands entry."""

    _label = "blockedCommands"


class SensitiveVariables(NameCollection):
    """Variable names that are denied outright wherever referenced."""

    _label = "sensitiveVariables"


class AllowedPathPrefixes(NameCollection):
    """Filesystem path prefixes permitted beyond CLAUDE_PROJECT_DIR."""

    _label = "additionalAllowedPathPrefixes"
