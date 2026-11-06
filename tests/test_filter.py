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

    assert filter_.explain() == "the arguments, joined by spaces, must not match `--force`"


def test_an_invalid_filter_explains_that_it_is_broken_and_why():
    filter_ = Filter.from_definition({"type": "madeUp"})

    assert filter_.explain().startswith("broken rule, this entry never applies: ")
    assert "madeUp" in filter_.explain()


def test_a_nested_command_filter_explains_its_requirement_and_optional_depth():
    assert Filter.from_definition({"type": "nestedCommand"}).explain() == (
        "every wrapped command must itself be auto-allowed (at least one required)"
    )
    assert Filter.from_definition({"type": "nestedCommand", "maxDepth": 2}).explain().endswith("; max depth 2)")


def test_filters_built_from_the_same_definition_are_equal():
    definition = {"type": "namedValue", "name": "subcommand", "pattern": "^a$", "action": "required"}

    assert Filter.from_definition(definition) == Filter.from_definition(dict(definition))
    assert Filter.from_definition(definition) != Filter.from_definition({**definition, "pattern": "^b$"})
    assert Filter.from_definition(definition) != Filter.from_definition({**definition, "action": "block"})
