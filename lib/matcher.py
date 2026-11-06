"""Matcher family: what a filter extracts and compares, independent of what
it does with the outcome (that is Action's job - see filter.py).

Eight concrete matchers, one per today's projection+comparison pair. Four of
them (ArgumentAtIndex, PositionalArgAtIndex, NamedValue, OptionValue) can
report MatchOutcome.TARGET_ABSENT when the thing they would compare against
does not exist at all - see match_outcome.py for why that is a third state
rather than NOT_MATCHED. PathsFilter is NOT a Matcher: its 'exactly'-match-
over-a-list semantics has no block/required action at all - see filter.py.

Each matcher renders its own rule line via `explain(action)`: the target it
reads, must / must not, and the pattern verbatim in backticks. Matchers are
value objects: equal when they are the same kind with the same pattern and
target.
"""

from __future__ import annotations

import re

from match_outcome import MatchOutcome


class Matcher:
    type_name = ""

    def __init__(self, pattern=None):
        self._pattern = pattern

    def match(self, parsed):
        raise NotImplementedError

    def explain(self, action):
        raise NotImplementedError

    def _identity(self):
        return (self.type_name, self._pattern)

    def __eq__(self, other):
        if not isinstance(other, Matcher):
            return NotImplemented
        return self._identity() == other._identity()

    def __hash__(self):
        return hash(self._identity())

    def __repr__(self):
        return f"{type(self).__name__}{self._identity()[1:]!r}"


class ParameterRegexMatcher(Matcher):
    """Config: {"type": "parameterRegex", "pattern": "regex"}"""

    type_name = "parameterRegex"

    def __init__(self, pattern):
        super().__init__(pattern)
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        text = " ".join(parsed.all_argument_texts())
        return MatchOutcome.MATCHED if self._compiled.search(text) else MatchOutcome.NOT_MATCHED

    def explain(self, action):
        return f"the arguments, joined by spaces, {action.must_phrase} match `{self._pattern}`"


class MatchFullParameterMatcher(Matcher):
    """Config: {"type": "matchFullParameter", "pattern": "value"}

    Exact-value membership, not a regex search.
    """

    type_name = "matchFullParameter"

    def match(self, parsed):
        matched = self._pattern in parsed.all_argument_texts()
        return MatchOutcome.MATCHED if matched else MatchOutcome.NOT_MATCHED

    def explain(self, action):
        if action.is_required:
            return f"one argument must be exactly `{self._pattern}`"
        return f"no argument may be exactly `{self._pattern}`"


class PositionalArgRegexMatcher(Matcher):
    """Config: {"type": "positionalArgRegex", "pattern": "regex"}"""

    type_name = "positionalArgRegex"

    def __init__(self, pattern):
        super().__init__(pattern)
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        text = " ".join(parsed.positional_values())
        return MatchOutcome.MATCHED if self._compiled.search(text) else MatchOutcome.NOT_MATCHED

    def explain(self, action):
        return f"the positional arguments, joined by spaces, {action.must_phrase} match `{self._pattern}`"


class ArgumentAtIndexMatcher(Matcher):
    """Config: {"type": "argumentAtIndex", "index": N, "pattern": "regex"}"""

    type_name = "argumentAtIndex"

    def __init__(self, index, pattern):
        super().__init__(pattern)
        self._index = index
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        args = parsed.all_argument_texts()
        if self._index < 0 or self._index >= len(args):
            return MatchOutcome.TARGET_ABSENT
        return MatchOutcome.MATCHED if self._compiled.search(args[self._index]) else MatchOutcome.NOT_MATCHED

    def explain(self, action):
        return (
            f"argument {self._index} (from 0, options counted) must be present"
            f" and {action.must_phrase} match `{self._pattern}`"
        )

    def _identity(self):
        return (*super()._identity(), self._index)


class PositionalArgAtIndexMatcher(Matcher):
    """Config: {"type": "positionalArgAtIndex", "index": N, "pattern": "regex"}"""

    type_name = "positionalArgAtIndex"

    def __init__(self, index, pattern):
        super().__init__(pattern)
        self._index = index
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        values = parsed.positional_values()
        if self._index < 0 or self._index >= len(values):
            return MatchOutcome.TARGET_ABSENT
        return MatchOutcome.MATCHED if self._compiled.search(values[self._index]) else MatchOutcome.NOT_MATCHED

    def explain(self, action):
        return (
            f"positional argument {self._index} (from 0, options skipped) must be present"
            f" and {action.must_phrase} match `{self._pattern}`"
        )

    def _identity(self):
        return (*super()._identity(), self._index)


class NamedValueMatcher(Matcher):
    """Config: {"type": "namedValue", "name": "key", "pattern": "regex"}"""

    type_name = "namedValue"

    def __init__(self, name, pattern):
        super().__init__(pattern)
        self._name = name
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        value = parsed.named.get(self._name)
        if value is None:
            return MatchOutcome.TARGET_ABSENT
        return MatchOutcome.MATCHED if self._compiled.search(_json_spelling_of(value)) else MatchOutcome.NOT_MATCHED

    def explain(self, action):
        return f"value `{self._name}` must be present and {action.must_phrase} match `{self._pattern}`"

    def _identity(self):
        return (*super()._identity(), self._name)


class OptionValueMatcher(Matcher):
    """Config: {"type": "optionValue", "option": "-m", "pattern": "regex"}"""

    type_name = "optionValue"

    def __init__(self, option, pattern):
        super().__init__(pattern)
        self._option = option
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        for option in parsed.options:
            if option.name == self._option:
                text = " ".join(option.arguments)
                return MatchOutcome.MATCHED if self._compiled.search(text) else MatchOutcome.NOT_MATCHED
        return MatchOutcome.TARGET_ABSENT

    def explain(self, action):
        return f"option `{self._option}` must be given and its value {action.must_phrase} match `{self._pattern}`"

    def _identity(self):
        return (*super()._identity(), self._option)


class OptionPresentMatcher(Matcher):
    """Config: {"type": "optionPresent", "option": "--force"}

    No target-absent state: presence itself IS the match outcome.
    """

    type_name = "optionPresent"

    def __init__(self, option):
        super().__init__(pattern=None)
        self._option = option

    def match(self, parsed):
        present = any(option.name == self._option for option in parsed.options)
        return MatchOutcome.MATCHED if present else MatchOutcome.NOT_MATCHED

    def explain(self, action):
        return f"option `{self._option}` {action.must_phrase} be given"

    def _identity(self):
        return (*super()._identity(), self._option)


def _json_spelling_of(value):
    """Render a named value the way a config author writes it in JSON."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
