"""PathsFilter: matches against a ParsedResult's detected filtering paths.

Deliberately NOT a Filter{Matcher, Action} - its 'exactly'-match-over-a-list
semantics has no block/required action concept at all, so it stays its own
value object outside that composition (see filter.py's module docstring).

`exactly` entries are normalized to absolute form ONCE, at construction, via
the injected PathResolutionContext - `matches()` itself performs no
filesystem or cwd read, unlike today's PathsFilter which re-normalized on
every call.
"""

from __future__ import annotations


class PathsFilter:
    def __init__(self, exactly):
        self._exactly = frozenset(exactly)

    @classmethod
    def from_definition(cls, definition, path_resolution):
        exactly = definition.get("exactly", [])
        if isinstance(exactly, str):
            exactly = [exactly]
        return cls(path_resolution.absolute_path_of(entry) for entry in exactly)

    def matches(self, parsed):
        paths = parsed.paths_for_filtering
        if not paths:
            return True
        if not self._exactly:
            return False
        return all(path in self._exactly for path in paths)

    def explain(self):
        return "paths filter restricting which paths this entry allows"

    def derive_alternative(self):
        return "use a path under one of the allowed prefixes"
