"""PathConfig: the allowedPaths key, isolated behind its own value object.

Path rules share no vocabulary with the bash analyzer (Read/Grep/Glob path
matching vs. command decisions), so they live behind one PathConfig property
of Config rather than mixed into the bash-facing collections. Tool-alias
expansion ("all" -> read/grep/glob) is analyze-path's concern, not
construction's - PathRule stores tools exactly as configured.
"""

from __future__ import annotations


class PathRule:
    def __init__(self, tools, path):
        self.tools = tuple(tools)
        self.path = path

    @classmethod
    def from_entry(cls, entry):
        tools = entry.get("tools", [])
        if isinstance(tools, str):
            tools = [tools]
        return cls(tools=tools, path=entry.get("path"))

    def explain(self):
        return f"- {self.path} (tools: {', '.join(self.tools)})"

    def __eq__(self, other):
        if not isinstance(other, PathRule):
            return NotImplemented
        return self.tools == other.tools and self.path == other.path

    def __hash__(self):
        return hash((self.tools, self.path))

    def __repr__(self):
        return f"PathRule(tools={self.tools!r}, path={self.path!r})"


class PathConfig:
    def __init__(self, rules):
        self.rules = tuple(rules)

    @classmethod
    def from_entries(cls, entries):
        return cls(tuple(PathRule.from_entry(entry) for entry in entries or ()))

    def union(self, other):
        return PathConfig(self.rules + other.rules)

    def explain(self):
        if not self.rules:
            return "allowedPaths: (none configured)"
        lines = ["allowedPaths:"]
        lines.extend(rule.explain() for rule in self.rules)
        return "\n".join(lines)

    def __eq__(self, other):
        if not isinstance(other, PathConfig):
            return NotImplemented
        return self.rules == other.rules

    def __hash__(self):
        return hash(self.rules)

    def __repr__(self):
        return f"PathConfig({self.rules!r})"
