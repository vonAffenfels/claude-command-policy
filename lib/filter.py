"""Filter: a Matcher bound to an Action, replacing create_filter's dict-of-
classes dispatch with a single named constructor. Also the single dispatch
point for the two filter kinds that are not a Matcher+Action composition at
all (`paths` -> PathsFilter, `nestedCommand` -> NestedCommandFilter) - moved
here from AllowedCommandPolicy's own `_filter_passes` string dispatch, so
every filter TYPE is resolved in one place regardless of shape.

`Filter.matches(parsed)` is `action.applies_to(matcher.match(parsed))` -
never a boolean composition, because the Matcher's three-state MatchOutcome
(see match_outcome.py) has a TARGET_ABSENT case that must fail the filter
regardless of action.

`from_definition` never raises: every defect (an unknown type, an
uncompilable pattern, an unrecognised action) degrades to an `InvalidFilter`
carrying human-readable `problems` - a generalisation of the old engine's
UncompilableFilter, which handled only the pattern case. `InvalidFilter`
always fails closed, so the entry it belongs to can never vouch through it;
`AllowedCommand.problems()` is what surfaces the `problems` text to a config
author (see allowed_command.py). Lower-level constructors this delegates to
(`Action.from_definition`, `re.compile`) may still raise - this is the one
place those defects are caught and converted, not left to propagate to
`decision_for`.
"""

from __future__ import annotations

import re

from action import Action
from config import ConfigError
from matcher import (
    ArgumentAtIndexMatcher,
    MatchFullParameterMatcher,
    NamedValueMatcher,
    OptionPresentMatcher,
    OptionValueMatcher,
    ParameterRegexMatcher,
    PositionalArgAtIndexMatcher,
    PositionalArgRegexMatcher,
)
from nested_command_filter import NestedCommandFilter
from paths_filter import PathsFilter

_PATTERN_MATCHER_BY_TYPE = {
    "parameterRegex": lambda d: ParameterRegexMatcher(pattern=d.get("pattern", "")),
    "matchFullParameter": lambda d: MatchFullParameterMatcher(pattern=d.get("pattern", "")),
    "positionalArgRegex": lambda d: PositionalArgRegexMatcher(pattern=d.get("pattern", "")),
    "argumentAtIndex": lambda d: ArgumentAtIndexMatcher(index=d.get("index", 0), pattern=d.get("pattern", "")),
    "positionalArgAtIndex": lambda d: PositionalArgAtIndexMatcher(
        index=d.get("index", 0), pattern=d.get("pattern", "")
    ),
    "namedValue": lambda d: NamedValueMatcher(name=d.get("name", ""), pattern=d.get("pattern", "")),
    "optionValue": lambda d: OptionValueMatcher(option=d.get("option", ""), pattern=d.get("pattern", "")),
    "optionPresent": lambda d: OptionPresentMatcher(option=d.get("option", "")),
}


class Filter:
    def __init__(self, matcher, action):
        self._matcher = matcher
        self._action = action

    @classmethod
    def from_definition(cls, definition, path_resolution=None):
        filter_type = definition.get("type", "")

        if filter_type == "paths":
            return PathsFilter.from_definition(definition, path_resolution)
        if filter_type == "nestedCommand":
            return NestedCommandFilter.from_definition(definition)

        build_matcher = _PATTERN_MATCHER_BY_TYPE.get(filter_type)
        if build_matcher is None:
            return InvalidFilter((f"unknown filter type {filter_type!r}",))

        try:
            matcher = build_matcher(definition)
        except re.error as exc:
            pattern = definition.get("pattern", "")
            return InvalidFilter((f"{filter_type} filter pattern {pattern!r} does not compile: {exc}",))

        try:
            action = Action.from_definition(definition)
        except ConfigError as exc:
            return InvalidFilter((str(exc),))

        return cls(matcher, action)

    def matches(self, parsed):
        return self._action.applies_to(self._matcher.match(parsed))

    def explain(self):
        return self._matcher.explain(self._action)

    def derive_alternative(self):
        return self._matcher.derive_alternative(self._action)


class InvalidFilter:
    """Stand-in for any filter definition `from_definition` could not build
    - an unknown type, an uncompilable pattern, or an unrecognised action.
    Always fails closed, so the entry it belongs to can never vouch through
    it (`test_a_filter_that_cannot_be_evaluated_fails_closed_at_match_time`).
    `problems` is a tuple of human-readable strings, surfaced through
    `AllowedCommand.problems()`."""

    def __init__(self, problems):
        self.problems = tuple(problems)

    def matches(self, parsed):
        return False
