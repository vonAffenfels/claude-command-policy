"""Unit tests for the Matcher family and its three-state MatchOutcome contract.

THE THREE-STATE SUBTLETY: ArgumentAtIndexMatcher, PositionalArgAtIndexMatcher,
NamedValueMatcher and OptionValueMatcher must return TARGET_ABSENT - not
NOT_MATCHED - when their target does not exist, so Action fails the filter
closed regardless of block/required. The other four matchers
(ParameterRegex, MatchFullParameter, PositionalArgRegex, OptionPresent) have
no such short-circuit and are only ever MATCHED/NOT_MATCHED.
"""

from action import Action
from match_outcome import MatchOutcome
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
from parsed_result import ParsedOption, ParsedPositional, ParsedResult


def parsed(options=(), positionals=(), named=None):
    return ParsedResult(options=options, positionals=positionals, named=named)


# -- ParameterRegexMatcher --------------------------------------------------


def test_parameter_regex_matcher_matches_against_all_argument_texts():
    matcher = ParameterRegexMatcher(pattern="--force")
    result = parsed(options=[ParsedOption("--force")])

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_parameter_regex_matcher_reports_not_matched_when_absent():
    matcher = ParameterRegexMatcher(pattern="--force")
    result = parsed(options=[ParsedOption("--verbose")])

    assert matcher.match(result) is MatchOutcome.NOT_MATCHED


# -- MatchFullParameterMatcher ------------------------------------------------


def test_match_full_parameter_matcher_matches_an_exact_argument():
    matcher = MatchFullParameterMatcher(pattern="--force")
    result = parsed(options=[ParsedOption("--force")])

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_match_full_parameter_matcher_does_not_match_a_partial_argument():
    matcher = MatchFullParameterMatcher(pattern="--force")
    result = parsed(options=[ParsedOption("--force-push")])

    assert matcher.match(result) is MatchOutcome.NOT_MATCHED


# -- PositionalArgRegexMatcher ------------------------------------------------


def test_positional_arg_regex_matcher_matches_against_positionals_only():
    matcher = PositionalArgRegexMatcher(pattern="secret")
    result = parsed(
        options=[ParsedOption("secret-flag")],
        positionals=[ParsedPositional(0, "secret.txt")],
    )

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_positional_arg_regex_matcher_ignores_option_text():
    matcher = PositionalArgRegexMatcher(pattern="secret")
    result = parsed(options=[ParsedOption("secret-flag")], positionals=[ParsedPositional(0, "a.txt")])

    assert matcher.match(result) is MatchOutcome.NOT_MATCHED


# -- ArgumentAtIndexMatcher: the three-state contract -------------------------


def test_argument_at_index_matcher_matches_the_argument_at_the_given_index():
    matcher = ArgumentAtIndexMatcher(index=0, pattern="--force")
    result = parsed(options=[ParsedOption("--force")])

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_argument_at_index_matcher_reports_not_matched_for_a_present_but_different_argument():
    matcher = ArgumentAtIndexMatcher(index=0, pattern="--force")
    result = parsed(options=[ParsedOption("--verbose")])

    assert matcher.match(result) is MatchOutcome.NOT_MATCHED


def test_argument_at_index_matcher_reports_target_absent_when_index_is_out_of_bounds():
    matcher = ArgumentAtIndexMatcher(index=5, pattern="--force")
    result = parsed(options=[ParsedOption("--verbose")])

    assert matcher.match(result) is MatchOutcome.TARGET_ABSENT


def test_argument_at_index_out_of_bounds_fails_closed_under_block_action():
    matcher = ArgumentAtIndexMatcher(index=5, pattern="--force")
    action = Action.from_definition({"action": "block"})
    result = parsed(options=[ParsedOption("--verbose")])

    assert action.applies_to(matcher.match(result)) is False


def test_argument_at_index_out_of_bounds_fails_closed_under_required_action():
    matcher = ArgumentAtIndexMatcher(index=5, pattern="--force")
    action = Action.from_definition({"action": "required"})
    result = parsed(options=[ParsedOption("--verbose")])

    assert action.applies_to(matcher.match(result)) is False


# -- PositionalArgAtIndexMatcher: the three-state contract --------------------


def test_positional_arg_at_index_matcher_matches_the_positional_at_the_given_index():
    matcher = PositionalArgAtIndexMatcher(index=0, pattern="commit")
    result = parsed(positionals=[ParsedPositional(0, "commit")])

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_positional_arg_at_index_matcher_reports_target_absent_when_index_is_out_of_bounds():
    matcher = PositionalArgAtIndexMatcher(index=3, pattern="commit")
    result = parsed(positionals=[ParsedPositional(0, "commit")])

    assert matcher.match(result) is MatchOutcome.TARGET_ABSENT


def test_positional_arg_at_index_out_of_bounds_fails_closed_under_block_action():
    matcher = PositionalArgAtIndexMatcher(index=3, pattern="commit")
    action = Action.from_definition({"action": "block"})
    result = parsed(positionals=[ParsedPositional(0, "commit")])

    assert action.applies_to(matcher.match(result)) is False


def test_positional_arg_at_index_out_of_bounds_fails_closed_under_required_action():
    matcher = PositionalArgAtIndexMatcher(index=3, pattern="commit")
    action = Action.from_definition({"action": "required"})
    result = parsed(positionals=[ParsedPositional(0, "commit")])

    assert action.applies_to(matcher.match(result)) is False


# -- NamedValueMatcher: the three-state contract ------------------------------


def test_named_value_matcher_matches_a_present_named_value():
    matcher = NamedValueMatcher(name="subcommand", pattern="commit")
    result = parsed(named={"subcommand": "commit"})

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_named_value_matcher_reports_target_absent_when_the_name_is_missing():
    matcher = NamedValueMatcher(name="subcommand", pattern="commit")
    result = parsed(named={})

    assert matcher.match(result) is MatchOutcome.TARGET_ABSENT


def test_named_value_matcher_renders_a_boolean_value_the_way_json_would():
    matcher = NamedValueMatcher(name="verbose", pattern="^true$")
    result = parsed(named={"verbose": True})

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_named_value_missing_fails_closed_under_block_action():
    matcher = NamedValueMatcher(name="subcommand", pattern="commit")
    action = Action.from_definition({"action": "block"})
    result = parsed(named={})

    assert action.applies_to(matcher.match(result)) is False


def test_named_value_missing_fails_closed_under_required_action():
    matcher = NamedValueMatcher(name="subcommand", pattern="commit")
    action = Action.from_definition({"action": "required"})
    result = parsed(named={})

    assert action.applies_to(matcher.match(result)) is False


# -- OptionValueMatcher: the three-state contract -----------------------------


def test_option_value_matcher_matches_against_the_options_argument_values():
    matcher = OptionValueMatcher(option="-m", pattern="fix")
    result = parsed(options=[ParsedOption("-m", ["fix bug"])])

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_option_value_matcher_reports_target_absent_when_the_option_is_not_present():
    matcher = OptionValueMatcher(option="-m", pattern="fix")
    result = parsed(options=[ParsedOption("-v")])

    assert matcher.match(result) is MatchOutcome.TARGET_ABSENT


def test_option_value_missing_fails_closed_under_block_action():
    matcher = OptionValueMatcher(option="-m", pattern="fix")
    action = Action.from_definition({"action": "block"})
    result = parsed(options=[ParsedOption("-v")])

    assert action.applies_to(matcher.match(result)) is False


def test_option_value_missing_fails_closed_under_required_action():
    matcher = OptionValueMatcher(option="-m", pattern="fix")
    action = Action.from_definition({"action": "required"})
    result = parsed(options=[ParsedOption("-v")])

    assert action.applies_to(matcher.match(result)) is False


# -- OptionPresentMatcher: no target-absent state -----------------------------


def test_option_present_matcher_matches_when_the_option_is_present():
    matcher = OptionPresentMatcher(option="--force")
    result = parsed(options=[ParsedOption("--force")])

    assert matcher.match(result) is MatchOutcome.MATCHED


def test_option_present_matcher_reports_not_matched_when_the_option_is_absent():
    matcher = OptionPresentMatcher(option="--force")
    result = parsed(options=[ParsedOption("--verbose")])

    assert matcher.match(result) is MatchOutcome.NOT_MATCHED


# -- explain()/derive_alternative() -------------------------------------------


def test_pattern_matcher_explain_reproduces_todays_description_format():
    matcher = ParameterRegexMatcher(pattern="--force")
    action = Action.from_definition({"action": "block"})

    assert matcher.explain(action) == "parameterRegex block pattern '--force'"


def test_pattern_matcher_derive_alternative_under_block_names_the_part_to_drop():
    matcher = ParameterRegexMatcher(pattern="--force")
    action = Action.from_definition({"action": "block"})

    assert matcher.derive_alternative(action) == "the same command without the part matching '--force'"


def test_pattern_matcher_derive_alternative_under_required_names_the_part_to_add():
    matcher = ParameterRegexMatcher(pattern="--force")
    action = Action.from_definition({"action": "required"})

    assert matcher.derive_alternative(action) == "the same command with an argument matching '--force'"


def test_option_present_matcher_explain_names_the_option_not_a_pattern():
    matcher = OptionPresentMatcher(option="--force")
    action = Action.from_definition({"action": "block"})

    assert matcher.explain(action) == "optionPresent block on option '--force'"


def test_option_present_matcher_derive_alternative_under_block_says_without_the_option():
    matcher = OptionPresentMatcher(option="--force")
    action = Action.from_definition({"action": "block"})

    assert matcher.derive_alternative(action) == "the same command without the '--force' option"


def test_option_present_matcher_derive_alternative_under_required_says_with_the_option():
    matcher = OptionPresentMatcher(option="--force")
    action = Action.from_definition({"action": "required"})

    assert matcher.derive_alternative(action) == "the same command with the '--force' option"
