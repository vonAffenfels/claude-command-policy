"""Unit tests for Filter: Matcher + Action composition via a named constructor.

create_filter's dict-of-classes factory is replaced entirely by
Filter.from_definition - no filter type dispatch lives outside this file's
subject.
"""

import pytest

from config import ConfigError
from filter import Filter
from parsed_result import ParsedOption, ParsedResult


def test_from_definition_builds_a_working_block_filter():
    filter_ = Filter.from_definition({"type": "parameterRegex", "pattern": "--force", "action": "block"})

    passing = ParsedResult(options=[ParsedOption("--other")])
    blocking = ParsedResult(options=[ParsedOption("--force")])

    assert filter_.matches(passing) is True
    assert filter_.matches(blocking) is False


def test_from_definition_builds_a_working_required_filter():
    filter_ = Filter.from_definition({"type": "optionPresent", "option": "--yes", "action": "required"})

    assert filter_.matches(ParsedResult(options=[ParsedOption("--yes")])) is True
    assert filter_.matches(ParsedResult(options=[ParsedOption("--other")])) is False


def test_from_definition_defaults_action_to_block():
    filter_ = Filter.from_definition({"type": "parameterRegex", "pattern": "--force"})

    assert filter_.matches(ParsedResult(options=[ParsedOption("--force")])) is False


def test_target_absent_fails_the_filter_under_block_action_not_the_naive_inversion():
    """An out-of-bounds argumentAtIndex under `block` must FAIL (deny), not
    pass - the exact regression a naive `not matched` composition produces.
    """
    filter_ = Filter.from_definition(
        {"type": "argumentAtIndex", "index": 5, "pattern": "--force", "action": "block"}
    )

    assert filter_.matches(ParsedResult(options=[ParsedOption("--other")])) is False


def test_an_uncompilable_pattern_is_rejected_at_construction():
    with pytest.raises(ConfigError):
        Filter.from_definition({"type": "parameterRegex", "pattern": "(unclosed", "action": "block"})


def test_the_construction_error_carries_the_offending_type_and_pattern():
    with pytest.raises(ConfigError) as excinfo:
        Filter.from_definition({"type": "parameterRegex", "pattern": "(unclosed", "action": "block"})

    assert excinfo.value.filter_type == "parameterRegex"
    assert excinfo.value.pattern == "(unclosed"


def test_explain_delegates_to_the_matcher_with_the_actions_own_kind():
    filter_ = Filter.from_definition({"type": "parameterRegex", "pattern": "--force", "action": "block"})

    assert filter_.explain() == "parameterRegex block pattern '--force'"


def test_derive_alternative_delegates_to_the_matcher_with_the_actions_own_kind():
    filter_ = Filter.from_definition({"type": "optionPresent", "option": "--force", "action": "block"})

    assert filter_.derive_alternative() == "the same command without the '--force' option"
