"""Unit tests for Filter: Matcher + Action composition via a named constructor.

create_filter's dict-of-classes factory is replaced entirely by
Filter.from_definition - no filter type dispatch lives outside this file's
subject.
"""

from filter import Filter, InvalidFilter
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


def test_an_uncompilable_pattern_degrades_to_an_invalid_filter_instead_of_raising():
    filter_ = Filter.from_definition({"type": "parameterRegex", "pattern": "(unclosed", "action": "block"})

    assert isinstance(filter_, InvalidFilter)
    assert filter_.matches(ParsedResult()) is False


def test_the_invalid_filters_problem_names_the_offending_type_and_pattern():
    filter_ = Filter.from_definition({"type": "parameterRegex", "pattern": "(unclosed", "action": "block"})

    [problem] = filter_.problems
    assert "parameterRegex" in problem
    assert "(unclosed" in problem


def test_an_unknown_filter_type_degrades_to_an_invalid_filter_instead_of_raising():
    filter_ = Filter.from_definition({"type": "madeUp", "action": "block"})

    assert isinstance(filter_, InvalidFilter)
    assert "madeUp" in filter_.problems[0]


def test_explain_delegates_to_the_matcher_with_the_actions_own_kind():
    filter_ = Filter.from_definition({"type": "parameterRegex", "pattern": "--force", "action": "block"})

    assert filter_.explain() == "parameterRegex block pattern '--force'"


def test_derive_alternative_delegates_to_the_matcher_with_the_actions_own_kind():
    filter_ = Filter.from_definition({"type": "optionPresent", "option": "--force", "action": "block"})

    assert filter_.derive_alternative() == "the same command without the '--force' option"
