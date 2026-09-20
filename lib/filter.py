"""Filter: a Matcher bound to an Action, replacing create_filter's dict-of-
classes dispatch with a single named constructor.

`Filter.matches(parsed)` is `action.applies_to(matcher.match(parsed))` -
never a boolean composition, because the Matcher's three-state MatchOutcome
(see match_outcome.py) has a TARGET_ABSENT case that must fail the filter
regardless of action.

An uncompilable regex pattern is rejected HERE, at construction, rather than
swallowed at match time into a fail-open `matched = False` the way today's
`except re.error` does. Reuses `config.ConfigError` - `Config.from_dict`
deliberately never raises it (see config.py's docstring); filter/parser
shape validation is this leaf's job.
"""

from __future__ import annotations

import re

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
from action import Action

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
    def from_definition(cls, definition):
        filter_type = definition.get("type", "")
        build_matcher = _PATTERN_MATCHER_BY_TYPE.get(filter_type)
        if build_matcher is None:
            raise ConfigError(f"unknown filter type {filter_type!r}")

        try:
            matcher = build_matcher(definition)
        except re.error as exc:
            error = ConfigError(
                f"{filter_type} filter pattern {definition.get('pattern', '')!r} does not compile: {exc}"
            )
            error.filter_type = filter_type
            error.pattern = definition.get("pattern", "")
            raise error from exc

        return cls(matcher, Action.from_definition(definition))

    @classmethod
    def try_from_definition(cls, definition):
        """Like `from_definition`, but degrades an uncompilable regex
        PATTERN into an always-failing stand-in instead of raising - the
        inherited leaf 20260914-213502 obligation (an uncompilable filter
        fails closed at match time rather than crashing config load).

        Returns `(filter, uncompilable_facts)`: `uncompilable_facts` is None
        on success, or `(filter_type, pattern)` when degraded - the caller
        (never this class) decides what a Warning about it should say, since
        which layer/program it came from is not this class's concern. Any
        OTHER `ConfigError` (an unknown type or action) still raises; only a
        pattern-compile failure degrades.
        """
        try:
            return cls.from_definition(definition), None
        except ConfigError as exc:
            if hasattr(exc, "filter_type"):
                return UncompilableFilter(), (exc.filter_type, exc.pattern)
            raise

    def matches(self, parsed):
        return self._action.applies_to(self._matcher.match(parsed))

    def explain(self):
        return self._matcher.explain(self._action)

    def derive_alternative(self):
        return self._matcher.derive_alternative(self._action)


class UncompilableFilter:
    """Stand-in for a filter whose pattern failed to compile - always fails
    closed, so the entry can never vouch through it
    (`test_a_filter_that_cannot_be_evaluated_fails_closed_at_match_time`)."""

    def matches(self, parsed):
        return False
