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


BLOCK = Action.from_definition({"action": "block"})
REQUIRED = Action.from_definition({"action": "required"})


def test_parameter_regex_rule_line_states_target_direction_and_pattern():
    matcher = ParameterRegexMatcher(pattern="--force")

    assert matcher.explain(BLOCK) == "the arguments, joined by spaces, must not match `--force`"
    assert matcher.explain(REQUIRED) == "the arguments, joined by spaces, must match `--force`"


def test_match_full_parameter_rule_line_distinguishes_required_from_block():
    matcher = MatchFullParameterMatcher(pattern="--dry-run")

    assert matcher.explain(REQUIRED) == "one argument must be exactly `--dry-run`"
    assert matcher.explain(BLOCK) == "no argument may be exactly `--dry-run`"


def test_positional_arg_regex_rule_line_names_the_positional_arguments():
    matcher = PositionalArgRegexMatcher(pattern="^src/")

    assert matcher.explain(REQUIRED) == "the positional arguments, joined by spaces, must match `^src/`"


def test_argument_at_index_rule_line_states_index_and_that_the_target_must_be_present():
    matcher = ArgumentAtIndexMatcher(index=1, pattern="^x$")

    expected = "argument 1 (from 0, options counted) must be present and must match `^x$`"
    assert matcher.explain(REQUIRED) == expected
    assert matcher.explain(BLOCK).endswith("must be present and must not match `^x$`")


def test_positional_arg_at_index_rule_line_states_index_and_that_options_are_skipped():
    matcher = PositionalArgAtIndexMatcher(index=0, pattern="^parsers/[a-z-]+\\.py$")

    expected = "positional argument 0 (from 0, options skipped) must be present and must match `^parsers/[a-z-]+\\.py$`"
    assert matcher.explain(REQUIRED) == expected


def test_named_value_rule_line_names_the_value():
    matcher = NamedValueMatcher(name="subcommand", pattern="^(status|log)$")

    assert matcher.explain(REQUIRED) == "value `subcommand` must be present and must match `^(status|log)$`"
    assert matcher.explain(BLOCK) == "value `subcommand` must be present and must not match `^(status|log)$`"


def test_option_value_rule_line_names_the_option():
    matcher = OptionValueMatcher(option="-m", pattern="^feat")

    assert matcher.explain(REQUIRED) == "option `-m` must be given and its value must match `^feat`"


def test_option_present_rule_line_names_the_option_not_a_pattern():
    matcher = OptionPresentMatcher(option="--force")

    assert matcher.explain(BLOCK) == "option `--force` must not be given"
    assert matcher.explain(REQUIRED) == "option `--force` must be given"


def test_matchers_are_equal_by_kind_pattern_and_target():
    assert NamedValueMatcher("a", "x") == NamedValueMatcher("a", "x")
    assert NamedValueMatcher("a", "x") != NamedValueMatcher("b", "x")
    assert ArgumentAtIndexMatcher(0, "x") != ArgumentAtIndexMatcher(1, "x")
    assert ParameterRegexMatcher("x") != PositionalArgRegexMatcher("x")
