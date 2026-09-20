"""Matcher family: what a filter extracts and compares, independent of what
it does with the outcome (that is Action's job - see filter.py).

Eight concrete matchers, one per today's projection+comparison pair. Four of
them (ArgumentAtIndex, PositionalArgAtIndex, NamedValue, OptionValue) can
report MatchOutcome.TARGET_ABSENT when the thing they would compare against
does not exist at all - see match_outcome.py for why that is a third state
rather than NOT_MATCHED. PathsFilter is NOT a Matcher: its 'exactly'-match-
over-a-list semantics has no block/required action at all - see filter.py.
"""

from __future__ import annotations

import re

from match_outcome import MatchOutcome


class Matcher:
    """Shared explain()/derive_alternative() for the seven pattern-bearing
    matchers. OptionPresentMatcher overrides both - it names an option, not
    a pattern.
    """

    type_name = ""

    def __init__(self, pattern=None):
        self._pattern = pattern

    def match(self, parsed):
        raise NotImplementedError

    def explain(self, action):
        return f"{self.type_name} {action.explain()} pattern '{self._pattern}'"

    def derive_alternative(self, action):
        if action.is_required:
            return f"the same command with an argument matching '{self._pattern}'"
        return f"the same command without the part matching '{self._pattern}'"


class ParameterRegexMatcher(Matcher):
    """Config: {"type": "parameterRegex", "pattern": "regex"}"""

    type_name = "parameterRegex"

    def __init__(self, pattern):
        super().__init__(pattern)
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        text = " ".join(parsed.all_argument_texts())
        return MatchOutcome.MATCHED if self._compiled.search(text) else MatchOutcome.NOT_MATCHED


class MatchFullParameterMatcher(Matcher):
    """Config: {"type": "matchFullParameter", "pattern": "value"}

    Exact-value membership, not a regex search.
    """

    type_name = "matchFullParameter"

    def match(self, parsed):
        matched = self._pattern in parsed.all_argument_texts()
        return MatchOutcome.MATCHED if matched else MatchOutcome.NOT_MATCHED


class PositionalArgRegexMatcher(Matcher):
    """Config: {"type": "positionalArgRegex", "pattern": "regex"}"""

    type_name = "positionalArgRegex"

    def __init__(self, pattern):
        super().__init__(pattern)
        self._compiled = re.compile(pattern)

    def match(self, parsed):
        text = " ".join(parsed.positional_values())
        return MatchOutcome.MATCHED if self._compiled.search(text) else MatchOutcome.NOT_MATCHED


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
        return f"optionPresent {action.explain()} on option '{self._option}'"

    def derive_alternative(self, action):
        if action.is_required:
            return f"the same command with the '{self._option}' option"
        return f"the same command without the '{self._option}' option"


def _json_spelling_of(value):
    """Render a named value the way a config author writes it in JSON."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
