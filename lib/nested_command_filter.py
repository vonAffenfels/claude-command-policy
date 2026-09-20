"""NestedCommandFilter: `{"type": "nestedCommand"}`, replacing the
`evaluateNamedValueAsCommand` entry key (design decision, leaf
20260914-213652 planning, 2026-09-16).

Deliberately NOT constructed via `Filter.from_definition` and NOT a
`Filter{Matcher, Action}` - like `PathsFilter`, it is its own filter kind
(see filter.py's module docstring on why PathsFilter stands apart), and its
`matches()` needs more than a `ParsedResult`: it needs a way to re-enter the
decision pipeline for each published sub-command, and how deep it is
already nested. `allowed_command_policy.py` is the one caller that has both,
so it calls this filter with its own extended signature rather than through
the uniform `Filter.matches(parsed)` entry point.

Fails CLOSED (does not match/pass) when the parser published nothing to
check (Flag List A3/D6) - there is no "safety belt" special-casing left to
remember, because failing to match is just what an ordinary filter with
nothing to evaluate does. Depth-guarded on two levels: the filter's own
`maxDepth` when configured, else the pipeline's ambient default - both
compared against the CALLER-supplied `depth` so recursion depth is always
an explicit, threaded parameter, never hidden state.
"""

from __future__ import annotations


class NestedCommandFilter:
    def __init__(self, max_depth=None):
        self._max_depth = max_depth

    @classmethod
    def from_definition(cls, definition):
        return cls(max_depth=definition.get("maxDepth"))

    def matches(self, parsed, evaluate_nested, depth, default_max_depth):
        nested = parsed.nested_commands
        if not nested:
            return False

        effective_max_depth = self._max_depth if self._max_depth is not None else default_max_depth
        if depth >= effective_max_depth:
            return False

        return all(evaluate_nested(entry.text, depth + 1).is_allow for entry in nested)

    def explain(self):
        return "nestedCommand filter requiring every published sub-command to itself be allowed"

    def derive_alternative(self):
        return "a wrapper invocation whose own sub-command is independently allowed"
