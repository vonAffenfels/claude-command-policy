"""Authored decision specification for the command-policy engine.

This suite defines what `Config.from_dict(cfg).decision_for(command)` SHOULD
do under the trunk's deny+hint outcome model. It is written against a public
entrypoint that does not have a real implementation yet (see
improvement-20260914-213049) - every case here is deliberately RED, failing
with NotImplementedError, until leaf 20260914-213652 wires the real pipeline.
A collection/import error is a defect in this suite; NotImplementedError at
assertion time is the correct, expected state.

WHAT DENY MEANS HERE - read before adding or judging any case below.

Deny is NOT prevention; it is ROUTING. `allow` is the only privileged outcome,
because it is the only one that runs with no human involved. A `deny` does not
block anything: it tells the caller "this could not be auto-approved", and the
caller is expected to try again with something that can be - guided by the hint
- or, if nothing auto-approved achieves the result, to escalate deliberately by
name through `bypass-policy`, which hands the decision to the human.

Three consequences, each easy to get backwards when reading a case:
  - Denying MORE is not safer. Narrowing the escape hatch removes the caller's
    escalation route without adding protection, since bypass already routes to
    a human.
  - The hint is load-bearing. It is what the caller acts on to find an
    auto-approved equivalent, which is why the ordering cases specify WHICH
    reason surfaces when two objections both apply.
  - The defect class these cases guard against is unintended AUTO-APPROVAL, not
    insufficient denial. Every "fails closed" below means "declines to
    auto-approve", never "blocks".

Cases are harvested from `packages/shfmt-permissions/tests/test_analyze_bash_command.py`
as INSPIRATION for coverage territory only - the decisions asserted here are
freshly adjudicated for the new deny+hint model, not inherited. See that
improvement file's Implementation Notes for the full Flag List behind each
adjudication referenced in a case's docstring/comment below.

Cases are grouped into themed batches (see the improvement file's Proposed
Approach, Step 5), reviewed and approved by the user one theme at a time:
  1. the surviving decision-adjacent knob + the uniform deny+hint default
  2. filters
  3. paths and redirects
  4. wrappers and command propagation
  5. bypass and add-allow-policy escalation
"""

from pathlib import Path

import pytest

from config import Config, ConfigError
from reason import (
    AddAllowPolicyGrammarViolation,
    ArgumentPathOutsideAllowedPaths,
    BlockedCommandInvoked,
    CommandSubstitutionPresent,
    FilterRejected,
    NotEscalatedByAnUnrelatedBypassWrapper,
    ProgramNotAllowListed,
    RedirectOutsideAllowedPaths,
    SensitivePathReferenced,
    SensitiveVariableReferenced,
    UnknowablePathArgument,
)
from reason_renderer import render

# commandSubstitutionResponse is the only decision-adjacent knob that
# survives the outcome model (see the improvement's WHAT CHANGED item 3).
# This is a temporary, suite-local mirror of its valid-value set - it exists
# only so `assert_config_is_reachable` can guard THIS suite's own cases
# before `Config.from_dict` does real validation. Leaf 20260914-213153 makes
# `Config.from_dict` itself the source of truth; once it does, re-point this
# guard at whatever it exposes instead of this literal set.
SURVIVING_DECISION_KNOB_VALID_VALUES = {
    "commandSubstitutionResponse": {"deny", "via-allowed-commands"},
}


def assert_config_is_reachable(config: dict) -> None:
    """Fail loudly if `config` holds a value no real command-policy.json could produce.

    See Flag List F4: covers only the surviving decision-adjacent knob's
    shape for now - there is still no equivalent guard for allowedCommands
    or filter shapes (that's precisely where Flag List A1/A2 live), and none
    is possible yet since `Config.from_dict` does not validate anything.
    """
    for knob, valid_values in SURVIVING_DECISION_KNOB_VALID_VALUES.items():
        if knob not in config:
            continue
        supplied_value = config[knob]
        if supplied_value not in valid_values:
            valid_list = ", ".join(f"'{v}'" for v in sorted(valid_values))
            raise AssertionError(
                f"{knob}: '{supplied_value}' is not a valid value (valid: {valid_list})."
            )


def decision_for(command: str, config: dict):
    assert_config_is_reachable(config)
    return Config.from_dict(config).decision_for(command)


def assert_decision(command: str, config: dict, expected_decision: str):
    """Assert that a command produces the expected decision, and return the
    full result so a caller can additionally inspect its reason list via
    `assert_reason_includes`/`assert_primary_reason` below.
    """
    result = decision_for(command, config)
    assert result.decision == expected_decision, (
        f"Command: {command}\n"
        f"Expected decision: {expected_decision}, Actual: {result.decision}\n"
        f"Reason: {result.reason}"
    )
    return result


def assert_reason_includes(result, expected_reason) -> None:
    """Structural counterpart to assert_decision - asserts a Reason value
    object is present in the decision's reason list, without rendering it to
    prose first (leaf 20260915-010959's Design Decisions, 'How the spec
    suite asserts reasons': structural comparison is more durable than
    substring matching, cannot false-pass, and can express completeness).
    """
    assert expected_reason in (result.reason or ()), (
        f"Expected reason list to include {expected_reason!r}\nActual: {result.reason!r}"
    )


def assert_primary_reason(result, expected_reason) -> None:
    """Asserts `expected_reason` is the FIRST (pass-order) element of the
    reason list - for the ordering cases, which pin WHICH objection the
    engine reports first when several apply. Structural, so it fails the
    instant the primary objection changes rather than merely no longer
    proving anything (a substring check on rendered prose would keep passing
    even after a reorder, once every objection's text is always present)."""
    reason = result.reason or ()
    assert reason and reason[0] == expected_reason, (
        f"Expected the FIRST reason to be {expected_reason!r}\nActual: {result.reason!r}"
    )


# =============================================================================
# Batch 1: the surviving decision-adjacent knob + the uniform deny+hint default
# =============================================================================


def test_allow_listed_command_with_no_objections_is_allowed():
    assert_decision("echo hi", {"allowedCommands": ["echo"]}, "allow")


def test_a_program_glob_entry_allows_a_command_matching_its_wildcarded_version_path(monkeypatch, tmp_path):
    """`programGlob` (renamed from the old engine's `pluginProgram`, improvement
    20260915-011123) matches the ABSOLUTE RENDERED PATH of a plugin-cache
    script, wildcarding the version segment between `{plugin}` and `{path}` -
    this is the cross-leaf hand-back's matching-time half, completed here
    since leaf 20260914-213652 had already shipped by the time this leaf
    started.
    """
    monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(tmp_path))
    invoked = str(tmp_path / "vonaffenfels-dev-tools" / "improvement" / "1.26.3" / "bin" / "improvement-marker")

    assert_decision(
        f"{invoked} clear",
        {
            "allowedCommands": [
                {
                    "programGlob": {
                        "marketplace": "vonaffenfels-dev-tools",
                        "plugin": "improvement",
                        "path": "bin/improvement-marker",
                    }
                }
            ]
        },
        "allow",
    )


def test_program_absent_from_allowed_commands_entirely_is_denied_with_a_hint():
    """CASE A (old vocabulary): program never appears in allowedCommands at all.

    Under the old model this fell through to `defaultDecision` (default
    'passthrough'). Under the new model there is no knob left that could
    route this to anything but deny+hint - see trunk Consequence 4.
    """
    result = assert_decision("rm -rf /", {"allowedCommands": ["echo"]}, "deny")
    assert_reason_includes(result, ProgramNotAllowListed("rm"))


def test_allow_listed_program_whose_invocation_is_rejected_is_denied_with_a_hint():
    """CASE B (old vocabulary): program IS in allowedCommands, but the matched
    entry's own validation (e.g. a filter) rejects the specific invocation.

    Under the old model this used `filterRejectionResponse` (default
    'passthrough') - a DIFFERENT knob from CASE A's `defaultDecision`, even
    though they defaulted to the same value. Under the new model both knobs
    are gone and both cases collapse to the same constant, deny+hint - this
    case and the one above together ARE the single reworked E-section case
    asserting that CASE A and CASE B now produce the same outcome.
    """
    assert_decision(
        "echo --forbidden-flag",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [{"type": "optionPresent", "option": "--forbidden-flag", "action": "block"}],
                }
            ]
        },
        "deny",
    )


def test_allow_listed_program_missing_a_required_option_is_denied():
    """`action: "required"` rejects the invocation that OMITS the option.

    The mirror of the CASE B case above: there the filter rejected because a
    forbidden option was present, here because a required one is absent. Both
    are entry-level rejections and both land on the same constant, deny+hint.
    """
    assert_decision(
        "echo hi",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [{"type": "optionPresent", "option": "--required-flag", "action": "required"}],
                }
            ]
        },
        "deny",
    )


def test_allow_listed_program_carrying_its_required_option_is_allowed():
    """Pairs with the case above so the `required` filter is pinned in both
    directions - without this, a filter that rejected everything would satisfy
    the deny case just as well.
    """
    assert_decision(
        "echo --required-flag hi",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [{"type": "optionPresent", "option": "--required-flag", "action": "required"}],
                }
            ]
        },
        "allow",
    )


def test_command_substitution_defeats_a_filter_forbidding_content_and_is_denied():
    """A substitution's expansion is unknowable, so ABSENCE can never be proven.

    `via-allowed-commands` clears the inner command itself (`echo` is
    allow-listed), but the matched entry also forbids `--forbidden-flag`, and
    nothing static can rule out `$(...)` expanding to exactly that. The engine
    must fail closed rather than assert a property of text it cannot see.

    This is why the earlier bare `echo $(echo safe)` case is still ALLOW: that
    entry restricts no argument content, so an unknowable expansion changes
    nothing about what the entry permits. The unknowability only bites once the
    entry makes a claim about content.

    No `hasNoPathParameters` needed: `$(echo safe)` is the invocation's only
    argument and contributes no literal text at all, so the default parser's
    path heuristic never has anything to detect - argument-path containment
    (improvement-20260919-112214) only fails closed when it actually has a
    path candidate to protect (see that improvement's Design Decisions,
    'Argument-path containment next to unknowable content'), so it stays out
    of this filter's way on its own.
    """
    assert_decision(
        "echo $(echo safe)",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [{"type": "optionPresent", "option": "--forbidden-flag", "action": "block"}],
                }
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "deny",
    )


def test_command_substitution_does_not_defeat_a_filter_requiring_present_content():
    """The unknowability is ASYMMETRIC: presence is provable, absence is not.

    Word-splitting a substitution's output can only ADD arguments, never remove
    the literal `--required-flag` sitting in the AST - so a `required` filter
    stays satisfiable next to a substitution, where a `block` filter does not.

    `hasNoPathParameters` is a TRUE factual claim here, not a waiver bolted
    on to make the case pass: `echo` takes no path operands at all. Under
    the rule that every argument the parser cannot rule out is a path
    candidate (improvement-20260919-112214, second fix round), that claim is
    precisely what EARNS an entry the right to carry a substitution - so
    this case both tests its named filter mechanism and demonstrates the
    first of the three sanctioned ways to earn one. Removing the flag would
    not expose a filter bug; it would assert that `echo` takes paths.
    """
    assert_decision(
        "echo --required-flag $(echo safe)",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "hasNoPathParameters": True,
                    "filters": [{"type": "optionPresent", "option": "--required-flag", "action": "required"}],
                }
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "allow",
    )


def test_substitution_before_an_indexed_argument_defeats_a_required_index_filter():
    """A substitution expanding to != 1 word SHIFTS every index after it.

    Statically `--required-second-argument` sits at argument index 1 and the
    filter looks satisfied. At runtime `$(echo just-one-argument)` may expand
    to zero words or to five, putting the flag at index 0 or index 4 instead.
    Presence is provable here (G2) but POSITION is not, so a `required` filter
    that pins a position must fail closed - the one case G2's asymmetry does
    not rescue.

    No `hasNoPathParameters` needed: `$(echo just-one-argument)` contributes
    no literal text, so argument-path containment (improvement-20260919-
    112214) has no path candidate to fail closed on here.
    """
    assert_decision(
        "echo $(echo just-one-argument) --required-second-argument",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [
                        {
                            "type": "argumentAtIndex",
                            "index": 1,
                            "pattern": "^--required-second-argument$",
                            "action": "required",
                        }
                    ],
                }
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "deny",
    )


def test_substitution_before_an_indexed_positional_defeats_a_required_positional_filter():
    """The same shift, on the other index-based filter type.

    `positionalArgAtIndex` counts only positionals where `argumentAtIndex`
    counts every argument, but an unknowable expansion shifts both alike -
    the distinction between the two filter types does not rescue either.

    No `hasNoPathParameters` needed: `$(echo one)` contributes no literal
    text, so argument-path containment has no path candidate here.
    """
    assert_decision(
        "echo $(echo one) expected-second",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [
                        {
                            "type": "positionalArgAtIndex",
                            "index": 1,
                            "pattern": "^expected-second$",
                            "action": "required",
                        }
                    ],
                }
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "deny",
    )


def test_substitution_after_an_indexed_argument_leaves_the_index_provable():
    """Pins WHERE the shift bites, so the rule above is not read as
    "any substitution plus any index filter denies".

    A substitution can only shift what FOLLOWS it. Index 0 is pinned by the
    literal `expected-first` sitting ahead of the substitution, so the filter
    stays provable and the invocation is allowed.

    `hasNoPathParameters` is a TRUE claim about `echo` (it takes no path
    operands) and is what earns this entry its substitution under
    improvement-20260919-112214's second fix round, where an argument the
    parser cannot rule out IS a path candidate. Without it the invocation
    would deny on argument-path containment before this index rule was ever
    reached, and the case would stop testing what it is named after.
    """
    assert_decision(
        "echo expected-first $(echo tail)",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "hasNoPathParameters": True,
                    "filters": [
                        {
                            "type": "positionalArgAtIndex",
                            "index": 0,
                            "pattern": "^expected-first$",
                            "action": "required",
                        }
                    ],
                }
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "allow",
    )


def test_command_substitution_response_deny_denies_regardless_of_inner_command():
    """commandSubstitutionResponse: 'deny' denies outright on ANY substitution,
    without inspecting the inner command at all - even one that would
    otherwise be allow-listed.
    """
    result = assert_decision(
        "echo $(echo safe)",
        {"allowedCommands": ["echo"], "commandSubstitutionResponse": "deny"},
        "deny",
    )
    assert_reason_includes(result, CommandSubstitutionPresent())


def test_command_substitution_response_via_allowed_commands_checks_the_inner_command():
    """commandSubstitutionResponse: 'via-allowed-commands' continues evaluation,
    checking the inner (substituted) command against allowedCommands like any
    other invocation - denied here because `cat` is not allow-listed.
    """
    assert_decision(
        "echo $(cat /etc/passwd)",
        {"allowedCommands": ["echo"], "commandSubstitutionResponse": "via-allowed-commands"},
        "deny",
    )


def test_command_substitution_response_via_allowed_commands_allows_an_allow_listed_inner_command():
    """The canonical minimal shape for this knob: the inner program is
    allow-listed, so the recursion passes and the invocation allows.

    The entry declares `hasNoPathParameters` because that is what an entry
    must do to carry a substitution at all once every argument the parser
    cannot rule out counts as a path candidate (improvement-20260919-112214,
    second fix round). For `echo` the claim is true. This case is about the
    knob, so it takes the shortest honest route to reaching it; the
    consequence of NOT declaring it is pinned separately by
    `test_a_substitution_into_a_default_parser_slot_is_a_path_operand`.
    """
    assert_decision(
        "echo $(echo safe)",
        {
            "allowedCommands": [{"program": "echo", "hasNoPathParameters": True}],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "allow",
    )


def test_command_substitution_response_defaults_to_via_allowed_commands():
    """Omitting commandSubstitutionResponse entirely behaves exactly like the
    explicit 'via-allowed-commands' case above - it is the documented default.
    """
    assert_decision(
        "echo $(echo safe)",
        {"allowedCommands": [{"program": "echo", "hasNoPathParameters": True}]},
        "allow",
    )


# =============================================================================
# Batch 2: filters
# =============================================================================


def test_all_filters_on_an_entry_must_pass_for_the_entry_to_vouch():
    """Filters within one entry are AND-ed: the first one that rejects decides."""
    assert_decision(
        "echo --allowed-flag --forbidden-flag",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [
                        {"type": "optionPresent", "option": "--allowed-flag", "action": "required"},
                        {"type": "optionPresent", "option": "--forbidden-flag", "action": "block"},
                    ],
                }
            ]
        },
        "deny",
    )


def test_a_later_entry_can_vouch_for_what_an_earlier_entry_rejects():
    """Entries for the same program are OR-ed: one passing entry is enough.

    The first entry rejects (it requires a flag this invocation lacks), but the
    second vouches. This is what Flag List A1/A2 mean by "silently widens the
    allowlist under entry-level OR" - a broken entry that wrongly passes can
    never be vetoed by a stricter sibling.
    """
    assert_decision(
        "echo hi",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [{"type": "optionPresent", "option": "--required-flag", "action": "required"}],
                },
                {"program": "echo"},
            ]
        },
        "allow",
    )


def test_unknown_filter_action_is_rejected_at_config_load_time():
    """Flag List A1, layer 1. An action other than block/required must not load.

    Today all nine filter implementations end `return True` for an unrecognised
    action, so a typo ('blcok') silently turns a restriction into a no-op and
    widens the allowlist. Rejecting at load time gives the config author the
    error at the moment they can act on it.
    """
    with pytest.raises(ConfigError):
        decision_for(
            "echo hi",
            {
                "allowedCommands": [
                    {
                        "program": "echo",
                        "filters": [{"type": "optionPresent", "option": "--x", "action": "blcok"}],
                    }
                ]
            },
        )


def test_unknown_filter_type_is_rejected_at_config_load_time():
    """Flag List A2, layer 1. `create_filter` returns None for an unknown type
    and the match loop `continue`s past it, so a typo'd type REMOVES the
    restriction rather than failing.
    """
    with pytest.raises(ConfigError):
        decision_for(
            "echo hi",
            {
                "allowedCommands": [
                    {
                        "program": "echo",
                        "filters": [{"type": "optionPresnt", "option": "--x", "action": "block"}],
                    }
                ]
            },
        )


def test_a_filter_that_cannot_be_evaluated_fails_closed_at_match_time():
    """Flag List A1/A2, layer 2 - defense in depth for what load-time validation
    cannot catch.

    An unparsable regex is the reachable example: it is only discovered when the
    pattern is compiled against an argument. Today `re.error` is swallowed into
    `matched = False`, which for `action: "block"` means `not matched` -> the
    filter PASSES and the entry vouches. A filter that could not be evaluated
    must instead refuse to vouch.
    """
    assert_decision(
        "echo hi",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [{"type": "parameterRegex", "pattern": "[unclosed", "action": "block"}],
                }
            ]
        },
        "deny",
    )


def test_block_action_rejects_by_absence_when_the_index_is_out_of_bounds():
    """Flag List E5: a 'block' rule that blocks by ABSENCE.

    Both index filters `return False` (reject) when the index is out of bounds,
    so `action: "block"` on index 5 rejects a two-argument command - not because
    the forbidden pattern is present, but because there is nothing at that index
    to clear. Surprising, deliberate, and previously unasserted.
    """
    assert_decision(
        "echo one two",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [
                        {"type": "argumentAtIndex", "index": 5, "pattern": "^secret$", "action": "block"}
                    ],
                }
            ]
        },
        "deny",
    )


def test_blocked_commands_wins_over_allowed_commands_for_the_same_program():
    """Flag List E1: precedence is unambiguous in code but was never asserted."""
    assert_decision(
        "curl https://example.com",
        {"allowedCommands": ["curl"], "blockedCommands": ["curl"]},
        "deny",
    )


def test_an_entry_does_not_vouch_for_a_variable_it_has_not_declared():
    """Flag List B1: `onlyTheseVariables` is DENY-BY-DEFAULT, not a narrowing of a
    permissive default - the highest-severity naming defect in the config
    vocabulary. An entry that declares no variables vouches for no variables.
    """
    assert_decision(
        "echo $HOME",
        {"allowedCommands": [{"program": "echo"}]},
        "deny",
    )


def test_an_entry_vouches_for_a_variable_it_has_declared():
    """Declaring a variable via `onlyTheseVariables` and vouching for what
    its VALUE might be are two separate grants (see improvement-
    20260919-112214's Design Decisions, 'Whether onlyTheseVariables also
    grants filter opacity'). This case pins the first one, so it supplies
    the second explicitly rather than relying on it: `hasNoPathParameters`
    is true of `echo`, and is what lets `$HOME` sit in an argument slot
    without the containment check objecting that an unknowable value
    occupies a path operand.

    The two grants are visible as separate here precisely because removing
    either one denies, for a different reason."""
    assert_decision(
        "echo $HOME",
        {
            "allowedCommands": [
                {"program": "echo", "onlyTheseVariables": ["HOME"], "hasNoPathParameters": True}
            ]
        },
        "allow",
    )


def test_parameter_regex_filter_rejects_a_non_matching_parameter():
    assert_decision(
        "git push --force",
        {
            "allowedCommands": [
                {
                    "program": "git",
                    "filters": [{"type": "parameterRegex", "pattern": "--force", "action": "block"}],
                }
            ]
        },
        "deny",
    )


def test_match_full_parameter_does_not_reject_on_a_substring():
    """`matchFullParameter` matches a whole parameter where `parameterRegex`
    matches an unanchored substring - the distinction B6 flags as hidden in one
    adjective. `--force-with-lease` contains `--force` but is not equal to it.
    """
    assert_decision(
        "git push --force-with-lease",
        {
            "allowedCommands": [
                {
                    "program": "git",
                    "filters": [{"type": "matchFullParameter", "pattern": "--force", "action": "block"}],
                }
            ]
        },
        "allow",
    )


def test_parameter_regex_does_reject_on_that_same_substring():
    """The other half of the pair above: the unanchored default is what makes
    `parameterRegex` and `matchFullParameter` behave differently on one input.
    """
    assert_decision(
        "git push --force-with-lease",
        {
            "allowedCommands": [
                {
                    "program": "git",
                    "filters": [{"type": "parameterRegex", "pattern": "--force", "action": "block"}],
                }
            ]
        },
        "deny",
    )


def test_positional_arg_regex_ignores_options_when_matching():
    """`positionalArgRegex` sees only positionals, so an option that matches the
    pattern does not trigger it - the `argumentAtIndex` / `positionalArgAtIndex`
    distinction in B6, one filter family up.
    """
    assert_decision(
        "git commit --message=secret",
        {
            "allowedCommands": [
                {
                    "program": "git",
                    "filters": [{"type": "positionalArgRegex", "pattern": "secret", "action": "block"}],
                }
            ]
        },
        "allow",
    )


def test_positional_arg_at_index_required_allows_a_plain_matching_invocation():
    """Migrated from shfmt-permissions' (duplicate) `TestPositionalArgAtIndexFilter`
    (old test_positional_arg_at_index_required_matches, :1156). Every sibling
    filter type in this batch has a plain decision-level case; this one
    previously only had the substitution-shift edge cases above (B6/B7)."""
    config = {
        "allowedCommands": [
            {
                "program": "git",
                "filters": [
                    {"type": "positionalArgAtIndex", "index": 0, "pattern": "^commit$", "action": "required"}
                ],
            }
        ]
    }
    assert_decision("git commit", config, "allow")
    assert_decision("git push", config, "deny")


def test_positional_arg_at_index_counts_positionals_only_skipping_options():
    """Migrated from shfmt-permissions' (duplicate) `TestPositionalArgAtIndexFilter`
    (old test_positional_arg_at_index_second_positional, :1156): index 1 means
    the SECOND positional, not the second argument - a preceding option (`-r`)
    must not shift it."""
    config = {
        "allowedCommands": [
            {
                "program": "cp",
                "hasNoPathParameters": True,
                "filters": [{"type": "positionalArgAtIndex", "index": 1, "pattern": "^/tmp/", "action": "required"}],
            }
        ]
    }
    assert_decision("cp -r file.txt /tmp/dest", config, "allow")
    assert_decision("cp file.txt /etc/passwd", config, "deny")


def test_option_value_filter_rejects_a_disallowed_value():
    """An `optionValue` filter only sees a value if the entry's parser knows the
    option consumes one - hence the `structured` parser declaring `-m`.

    Without it the default parser hands `-m` an empty argument list and `wip`
    becomes a positional instead; see the next case for why that matters.
    """
    assert_decision(
        "git commit -m wip",
        {
            "allowedCommands": [
                {
                    "program": "git",
                    "commandParser": {"type": "structured", "options": [{"option": "-m", "arguments": 1}]},
                    "filters": [{"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}],
                }
            ]
        },
        "deny",
    )


def test_option_value_filter_naming_an_option_no_parser_consumes_is_a_config_error():
    """Flag List A6, surfaced while authoring this batch.

    The SAME filter without the structured parser is silently inert today: the
    default parser gives `-m` an empty argument list, the pattern matches
    nothing, and `action: "block"` therefore PASSES - the entry vouches for the
    very invocation the author wrote the filter to stop. No typo is involved, so
    A1/A2's type/action validation does not catch it.

    Rejecting at load time is the layer that can: whether an option consumes a
    value is knowable from the entry's own parser config, with no command in
    hand.
    """
    with pytest.raises(ConfigError):
        decision_for(
            "git commit -m wip",
            {
                "allowedCommands": [
                    {
                        "program": "git",
                        "filters": [
                            {"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}
                        ],
                    }
                ]
            },
        )


# -- double-quoted-argument blindness (improvement-20260918-205740) ---------
#
# Argument.text used to naively concatenate a word's top-level Parts, so a
# DblQuoted word (one top-level part carrying no Value of its own; its
# literal content sits one level deeper, in that part's own nested Parts)
# read as the empty string. The two cases below are false-ALLOWs this
# produced: a double quote alone defeated a block filter and desynchronised
# the substitution-shift bookkeeping from the parser's own classification.


def test_a_double_quoted_argument_cannot_evade_a_block_filter():
    """Finding 2: `rg --danger` and `rg '--danger'` both deny via the block
    filter below; before the Argument.text fix, `rg "--danger"` alone read
    as the empty string, the pattern never matched, and the block filter
    silently PASSED - one double quote defeated the rule."""
    config = {
        "allowedCommands": [
            {
                "program": "rg",
                "filters": [{"type": "argumentAtIndex", "index": 0, "pattern": "^--danger$", "action": "block"}],
            }
        ]
    }
    assert_decision("rg --danger", config, "deny")
    assert_decision("rg '--danger'", config, "deny")
    assert_decision('rg "--danger"', config, "deny")


def test_a_double_quoted_flag_ahead_of_a_substitution_does_not_miscount_positions():
    """Finding 4 / the _substitution_indices consistency gap: before the fix,
    the double-quoted `"--json"` read as "", which the default parser's
    dash-prefix heuristic then misclassified as a POSITIONAL rather than an
    option - shifting `expected` out of positional index 0 and wrongly
    denying a legitimate command the `required` filter should accept.
    `_substitution_indices` (allowed_command_policy.py) reads the same now-
    corrected `.text` directly, so its own dash-classification agrees with
    the parser automatically - no separate fix needed there.

    This is improvement-20260918-205740's own acceptance test for Finding 4.
    Its PROGRAM changed from `rg` to `echo` in improvement-20260919-112214's
    second fix round, and the change is deliberate: the mechanism under test
    is the parser's dash-classification of a double-quoted word and the
    index counting that follows from it, which is program-independent, but
    the fixture also needs an entry that may legitimately carry a
    substitution. `echo` takes no path operands, so `hasNoPathParameters`
    states a true fact; `rg` does take them, so the same flag on an `rg`
    entry would have been a false claim written to keep a test green. The
    `rg` shape's real verdict under the new rule is pinned right below.
    """
    assert_decision(
        'echo "--json" expected $(cat x)',
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "hasNoPathParameters": True,
                    "filters": [
                        {"type": "positionalArgAtIndex", "index": 0, "pattern": "^expected$", "action": "required"}
                    ],
                },
                "cat",
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "allow",
    )


def test_the_same_shape_denies_for_a_program_that_really_does_take_paths():
    """The other half of the fixture change above, kept visible rather than
    left implicit. Identical invocation shape, but `rg` genuinely takes path
    operands and its entry makes no claim otherwise, so `$(cat x)` lands in
    a slot the default parser cannot rule out and containment objects. The
    index filter is never reached - which is exactly why the case above had
    to move to a program that can honestly declare the flag it needs to
    ALLOW. (A flag that only isolates which objection fires first in a
    deny-expecting case is a different matter - see the knowability
    section's header note.)"""
    assert_decision(
        'rg "--json" expected $(cat x)',
        {
            "allowedCommands": [
                {
                    "program": "rg",
                    "filters": [
                        {"type": "positionalArgAtIndex", "index": 0, "pattern": "^expected$", "action": "required"}
                    ],
                },
                "cat",
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "deny",
    )


# =============================================================================
# Per-argument knowability (improvement-20260919-112214)
#
# Three concrete holes closed uniformly: a variable-bearing word was
# invisible to the unknowability rules entirely; the same intra-word fragment
# hole existed for substitutions on three non-index matchers; and
# `_substitution_indices`'s dash-prefix skip let an option-shaped word
# carrying unknowable content escape even the unconditional block rule.
#
# `hasNoPathParameters: True` appears throughout so these cases test their
# named filter mechanism rather than argument-path containment, which now
# also objects to unknowable content in a path operand (see that section
# below). Where the flag appears, one rule governs which program the fixture
# names, because the flag is a factual claim and a false one is exactly the
# defect this improvement's second fix round was reopened to remove:
#
#   - Where the flag is what MAKES the case ALLOW, the program must be one
#     that genuinely takes no path operands, so `echo`. A false claim doing
#     load-bearing work for a pass is a test lying to stay green.
#   - Where the case asserts a DENY, the flag only isolates which objection
#     fires first; it cannot manufacture the verdict. Those keep `rg`, whose
#     exact command shapes (`rg safe$HOME`, `rg --dang$X`, `rg safe$(echo
#     x)`, `rg --dang$(echo x)`) are the ones pinned as must-still-deny
#     across rounds and are deliberately left verbatim.
# =============================================================================


VARIABLE_FRAGMENT_REQUIRED_CASES = [
    "rg safe$HOME",
    'rg "safe$HOME"',
    "rg ${HOME}safe",
]


@pytest.mark.parametrize("command", VARIABLE_FRAGMENT_REQUIRED_CASES)
def test_a_variable_bearing_fragment_defeats_a_required_filter(command):
    """A literal sharing a word with a declared variable is a FRAGMENT, not
    the whole argument - `safe` plus whatever $HOME expands to. Presence is
    not provable from a fragment, however it is quoted or ordered relative
    to the variable. Before this fix, nothing threaded a variable's position
    the way a substitution's was threaded, so all three ALLOWED."""
    assert_decision(
        command,
        {
            "allowedCommands": [
                {
                    "program": "rg",
                    "onlyTheseVariables": ["HOME"],
                    "hasNoPathParameters": True,
                    "filters": [{"type": "parameterRegex", "pattern": "^safe$", "action": "required"}],
                }
            ]
        },
        "deny",
    )


def test_a_variable_bearing_fragment_defeats_a_block_filter():
    """The mirror bug: with `X` declared, `rg --dang$X` used to ALLOW against
    a block filter forbidding `--danger`, because nothing threaded the
    variable's position at all."""
    assert_decision(
        "rg --dang$X",
        {
            "allowedCommands": [
                {
                    "program": "rg",
                    "onlyTheseVariables": ["X"],
                    "hasNoPathParameters": True,
                    "filters": [{"type": "parameterRegex", "pattern": "^--danger$", "action": "block"}],
                }
            ]
        },
        "deny",
    )


def test_an_unquoted_variable_before_an_indexed_argument_defeats_a_required_index_filter():
    """The index-shift rule was missing for unquoted variables entirely - a
    pinned positional index stayed provable even though `$X` may expand to
    zero or several words, exactly the substitution-shift hole but for a
    variable instead."""
    assert_decision(
        "rg $X target",
        {
            "allowedCommands": [
                {
                    "program": "rg",
                    "onlyTheseVariables": ["X"],
                    "hasNoPathParameters": True,
                    "filters": [
                        {"type": "positionalArgAtIndex", "index": 1, "pattern": "^target$", "action": "required"}
                    ],
                }
            ]
        },
        "deny",
    )


SUBSTITUTION_FRAGMENT_REQUIRED_MATCHERS = [
    {"type": "parameterRegex", "pattern": "^safe$"},
    {"type": "matchFullParameter", "pattern": "safe"},
    {"type": "positionalArgRegex", "pattern": "^safe$"},
]


@pytest.mark.parametrize(
    "filter_kwargs", SUBSTITUTION_FRAGMENT_REQUIRED_MATCHERS, ids=[f["type"] for f in SUBSTITUTION_FRAGMENT_REQUIRED_MATCHERS]
)
def test_a_substitution_bearing_fragment_defeats_a_required_non_index_filter(filter_kwargs):
    """The same intra-word fragment hole as the variable case, for a
    substitution - even with the inner program allow-listed (so the
    via-allowed-commands recursion membership check cannot be what denies),
    `rg safe$(echo x)`'s real argument is `safe` plus whatever `echo x`
    expands to, not the bare literal `safe` the filter needs."""
    assert_decision(
        "rg safe$(echo x)",
        {
            "allowedCommands": [
                {
                    "program": "rg",
                    "hasNoPathParameters": True,
                    "filters": [dict(filter_kwargs, action="required")],
                },
                "echo",
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "deny",
    )


def test_a_dash_prefixed_substitution_defeats_the_unconditional_block_rule():
    """Finding 3 / the dash-skip bug: `_substitution_indices` used to
    `continue` past any argument starting with "-", so `rg --dang$(echo x)`
    (text "--dang") was invisible to the unknowability rules entirely and
    slipped even the unconditional block rule."""
    assert_decision(
        "rg --dang$(echo x)",
        {
            "allowedCommands": [
                {
                    "program": "rg",
                    "hasNoPathParameters": True,
                    "filters": [{"type": "optionPresent", "option": "--danger", "action": "block"}],
                },
                "echo",
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "deny",
    )


def test_option_present_required_denies_when_the_option_itself_is_unknowable():
    """The literal option text alone is a FRAGMENT of the real argument -
    `--dang$(echo x)` could expand to anything starting with `--dang`, not
    necessarily the bare `--dang` the filter requires. Reading its fragment
    text at face value (today's behaviour) wrongly proves presence; dropping
    the unknowable argument from the knowable-only re-parse denies it."""
    assert_decision(
        "rg --dang$(echo x)",
        {
            "allowedCommands": [
                {
                    "program": "rg",
                    "hasNoPathParameters": True,
                    "filters": [{"type": "optionPresent", "option": "--dang", "action": "required"}],
                },
                "echo",
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "deny",
    )


def test_dropping_an_unknowable_argument_lets_a_separate_literal_stay_provable():
    """The permissive-direction fix: today an unknowable word contributes ""
    to the joined text `parameterRegex`/`positionalArgRegex` search, so
    `echo safe $HOME` against `required ^safe$` joins to "safe " and wrongly
    DENIES even though the literal `safe` is complete and provable in its
    own, separate word. Dropping the unknowable argument entirely (rather
    than contributing "" in its place) makes this correctly ALLOW.

    Program is `echo` rather than `rg` because here `hasNoPathParameters` is
    what MAKES the case pass, so it has to be a true claim - see this
    section's header note."""
    assert_decision(
        "echo safe $HOME",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "onlyTheseVariables": ["HOME"],
                    "hasNoPathParameters": True,
                    "filters": [{"type": "parameterRegex", "pattern": "^safe$", "action": "required"}],
                }
            ]
        },
        "allow",
    )


def test_a_double_quoted_substitution_does_not_shift_a_pinned_index():
    """The one newly-ALLOWED shape (a deliberate relaxation, not a
    regression): a double-quoted substitution is guaranteed to be exactly
    one word by shell semantics, so - unlike an unquoted one - it must NOT
    shift a pinned index. Before this fix, `_substitution_indices` keyed
    off `contains_substitution` regardless of quoting, so this used to DENY
    exactly like the unquoted case."""
    assert_decision(
        'echo "$(echo one)" expected-second',
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "hasNoPathParameters": True,
                    "filters": [
                        {
                            "type": "positionalArgAtIndex",
                            "index": 1,
                            "pattern": "^expected-second$",
                            "action": "required",
                        }
                    ],
                }
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        },
        "allow",
    )


def test_an_entry_restricting_no_content_still_allows_a_variable_bearing_invocation():
    """No filters and a truthful `hasNoPathParameters` means there is no
    claim for unknowable content to invalidate - an entry that permits any
    arguments is not made less true by arguments it cannot see.

    Program is `echo` rather than `rg` because the flag is load-bearing for
    the ALLOW here, so it must be a fact rather than a convenience - see
    this section's header note."""
    assert_decision(
        "echo anything",
        {
            "allowedCommands": [
                {"program": "echo", "onlyTheseVariables": ["HOME"], "hasNoPathParameters": True}
            ]
        },
        "allow",
    )
    assert_decision(
        "echo safe$HOME",
        {
            "allowedCommands": [
                {"program": "echo", "onlyTheseVariables": ["HOME"], "hasNoPathParameters": True}
            ]
        },
        "allow",
    )


def test_a_single_quoted_look_alike_is_fully_knowable_and_not_defeated():
    """`'literal$X'` produces no expansion at all - single quotes prevent
    expansion entirely, so this is fully knowable and must not be treated as
    a fragment even though it contains a `$` character.

    Program is `echo` rather than `rg` for the same reason as its two
    neighbours above: the flag is what makes this ALLOW, so it has to be
    true."""
    assert_decision(
        "echo 'safe$X'",
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "hasNoPathParameters": True,
                    "filters": [{"type": "parameterRegex", "pattern": "^safe\\$X$", "action": "required"}],
                }
            ]
        },
        "allow",
    )


def _rg_knowability_config(matcher_type, matcher_kwargs, action):
    return {
        "allowedCommands": [
            {
                "program": "rg",
                "onlyTheseVariables": ["HOME"],
                "hasNoPathParameters": True,
                "filters": [dict(matcher_kwargs, type=matcher_type, action=action)],
            }
        ]
    }


# Table-driven matrix: every one of the (non-index-based, non-parser-specific)
# matcher types gets its OWN adjudicated case for both `required` and `block`
# next to a variable-bearing fragment, so no type reaches its verdict by
# generalisation from another. argumentAtIndex/positionalArgAtIndex are
# covered by the dedicated index-shift cases above; optionPresent is covered
# by the dash-prefix cases above (its "fragment" is the option name itself,
# not a regex pattern); optionValue/namedValue need a parser that populates
# an option value/named field at all, so they get their own dedicated cases
# below rather than a row in this table.
MATCHER_TYPE_KNOWABILITY_MATRIX = [
    ("parameterRegex", {"pattern": "^safe$"}),
    ("matchFullParameter", {"pattern": "safe"}),
    ("positionalArgRegex", {"pattern": "^safe$"}),
]


@pytest.mark.parametrize(
    "matcher_type, matcher_kwargs", MATCHER_TYPE_KNOWABILITY_MATRIX, ids=[m[0] for m in MATCHER_TYPE_KNOWABILITY_MATRIX]
)
def test_every_non_index_matcher_type_denies_its_own_required_fragment_case(matcher_type, matcher_kwargs):
    """The fragment `safe$HOME` visibly matches the pattern on its literal
    portion alone - the bug this closes is that today's engine reads that
    as PROVEN presence, when the real value is `safe` plus whatever $HOME
    expands to."""
    config = _rg_knowability_config(matcher_type, matcher_kwargs, "required")

    assert_decision("rg safe", config, "allow")
    assert_decision("rg safe$HOME", config, "deny")


@pytest.mark.parametrize(
    "matcher_type, matcher_kwargs", MATCHER_TYPE_KNOWABILITY_MATRIX, ids=[m[0] for m in MATCHER_TYPE_KNOWABILITY_MATRIX]
)
def test_every_non_index_matcher_type_denies_absence_next_to_its_own_block_fragment_case(matcher_type, matcher_kwargs):
    """`saf$HOME` deliberately does NOT match the pattern on its literal
    portion alone (`saf` != `safe`) - today's engine reads that as PROVEN
    absence and ALLOWS, when the real value could still be exactly `safe`
    if $HOME happens to expand to `e`. Using a fragment that already
    matches (`safe$HOME`) would deny for the coincidental reason that the
    visible literal alone satisfies the pattern, proving nothing about
    unknowability specifically."""
    config = _rg_knowability_config(matcher_type, matcher_kwargs, "block")

    assert_decision("rg safe", config, "deny")  # the real content is present: block correctly denies
    assert_decision("rg saf$HOME", config, "deny")  # unknowable: absence still not provable


def _git_commit_structured_config(filter_def):
    return {
        "allowedCommands": [
            {
                "program": "git",
                "onlyTheseVariables": ["HOME"],
                "hasNoPathParameters": True,
                "commandParser": {"type": "structured", "options": [{"option": "-m", "arguments": 1}]},
                "filters": [filter_def],
            }
        ]
    }


def test_option_value_required_denies_when_the_option_argument_is_a_fragment():
    """optionValue needs a parser that consumes a value for its option - the
    (pure) structured parser here, so this exercises the knowable-only
    RE-PARSE path rather than the external-parser fail-closed-with-no-reparse
    path (covered separately in test_allowed_command_policy.py)."""
    config = _git_commit_structured_config(
        {"type": "optionValue", "option": "-m", "pattern": "^safe$", "action": "required"}
    )

    assert_decision("git commit -m safe", config, "allow")
    assert_decision("git commit -m safe$HOME", config, "deny")


def test_option_value_block_denies_absence_next_to_a_fragment():
    """`w$HOME` deliberately does NOT match `^wip$` on its literal portion
    alone (`w` != `wip`) - a fragment that already fully matches (`wip$HOME`)
    would deny for the coincidental reason that the visible literal alone
    satisfies the pattern, proving nothing about unknowability specifically.
    """
    config = _git_commit_structured_config(
        {"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}
    )

    assert_decision("git commit -m dangerous", config, "allow")
    assert_decision("git commit -m w$HOME", config, "deny")


def test_named_value_required_denies_when_the_named_field_came_from_a_fragment(cwd_pinned_inside_project):
    """namedValue needs an external parser (only the command/provided route
    populates `named` at all) - this is also the external-parser direction
    of the required rule: no knowable-only re-parse is attempted, unknowable
    content simply defeats the filter (see the dedicated no-second-subprocess
    unit test in test_allowed_command_policy.py)."""
    with cwd_pinned_inside_project():
        fixtures = Path(__file__).parent / "fixtures" / "fake_parsers"
        config = {
            "allowedCommands": [
                {
                    "program": "my-tool",
                    "onlyTheseVariables": ["HOME"],
                    "hasNoPathParameters": True,
                    "commandParser": {"type": "command", "command": str(fixtures / "echoes_named_value.py")},
                    "filters": [{"type": "namedValue", "name": "echoed", "pattern": "^safe$", "action": "required"}],
                }
            ]
        }
        assert_decision("my-tool safe", config, "allow")
        assert_decision("my-tool safe$HOME", config, "deny")


def test_named_value_block_denies_absence_next_to_a_fragment(cwd_pinned_inside_project):
    """`danger$HOME` deliberately does NOT match `^dangerous$` on its literal
    portion alone (missing the `ous` suffix) - a fragment that already fully
    matches (`dangerous$HOME`) would deny for the coincidental reason that
    the visible literal alone satisfies the pattern, proving nothing about
    unknowability specifically."""
    with cwd_pinned_inside_project():
        fixtures = Path(__file__).parent / "fixtures" / "fake_parsers"
        config = {
            "allowedCommands": [
                {
                    "program": "my-tool",
                    "onlyTheseVariables": ["HOME"],
                    "hasNoPathParameters": True,
                    "commandParser": {"type": "command", "command": str(fixtures / "echoes_named_value.py")},
                    "filters": [{"type": "namedValue", "name": "echoed", "pattern": "^dangerous$", "action": "block"}],
                }
            ]
        }
        assert_decision("my-tool safe", config, "allow")
        assert_decision("my-tool dangerous", config, "deny")
        assert_decision("my-tool danger$HOME", config, "deny")


# -- argument-path containment (a security boundary, not a pattern assertion) -


PATH_CONTAINMENT_FRAGMENT_CASES = [
    "cat ./sub$ESC",
    "cat ./sub/$ESC",
    "cat ./a$ESC/b",
    'cat "./sub$ESC"',
]


@pytest.mark.parametrize("command", PATH_CONTAINMENT_FRAGMENT_CASES)
def test_argument_path_containment_fails_closed_next_to_unknowable_content(command, cwd_pinned_inside_project):
    """Path DETECTION runs on the fragment, so `./sub$ESC` resolves and
    checks `./sub` - comfortably inside the project - while the real path is
    whatever `$ESC` appends. An entry performing path validation cannot
    prove containment for an invocation carrying unknowable content, so it
    does not vouch - the blunt "any unknowable argument" rule, not a
    per-path one (see the improvement's Design Decisions)."""
    with cwd_pinned_inside_project():
        assert_decision(
            command,
            {"allowedCommands": [{"program": "cat", "onlyTheseVariables": ["ESC"]}]},
            "deny",
        )


def test_argument_path_containment_fails_closed_next_to_a_substitution_fragment_in_a_path_operand(cwd_pinned_inside_project):
    """The SUBSTITUTION axis of the rule PATH_CONTAINMENT_FRAGMENT_CASES above
    pins for variables - the suite was otherwise structurally blind to it
    (every existing path-containment case used `$ESC` plus
    `onlyTheseVariables`, the one axis with zero cost against the operator's
    live config; `commandSubstitutionResponse: via-allowed-commands` is the
    ordinary everyday shape there). `./sub$(echo x)`'s literal prefix `./sub`
    resolves and checks as a path comfortably inside the project, while the
    real value is whatever `echo x` appends - this must still deny even
    though the inner program is itself allow-listed."""
    with cwd_pinned_inside_project():
        assert_decision(
            "cat ./sub$(echo x)",
            {
                "allowedCommands": ["cat", "echo"],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "deny",
        )


def test_a_substitution_into_a_default_parser_slot_is_a_path_operand(cwd_pinned_inside_project):
    """SUPERSEDES a case that asserted the opposite (improvement-
    20260919-112214, second fix round). That case read `echo $(date)`
    against a BARE entry as allowed, on the reasoning that `$(date)`
    contributes no literal text so the default parser's heuristic detects no
    path candidate and containment has nothing to protect.

    Measurement refuted the reasoning behind that rule rather than its
    arithmetic: the same absence of a literal is what let `ls $(echo /etc)`,
    `cat $(echo ~/.ssh/id_rsa)` and `rg -f $(echo /etc/passwd) pattern`
    through, because one allow-listed string-producing program is enough to
    fill an empty-looking slot with an arbitrary absolute path at runtime.
    "The parser detected no path" was never evidence that no path was there;
    it was only evidence that the parser could not see one. A parser that
    rules nothing out rules nothing out."""
    with cwd_pinned_inside_project():
        assert_decision(
            "echo $(date)",
            {
                "allowedCommands": ["echo", "date"],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "deny",
        )


def test_an_honest_has_no_path_parameters_earns_a_substitution(cwd_pinned_inside_project):
    """The first of the three sanctioned ways to carry a substitution.
    `echo` takes no path operands, so the claim is factual and the entry
    genuinely has no containment question to answer. This is the flag's
    intended job restored: it earns substitutions by asserting something
    true about the program, rather than waiving a denial."""
    with cwd_pinned_inside_project():
        assert_decision(
            "echo $(date)",
            {
                "allowedCommands": [{"program": "echo", "hasNoPathParameters": True}, "date"],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "allow",
        )


def test_a_parser_that_classifies_the_slot_as_a_mode_earns_a_substitution(cwd_pinned_inside_project):
    """The second sanctioned way, and the reason parser quality is now the
    explicit currency. `chmod`'s bundled parser knows its first positional
    is a MODE, not a path, so an unknowable value there is not an unknowable
    path - while `bin/x`, the slot the parser does call a path, is knowable
    and contained. Nothing is waived: the entry makes no claim about paths
    at all, it simply has a parser good enough to answer the question."""
    with cwd_pinned_inside_project():
        assert_decision(
            "chmod $(echo 755) bin/x",
            {
                "allowedCommands": [
                    {"program": "chmod", "commandParser": {"type": "provided", "name": "chmod"}},
                    "echo",
                ],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "allow",
        )


def test_the_same_parser_still_denies_a_substitution_in_its_real_path_slot(cwd_pinned_inside_project):
    """The guard that keeps the case above from reading as "a provided
    parser waives containment". Same program, same parser, substitution
    moved from the mode slot into the path slot - which that parser DOES
    classify as a path - and it denies."""
    with cwd_pinned_inside_project():
        assert_decision(
            "chmod 755 $(echo bin/x)",
            {
                "allowedCommands": [
                    {"program": "chmod", "commandParser": {"type": "provided", "name": "chmod"}},
                    "echo",
                ],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "deny",
        )


# -- everything the default parser cannot rule out is a path operand --------
#
# improvement-20260919-112214, second fix round. The cases below were all
# ALLOWED before it, measured against the operator's real merged config.
# =============================================================================


SUBSTITUTION_REACHING_A_PATH_OPERAND_CASES = [
    "ls $(echo /etc)",
    "cat $(echo /etc/passwd)",
    "rg -f $(echo /etc/passwd) pattern",
    "ls --color=$(echo /etc)",
]


@pytest.mark.parametrize("command", SUBSTITUTION_REACHING_A_PATH_OPERAND_CASES)
def test_one_allow_listed_string_producer_cannot_fill_a_path_operand(command, cwd_pinned_inside_project):
    """The leak this round exists to close, and the reason the previous
    round's "denying this protects nothing" rationale was wrong. `echo` is
    allow-listed and produces arbitrary strings, so every one of these hands
    a path-taking entry an absolute path outside the project at runtime
    while presenting the engine with an empty or option-shaped fragment.
    None of these entries claims to take no paths, and none has a parser
    that classifies the slot, so all of them deny."""
    with cwd_pinned_inside_project():
        assert_decision(
            command,
            {
                "allowedCommands": ["ls", "cat", "rg", "echo"],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "deny",
        )


LITERAL_PATH_INSIDE_AN_OPTION_CASES = [
    "ls --color=/etc",
    "ls --color=/etc/passwd",
    "rg --file=/etc/passwd pattern",
]


@pytest.mark.parametrize("command", LITERAL_PATH_INSIDE_AN_OPTION_CASES)
def test_an_option_shaped_word_cannot_smuggle_a_literal_path_out_of_the_project(
    command, cwd_pinned_inside_project
):
    """The LITERAL twin of the substitution cases above, with no unknowable
    content anywhere - measured as ALLOW before this round.

    The default parser routed every dash-prefixed word to `options` and only
    ever ran path detection over `positionals`, so an absolute path riding
    inside `--name=value` was never examined at all. This is why the fix had
    to reach the parser rather than only the unknowability layer: the
    substitution versions were the flavoured case of a hole that was already
    open to a plain literal."""
    with cwd_pinned_inside_project():
        assert_decision(
            command,
            {"allowedCommands": ["ls", "rg"]},
            "deny",
        )


def test_a_pattern_slot_is_not_a_path_operand_even_when_its_value_is_unknowable(cwd_pinned_inside_project):
    """The other direction, and the incoherence this round removes: before
    it, `head -5 $(echo README.md)` allowed while `cat -n $(echo README.md)`
    denied - same intent, opposite verdicts, decided by nothing but which
    entry happened to have a parser. Now the verdict follows the parser's
    actual knowledge: grep's bundled parser knows positional 0 is the
    PATTERN, so an unknowable value there is not an unknowable path."""
    with cwd_pinned_inside_project():
        assert_decision(
            "grep $(echo mypattern) README.md",
            {
                "allowedCommands": [
                    {"program": "grep", "commandParser": {"type": "provided", "name": "grep"}},
                    "echo",
                ],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "allow",
        )


def test_an_unknowable_path_operand_is_reported_as_its_own_fact(cwd_pinned_inside_project):
    """The denial names what is actually true. `ArgumentPathOutsideAllowed
    Paths` would claim the engine resolved a path and found it outside the
    boundary; here no path can be named at all, which is a different fact
    and carries a different fix (substitute the real value, or use an entry
    that legitimately declares it takes no paths)."""
    with cwd_pinned_inside_project():
        result = assert_decision(
            "ls $(echo /etc)",
            {
                "allowedCommands": ["ls", "echo"],
                "commandSubstitutionResponse": "via-allowed-commands",
            },
            "deny",
        )
        assert_reason_includes(result, UnknowablePathArgument("ls"))


# =============================================================================
# Batch 3: paths and redirects
#
# EVERY case in this batch pins cwd explicitly via `cwd_pinned_inside_project`.
# Flag List F1: a green tilde-redirect test in the old suite was green for an
# ARTEFACTUAL reason - pytest's cwd differed from CLAUDE_PROJECT_DIR in that
# test, while in production the same command was ALLOWED. Inheriting pytest's
# working directory is how that false confidence was manufactured.
# =============================================================================


REDIRECTS_THAT_MUST_DENY = [
    # Confirmed by execution against the live engine to be ALLOWED today,
    # purely because of quoting style - the four bugs this batch exists for.
    'cat ./README.md > "/etc/passwd"',
    'echo x > "$HOME/.bashrc"',
    "echo x >> ~/.ssh/authorized_keys",
    "cat < ~/.ssh/id_rsa",
    # The equivalents that do NOT silently allow today - included so the
    # specification states the whole property, not only the broken half.
    # Measured 2026-09-16: with pathValidationResponse unset these two
    # PASSTHROUGH (the knob's old default), and only DENY when it is explicitly
    # set to "deny". Under the new model both collapse to deny regardless, which
    # is the point - but "they already deny" was too strong a claim to leave.
    "cat ./README.md > '/etc/passwd'",
    "cat ./README.md > /etc/passwd",
]


@pytest.mark.parametrize("command", REDIRECTS_THAT_MUST_DENY)
def test_a_redirect_leaving_the_project_is_denied_whatever_its_quoting(command, cwd_pinned_inside_project):
    """Quoting style must not change where a redirect is allowed to point.

    Today it does: double-quoted targets extract as the empty string and
    tilde targets are never expanded, so four of these six are auto-approved
    while their bare and single-quoted equivalents deny. An allow-listed
    command can therefore be made to write anywhere by adding quotes.
    """
    with cwd_pinned_inside_project():
        assert_decision(command, {"allowedCommands": ["cat", "echo"]}, "deny")


def test_an_unresolvable_redirect_target_is_denied_never_resolved_to_cwd(cwd_pinned_inside_project):
    """Flag List F2, stated as a named property.

    An empty or unresolvable extracted target must be treated as unresolvable
    and DENIED. The failure mode it guards against is silent: an empty string
    resolves to cwd, cwd sits inside an allowed prefix, and the redirect is
    approved as though it pointed somewhere harmless.

    Leaf 20260914-213652 hand-back: extraction should ALSO be reachable as an
    independently assertable property rather than only through a full
    `decision_for` call - this suite can only reach it through the entrypoint.
    """
    with cwd_pinned_inside_project():
        assert_decision('cat ./README.md > ""', {"allowedCommands": ["cat"]}, "deny")


def test_a_double_quoted_path_argument_cannot_evade_the_project_containment_check(cwd_pinned_inside_project):
    """Finding 3, the double-quote analogue of PATH_NORMALISATION_CASES's
    plain '/not-allowed.txt' deny case below. Before the Argument.text fix,
    the quoted form read as the empty string, `DefaultParser._detect_paths`
    skips an empty value entirely, and the argument-path containment check
    never even saw a path to reject - a double quote alone let an
    allow-listed command read/write anywhere.
    """
    with cwd_pinned_inside_project():
        assert_decision('cat "/not-allowed.txt"', {"allowedCommands": ["cat"]}, "deny")


def test_a_double_quoted_redirect_outside_the_project_denies_naming_the_real_path(cwd_pinned_inside_project):
    """Reason-fidelity strengthening for REDIRECTS_THAT_MUST_DENY's first two
    cases: before the Redirect.target_text fix, both denied via the WRONG
    mechanism - an empty/unresolvable target, coincidentally caught by
    test_an_unresolvable_redirect_target_is_denied_never_resolved_to_cwd's
    own 'empty target must deny' property, naming target_text="" in the
    Reason rather than the real path being written to. Same deny OUTCOME
    after the fix (asserted again here for clarity), now naming the real
    resolved-looking path. The truly-empty `> ""` case in that sibling test
    has no literal content to recover and remains unaffected by this fix.
    """
    with cwd_pinned_inside_project():
        result = assert_decision('cat ./README.md > "/etc/passwd"', {"allowedCommands": ["cat"]}, "deny")
        assert_reason_includes(result, RedirectOutsideAllowedPaths("/etc/passwd"))

        result = assert_decision('echo x > "$HOME/.bashrc"', {"allowedCommands": ["echo"]}, "deny")
        assert_reason_includes(result, RedirectOutsideAllowedPaths("/.bashrc"))


def test_a_sensitive_path_is_denied_wherever_it_appears(cwd_pinned_inside_project):
    """Flag List C3: sensitivePaths hard-denies rather than being inert unless
    opted into, and applies to any literal in the command, not only to paths a
    parser classified as such.
    """
    with cwd_pinned_inside_project():
        result = assert_decision(
            "cat /etc/passwd",
            {"allowedCommands": ["cat"], "sensitivePaths": ["/etc/passwd"]},
            "deny",
        )
        assert_reason_includes(result, SensitivePathReferenced("/etc/passwd"))


def test_sensitive_path_matching_is_substring_and_deliberately_over_matches(cwd_pinned_inside_project):
    """Flag List D1, the false-positive direction - the half no current test
    distinguishes.

    `/home/me/etc/passwd-backup` is an unrelated file that merely CONTAINS the
    string `/etc/passwd`, and it is denied. That is intentional catch-everything
    breadth for a denylist, not a defect: specified explicitly so a later reader
    cannot "fix" it into prefix or exact matching without re-adjudicating.
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "cat /home/me/etc/passwd-backup",
            {"allowedCommands": ["cat"], "sensitivePaths": ["/etc/passwd"]},
            "deny",
        )


def test_a_path_under_an_additional_allowed_prefix_is_permitted(cwd_pinned_inside_project, tmp_path):
    """Flag List B2: `additionalAllowedPathPrefixes` is FILESYSTEM path prefixes.

    Both blind readings of the name - "command-line prefix" and "wrapper
    program" - were wrong, so the specification pins the real meaning. Kept
    free of `..` on purpose: traversal is its own property, pinned separately
    by the normalisation cases below.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()

    with cwd_pinned_inside_project(project_dir=project_dir):
        assert_decision(
            f"cat {shared_dir}/notes.txt",
            {"allowedCommands": ["cat"], "additionalAllowedPathPrefixes": [str(shared_dir)]},
            "allow",
        )


# Each entry is (path as written on the command line, expected decision).
# `{project}` is substituted with the pinned CLAUDE_PROJECT_DIR at run time.
PATH_NORMALISATION_CASES = [
    ("/not-allowed.txt", "deny"),          # absolute, plainly outside
    ("relative-to-project.txt", "allow"),  # relative, resolves inside
    ("{project}/file.txt", "allow"),       # absolute, inside
    ("{project}/../file.txt", "deny"),     # absolute, but traverses back out
    ("../file.txt", "deny"),               # relative, traverses out
]


@pytest.mark.parametrize("path_template,expected", PATH_NORMALISATION_CASES)
def test_argument_paths_are_judged_after_normalisation(
    path_template, expected, cwd_pinned_inside_project
):
    """Containment is decided on the RESOLVED path, not the written one.

    The two `..` cases are the point: both are written to look like paths the
    project owns, and both land outside it. A check that compared the string as
    written would admit either. Specified explicitly rather than as a side
    effect of some other case, so a regression names this property directly.
    """
    with cwd_pinned_inside_project() as project_dir:
        path = path_template.format(project=project_dir)

        assert_decision(f"cat {path}", {"allowedCommands": ["cat"]}, expected)


def test_an_additional_allowed_prefix_does_not_match_a_longer_sibling_directory(cwd_pinned_inside_project):
    """Flag List E8: the near-miss guard exists but was never asserted.

    `/home/user` must not admit `/home/username`. The guard is one `+ os.sep`
    in the prefix comparison; without a test, a refactor that drops it fails
    open and silently widens every prefix to its sibling directories.
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "cat /home/username/secret.txt",
            {"allowedCommands": ["cat"], "additionalAllowedPathPrefixes": ["/home/user"]},
            "deny",
        )


def test_entry_level_path_validation_false_disables_only_the_argument_path_check(cwd_pinned_inside_project):
    """Flag List B4, part 1. RENAMED: `pathValidation: false` becomes
    `hasNoPathParameters: true`.

    The old name promised to switch off "path validation" wholesale and
    delivered something much narrower, which is the defect. The new name states
    a FACT ABOUT THE ENTRY - this program takes no path parameters - from which
    skipping the argument-path check follows, and which says nothing about
    redirects or the paths filter because it makes no claim about them.

    POLARITY INVERTS with the rename: the disabling value is now `true`, since
    the sentence being asserted is "there are no path parameters here".
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "cat /somewhere/outside/the/project.txt",
            {"allowedCommands": [{"program": "cat", "hasNoPathParameters": True}]},
            "allow",
        )


def test_entry_level_path_validation_false_does_not_disable_redirect_validation(cwd_pinned_inside_project):
    """Flag List B4, part 2 - the half the OLD name hid.

    Redirect-target validation is an INDEPENDENT mechanism guarding where the
    calling shell writes, not where the command's arguments point. An entry
    declaring it has no path PARAMETERS has said nothing about redirects, so it
    must not gain the ability to redirect anywhere.
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "cat ./README.md > /etc/passwd",
            {"allowedCommands": [{"program": "cat", "hasNoPathParameters": True}]},
            "deny",
        )


def test_entry_level_path_validation_false_does_not_disable_the_paths_filter(cwd_pinned_inside_project):
    """Flag List B4, part 3. The `paths` filter is a third independent
    mechanism; `hasNoPathParameters: true` does not switch it off either. An
    entry can truthfully declare its own parameters are not paths while a
    `paths` filter still constrains what it may touch.
    """
    with cwd_pinned_inside_project() as project_dir:
        assert_decision(
            "cat /somewhere/outside/the/project.txt",
            {
                "allowedCommands": [
                    {
                        "program": "cat",
                        "hasNoPathParameters": True,
                        "filters": [{"type": "paths", "exactly": [f"{project_dir}/README.md"]}],
                    }
                ]
            },
            "deny",
        )


def test_the_paths_filter_rejection_does_not_borrow_prefix_vocabulary(cwd_pinned_inside_project):
    """Flag List D5: today the `paths` filter's rejection message talks about
    prefixes, though the filter has no prefixes - it matches an `exactly` list.
    A reader who follows that hint goes looking for a prefix setting to widen
    and finds none.

    Reason objects carry facts, never prose (leaf 20260915-010959) - a
    `FilterRejected` names only `program`/`filter_type`, so this concern is
    now structurally impossible for the Reason itself; what remains testable
    is that the single renderer's own prose for it stays prefix-free too.

    `hasNoPathParameters` is set so the entry's OWN argument-path check (a
    genuinely prefix-based check, unrelated to this filter) is disabled -
    otherwise that check rejects the invocation first (`/somewhere/else.txt`
    is outside the project either way) and the `paths` filter is never even
    reached, leaving this case exercising the wrong mechanism entirely.
    """
    with cwd_pinned_inside_project() as project_dir:
        result = decision_for(
            "cat /somewhere/else.txt",
            {
                "allowedCommands": [
                    {
                        "program": "cat",
                        "hasNoPathParameters": True,
                        "filters": [{"type": "paths", "exactly": [f"{project_dir}/README.md"]}],
                    }
                ]
            },
        )

        assert result.decision == "deny"
        assert_reason_includes(result, FilterRejected("cat", "paths"))
        assert "prefix" not in render(result.reason).lower(), (
            f"paths-filter rejection borrowed the prefix vocabulary: {result.reason}"
        )


def test_a_relative_paths_filter_entry_resolves_against_the_project_not_the_process_cwd(
    cwd_pinned_inside_project, tmp_path
):
    """Flag List D4: adjudicated a BUG, specified here as the intended behaviour.

    Every other path mechanism in the engine anchors on CLAUDE_PROJECT_DIR, so
    a relative `exactly` entry must too. This is the one case that deliberately
    pins cwd and CLAUDE_PROJECT_DIR to DIFFERENT directories - resolving against
    the process cwd would make the filter's meaning depend on where the user
    happened to be standing.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    with cwd_pinned_inside_project(project_dir=project_dir, cwd=elsewhere):
        assert_decision(
            f"cat {project_dir}/notes.txt",
            {
                "allowedCommands": [
                    {"program": "cat", "filters": [{"type": "paths", "exactly": ["notes.txt"]}]}
                ]
            },
            "allow",
        )


# =============================================================================
# Batch 3b: symlink resolution (improvement-20260918-185726)
#
# Confirmed false-ALLOW: PathResolutionContext.absolute_path_of resolved a
# candidate path lexically only (os.path.normpath), so a project-local
# symlink pointing outside the boundary was never caught - the literal
# traversal denied, the symlinked equivalent silently allowed. Every case
# below uses a REAL symlink under tmp_path (the deliberate exception to this
# suite's fake-predicate discipline - see the improvement file's
# Implementation Notes: the thing under test is real filesystem behaviour).
# =============================================================================


def test_a_redirect_through_a_symlink_leaving_the_project_is_denied(cwd_pinned_inside_project, tmp_path):
    """The reported false-ALLOW, reproduced and pinned: `escape -> ../outside`
    then `echo hi > escape/pwned.txt` must now deny identically to the
    already-denied literal traversal `echo hi > ../outside/pwned.txt`.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project_dir / "escape").symlink_to(outside)

    with cwd_pinned_inside_project(project_dir=project_dir):
        result = assert_decision("echo hi > escape/pwned.txt", {"allowedCommands": ["echo"]}, "deny")
        assert_reason_includes(result, RedirectOutsideAllowedPaths("escape/pwned.txt"))


def test_an_argument_path_through_a_symlink_leaving_the_project_is_denied(cwd_pinned_inside_project, tmp_path):
    """The mirror case for `allowedCommands` argument-path validation - the
    fix lives at the shared seam, not the redirect policy alone, so this
    pins the breadth directly rather than inferring it from the case above.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "passwd").write_text("secret")
    (project_dir / "escape").symlink_to(outside)

    with cwd_pinned_inside_project(project_dir=project_dir):
        result = assert_decision("cat escape/passwd", {"allowedCommands": ["cat"]}, "deny")
        assert_reason_includes(result, ArgumentPathOutsideAllowedPaths("cat", str(outside / "passwd")))


def test_paths_filter_matches_a_declared_path_reached_through_a_symlink(cwd_pinned_inside_project, tmp_path):
    """Proves the fix reaches `PathsFilter` too, not only redirect/argument-
    path validation: the filter's `exactly` entry is declared as the REAL
    (post-symlink) path, the command reaches it through the symlink, and
    both now resolve to the same absolute path via the shared
    `absolute_path_of` seam.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("hi")
    (project_dir / "escape").symlink_to(outside)

    with cwd_pinned_inside_project(project_dir=project_dir):
        assert_decision(
            "cat escape/notes.txt",
            {
                "allowedCommands": [
                    {
                        "program": "cat",
                        "hasNoPathParameters": True,
                        "filters": [{"type": "paths", "exactly": [str(outside / "notes.txt")]}],
                    }
                ]
            },
            "allow",
        )


def test_a_redirect_through_a_dangling_symlink_does_not_raise(cwd_pinned_inside_project):
    """A dangling symlink must not blow up the decision - `os.path.realpath`
    (non-strict) resolves it to its nonexistent target with no exception
    (confirmed live, see the improvement's Assumptions); nothing in this
    engine special-cases it.
    """
    with cwd_pinned_inside_project() as project_dir:
        (project_dir / "dangling").symlink_to(project_dir / "does-not-exist")

        result = decision_for("echo hi > dangling/pwned.txt", {"allowedCommands": ["echo"]})

        assert result.decision in ("allow", "deny")


def test_a_redirect_through_a_two_node_symlink_loop_does_not_raise(cwd_pinned_inside_project):
    """A two-node loop (`a -> b -> a`) must not blow up the decision either -
    non-strict `os.path.realpath` returns a stable path rather than raising.
    """
    with cwd_pinned_inside_project() as project_dir:
        (project_dir / "a").symlink_to(project_dir / "b")
        (project_dir / "b").symlink_to(project_dir / "a")

        result = decision_for("echo hi > a/pwned.txt", {"allowedCommands": ["echo"]})

        assert result.decision in ("allow", "deny")


def test_a_redirect_through_a_self_referencing_symlink_does_not_raise(cwd_pinned_inside_project):
    """A symlink pointing at itself (`a -> a`) is the third shape the
    Assumptions section confirmed live: no exception, even with a further
    child path component appended.
    """
    with cwd_pinned_inside_project() as project_dir:
        (project_dir / "self_link").symlink_to(project_dir / "self_link")

        result = decision_for("echo hi > self_link/pwned.txt", {"allowedCommands": ["echo"]})

        assert result.decision in ("allow", "deny")


# =============================================================================
# Batch 4: wrappers and command propagation
#
# Config-shape note: nested (wrapper sub-command) evaluation is an ORDINARY
# FILTER, `{"type": "nestedCommand"}`, not an entry-level key. This SUPERSEDES
# this leaf's own B5 rename (`propagate` -> `evaluateNamedValueAsCommand`),
# settled by the user during leaf 20260914-213652's planning on 2026-09-16.
#
# The point of the reshape is composition: filters already AND-compose within an
# entry and OR-compose across entries, so nested evaluation inherits both instead
# of running a parallel opt-in mechanism beside them. The filter needs no key
# naming what to read - sub-commands arrive on the parser's dedicated
# sub-command channel, so there is nothing left to point at.
#
# Converting old-format configs is the migration skill's job (leaf
# 20260915-011123); the engine carries no back-compat shim.
# =============================================================================


def wrapper_config(program, blocked=(), parser_name=None):
    """Config for a wrapper whose inner command is evaluated as a command.

    The xargs/sh -c/env/timeout family all need the same shape - a parser that
    publishes the inner command as a named value, plus the entry declaring that
    the named value is itself a command. `parser_name` selects a BUNDLED parser;
    see `script_parser_config` for the user-supplied route.
    """
    return {
        "allowedCommands": [
            {
                "program": program,
                "commandParser": {"type": "provided", "name": parser_name or program},
                "filters": [{"type": "nestedCommand"}],
            }
        ],
        "blockedCommands": list(blocked),
    }


def script_parser_config(program, script, blocked=()):
    """Config for a USER-SUPPLIED parser script - the external-script route.

    Distinct from `wrapper_config` on purpose: this is the public extensibility
    feature (a config author writes their own parser for a command the plugin
    does not bundle), not a bundled parser reached by name.
    """
    parser = {"type": "command", "command": script}

    return {
        "allowedCommands": [
            {
                "program": program,
                "commandParser": parser,
                "filters": [{"type": "nestedCommand"}],
            }
        ],
        "blockedCommands": list(blocked),
    }


def test_wrapper_config_builder_produces_the_shape_the_cases_rely_on():
    """Guards the two builders above - a silent shape drift would weaken every
    wrapper case at once while leaving them all still RED and so still "expected".
    """
    entry = wrapper_config("xargs", blocked=["rm"])["allowedCommands"][0]

    assert entry["program"] == "xargs"
    assert entry["commandParser"] == {"type": "provided", "name": "xargs"}
    assert entry["filters"] == [{"type": "nestedCommand"}]
    assert wrapper_config("xargs", blocked=["rm"])["blockedCommands"] == ["rm"]


def test_script_parser_config_builder_points_at_the_external_script_route():
    entry = script_parser_config("my-custom-tool", script="./my_parser.sh")["allowedCommands"][0]

    assert entry["commandParser"] == {"type": "command", "command": "./my_parser.sh"}
    assert entry["filters"] == [{"type": "nestedCommand"}]


def wrapper_wrapping_allowed_program(program, inner_program, parser_name=None):
    """`wrapper_config()` plus the WRAPPED program itself allow-listed.

    `wrapper_config()` only ever allow-lists the wrapper - every "wrapped
    ALLOWED command is allowed" case additionally needs the inner program
    admitted, and the four wrapper cases that must agree on this shape would
    otherwise each inline the same addition, inviting drift between them.
    """
    config = wrapper_config(program, parser_name=parser_name)
    config["allowedCommands"].append(inner_program)
    return config


def test_a_propagated_command_is_checked_against_blocked_commands():
    """Flag List D3 / the xargs hole. `xargs` is allow-listed, `rm` is not the
    invoked program - it arrives as the wrapper's trailing positionals - so
    without propagation `blockedCommands: ["rm"]` never fires.

    RED for TWO reasons until the stream completes: `decision_for` is unwired,
    and the xargs parser artifact itself is leaf 20260914-213502's to build.
    This leaf only specifies the expected outcome.
    """
    assert_decision(
        "find . -name '*.tmp' | xargs rm",
        wrapper_config("xargs", blocked=["rm"]),
        "deny",
    )


def test_a_propagated_command_is_checked_against_blocked_commands_with_every_outer_program_allow_listed():
    """Companion to the case above, isolating the mechanism it cannot prove on
    its own: there, `find` is not allow-listed either, so the command would
    deny even if propagation into the blocked `rm` were entirely broken.
    Allow-listing `find` too removes that confound - the ONLY remaining
    possible source of denial is propagation reaching the blocked `rm`.

    Added BESIDE the original case, never replacing it - the original spec's
    assertions are authority (it is authored-ahead), so this is a new case,
    not a fix to an existing one.
    """
    config = wrapper_config("xargs", blocked=["rm"])
    config["allowedCommands"].append("find")

    result = assert_decision("find . -name '*.tmp' | xargs rm", config, "deny")
    assert_reason_includes(result, FilterRejected("xargs", "nestedCommand"))


def test_an_external_script_parser_can_publish_a_command_that_reaches_blocked_commands():
    """The external-script CommandParser contract, pinned as a FIRST-CLASS case.

    A config author points `commandParser` at their own script; the engine runs
    it as a subprocess and trusts its JSON `named` output (Flag List F5: no
    schema validation, `named` is unvalidated pass-through). The published value
    is then consumed by the entry's `nestedCommand` filter, re-enters the
    decision pipeline as a command in its own right, and hits `blockedCommands`.

    This is a public extensibility feature, not an implementation detail: users
    must be able to write parsers for commands the plugin does not bundle. Leaf
    20260914-213502 MUST keep this route open when it rebuilds the Parser family
    as value objects - its Interface has to confirm it did.
    """
    assert_decision(
        "my-custom-tool --frobnicate x",
        script_parser_config("my-custom-tool", script="./my_parser.sh", blocked=["rm"]),
        "deny",
    )


def test_an_entry_whose_nested_command_filter_has_nothing_to_check_does_not_match():
    """Flag List A3/D6, adjudicated: FAIL CLOSED. Property survives the reshape
    from entry key to filter unchanged; only the config shape asserting it moved.

    Today `_handle_propagate` returns None when nothing is extracted and
    evaluation simply continues - so the entry vouches for a command whose inner
    command it never saw. The only protection is a hand-written "safety belt"
    filter the config author must remember to add. A `nestedCommand` filter with
    nothing to check must simply not pass, which retires that idiom - and as an
    ordinary filter it fails the entry the same way any other failing filter
    does, with no special-casing.

    Retargeted (leaf 20260918-223632) onto `nix-shell` with no `--run`/
    `--command` - bare `xargs` no longer illustrates "nothing to check" now
    that its parser exists, since it publishes its own known default
    (`echo`) rather than nothing; see the restated bare-`xargs` case below
    for what that now tests instead. A bare `nix-shell` genuinely publishes
    nothing (Design Decisions: "no command is going to run" is knowable and
    honestly represented as an absent `nestedCommands` key), so it is the
    wrapper this property should be pinned against.
    """
    assert_decision("nix-shell", wrapper_config("nix-shell"), "deny")


def test_bare_xargs_with_its_known_default_allow_listed_is_allowed():
    """What bare `xargs` now actually tests, once `parsers/xargs.py` exists:
    it publishes its own documented default (`echo`) rather than nothing - a
    KNOWN result, unlike bare `nix-shell` above. Once that default is itself
    allow-listed, propagation must let it through - proving the known-default
    case genuinely works end to end, not merely that it stopped crashing.
    """
    assert_decision("xargs", wrapper_wrapping_allowed_program("xargs", "echo"), "allow")



def test_a_nested_command_filter_composes_with_other_filters_across_entries():
    """The reason nested evaluation became a filter rather than an entry key.

    Two entries for one program, OR-ed: the first vouches outright when
    `--dry-run` is present, the second applies the nested check otherwise. A
    dry run is inert whatever it wraps, so it needs no nested evaluation - and
    expressing that takes no new machinery, because a filter composes where a
    parallel entry-level opt-in would not.
    """
    config = {
        "allowedCommands": [
            {
                "program": "xargs",
                "commandParser": {"type": "provided", "name": "xargs"},
                "filters": [{"type": "optionPresent", "option": "--dry-run", "action": "required"}],
            },
            {
                "program": "xargs",
                "commandParser": {"type": "provided", "name": "xargs"},
                "filters": [{"type": "nestedCommand"}],
            },
        ],
        "blockedCommands": ["rm"],
    }

    assert_decision("xargs --dry-run rm ./build", config, "allow")
    assert_decision("xargs rm ./build", config, "deny")


def test_a_nested_command_filter_needs_a_parser_that_publishes_sub_commands():
    """The A6 pattern, one filter family over: a filter is only as capable as
    the parser feeding it.

    Neither the default nor the structured parser can publish on the
    sub-command channel, so a `nestedCommand` filter beside one can never have
    anything to check and would deny every invocation forever. Rejected at load
    time for the same reason A6 is - the parser's own config says so, with no
    command in hand.
    """
    with pytest.raises(ConfigError):
        decision_for(
            "xargs rm ./build",
            {
                "allowedCommands": [
                    {
                        "program": "xargs",
                        "commandParser": {"type": "structured", "options": []},
                        "filters": [{"type": "nestedCommand"}],
                    }
                ],
                "blockedCommands": ["rm"],
            },
        )

def test_a_named_value_filter_constrains_what_a_parser_published(cwd_pinned_inside_project):
    """`namedValue` is the only filter family that reads parser output, so it
    could not appear in batch 2 - it needs a parser that populates `named`.
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "my-custom-tool --frobnicate x",
            {
                "allowedCommands": [
                    {
                        "program": "my-custom-tool",
                        "commandParser": {"type": "command", "command": "./my_parser.sh"},
                        "filters": [
                            {"type": "namedValue", "name": "command", "pattern": "^rm ", "action": "block"}
                        ],
                    }
                ]
            },
            "deny",
        )


# NOTE (leaf 20260915-010959): this suite previously carried three
# `commandParser.fallback` cases here (deny/legacy/an unrecognised value).
# Leaf 20260914-213502 permanently removed that knob before this leaf started
# - `CommandParser.from_definition` reads no `fallback` key at all; deny+hint
# is a constant the pipeline applies whenever the external-parser factory
# yields None (see command_parser.py's own docstring). The three cases were
# STALE, not failing-by-design: they asserted a feature a completed,
# binding prerequisite leaf had already deleted, so they carried noise in the
# red set rather than constraining anything. Deleted rather than re-authored,
# since there is no replacement behaviour left to specify.


# =============================================================================
# StructuredParser path candidacy (improvement-20260920-131722)
#
# StructuredParser used to guess with a shape heuristic for any positional not
# named in `pathPositionals`, and only ever populated `paths_for_validation`
# for an option's consumed value when the option was named in `pathOptions` -
# both are the same "does this look path-shaped" exemption DefaultParser lost
# in improvement-20260919-112214, so attaching a structured parser was
# measurably WEAKER than attaching no parser at all. The new per-slot
# `options`/`positionals` declaration schema closes that: every slot is a path
# candidate for validation unless a declaration says `path: false`.
# `paths_for_filtering` deliberately does not follow - it keeps the shape
# heuristic for undeclared positionals, because `PathsFilter`'s `exactly`
# semantics wants a precise set, not a conservative one.
# =============================================================================


HEADLINE_STRUCTURED_PARSER_CASES = [
    ("tool $(echo /etc/passwd)", {}),
    ("tool --colors=/etc/passwd", {}),
    ("tool --colors /etc/passwd", {"options": [{"option": "--colors", "arguments": 1}]}),
]


@pytest.mark.parametrize("command,parser_definition", HEADLINE_STRUCTURED_PARSER_CASES)
def test_structured_parser_denies_the_same_shapes_the_default_parser_denies(
    command, parser_definition, cwd_pinned_inside_project
):
    """The headline defect, pinned as an explicit pair. Before this
    improvement, all three of these shapes ALLOWed under a `structured`
    parser while attaching NO parser at all denied every one of them - the
    more knowledgeable parser was the more permissive one. Both entries must
    now reach the SAME verdict, at Reason level, for the SAME command - so
    that inversion cannot silently return.
    """
    with cwd_pinned_inside_project():
        default_config = {
            "allowedCommands": ["echo", {"program": "tool"}],
            "commandSubstitutionResponse": "via-allowed-commands",
        }
        structured_config = {
            "allowedCommands": [
                "echo",
                {"program": "tool", "commandParser": {"type": "structured", **parser_definition}},
            ],
            "commandSubstitutionResponse": "via-allowed-commands",
        }

        default_result = assert_decision(command, default_config, "deny")
        structured_result = assert_decision(command, structured_config, "deny")

        assert default_result.reason == structured_result.reason


def test_structured_parser_positional_declared_path_false_earns_an_exemption(cwd_pinned_inside_project):
    """`/etc/passwd` LOOKS exactly like the path it is not declared to be -
    chosen deliberately so the old shape heuristic (which this test's
    pre-change run still exercises, since it ignores the unread `positionals`
    key) would otherwise catch it, making this a genuine RED case rather
    than one that happens to pass for an unrelated reason."""
    with cwd_pinned_inside_project():
        assert_decision(
            "tool /etc/passwd",
            {
                "allowedCommands": [
                    {
                        "program": "tool",
                        "commandParser": {"type": "structured", "positionals": [{"index": 0, "path": False}]},
                    }
                ]
            },
            "allow",
        )


def test_structured_parser_option_value_declared_path_false_earns_an_exemption(cwd_pinned_inside_project):
    with cwd_pinned_inside_project():
        assert_decision(
            "tool --colors /etc/passwd",
            {
                "allowedCommands": [
                    {
                        "program": "tool",
                        "commandParser": {
                            "type": "structured",
                            "options": [{"option": "--colors", "arguments": 1, "path": False}],
                        },
                    }
                ]
            },
            "allow",
        )


def test_structured_parser_still_denies_a_slot_it_did_not_rule_out(cwd_pinned_inside_project):
    """The same parser as the previous case still denies positional 1, which
    it never declared - `path: false` on one slot must not blanket-exempt
    the whole entry."""
    with cwd_pinned_inside_project():
        assert_decision(
            "tool /etc/passwd /etc/hosts",
            {
                "allowedCommands": [
                    {
                        "program": "tool",
                        "commandParser": {"type": "structured", "positionals": [{"index": 0, "path": False}]},
                    }
                ]
            },
            "deny",
        )


def test_structured_parser_joined_form_contributes_the_value_not_the_whole_word(cwd_pinned_inside_project):
    """`--colors=/etc/passwd` must resolve to `/etc/passwd` - burying it
    under the project root (`<project>/--colors=/etc/passwd`) is exactly how
    the literal twin of this hole stayed open in `DefaultParser`."""
    with cwd_pinned_inside_project():
        result = assert_decision(
            "tool --colors=/etc/passwd",
            {"allowedCommands": [{"program": "tool", "commandParser": {"type": "structured"}}]},
            "deny",
        )
        assert_reason_includes(result, ArgumentPathOutsideAllowedPaths("tool", "/etc/passwd"))


@pytest.mark.parametrize(
    "retired_key,retired_value",
    [
        ("optionsWithArguments", ["-c"]),
        ("pathOptions", ["-o"]),
        ("pathPositionals", [0]),
    ],
)
def test_a_retired_structured_parser_key_is_rejected_at_decision_time(retired_key, retired_value):
    """The four parallel keys (`options`, `optionsWithArguments`,
    `pathOptions`, `pathPositionals`) collapsed into one per-slot declaration
    schema. A config still carrying a retired key is the 'config no author
    could have meant' class this engine's load-time rejection doctrine
    exists for: silently ignoring `optionsWithArguments` would change
    TOKENIZATION (an option's value becomes a stray positional, shifting
    every later index), and silently ignoring `pathOptions`/`pathPositionals`
    would leave an author believing they had declared something.
    """
    with pytest.raises(ConfigError):
        decision_for(
            "tool arg",
            {
                "allowedCommands": [
                    {"program": "tool", "commandParser": {"type": "structured", retired_key: retired_value}}
                ]
            },
        )


def test_structured_parser_undeclared_bare_flag_still_allows(cwd_pinned_inside_project):
    """An undeclared valueless flag's own token resolves project-relative and
    stays contained - declaring it was never required to avoid a denial."""
    with cwd_pinned_inside_project():
        assert_decision(
            "tool --verbose plain",
            {"allowedCommands": [{"program": "tool", "commandParser": {"type": "structured"}}]},
            "allow",
        )


def test_structured_parser_paths_filter_heuristic_still_rejects_an_undeclared_in_project_path(
    cwd_pinned_inside_project,
):
    """`paths_for_filtering` keeps its heuristic for undeclared positionals -
    dropping it would silently turn this DENY into an ALLOW, because argument-
    path containment cannot substitute for it: `./other-file.txt` is inside
    the project."""
    with cwd_pinned_inside_project():
        result = assert_decision(
            "tool ./other-file.txt",
            {
                "allowedCommands": [
                    {
                        "program": "tool",
                        "commandParser": {"type": "structured"},
                        "filters": [{"type": "paths", "exactly": ["allowed.txt"]}],
                    }
                ]
            },
            "deny",
        )
        assert_reason_includes(result, FilterRejected("tool", "paths"))


# --- A6, second pass: the parser-capability interface the rule needs ---
#
# Enforcing A6 requires asking the entry's parser two questions: does it know
# this option, and does that option consume a value? These four cases specify
# the capability itself, now expressed on the one-declaration-per-slot
# `options` schema (improvement-20260920-131722): a bare string item declares
# a valueless flag, `{"option": ..., "arguments": N}` declares a consuming
# option. The retired `optionsWithArguments` key no longer exists - see the
# StructuredParser path candidacy section below for its replacement's full
# rationale.
#
# Every `commandParser` in this suite states its `type` explicitly. There is NO
# implicit default: A2 adjudicates an unrecognised parser type to load-time
# rejection, and a MISSING type is the same class - a config that silently
# becomes a DefaultParser is exactly A2's "typo'd parser type silently disables
# propagation". An omission here would read as a decision nobody made.


def test_option_value_filter_is_rejected_when_the_parser_declares_no_such_option():
    """1 of 4. The parser knows nothing about `-m`, so the filter names a
    subject that can never be populated.
    """
    with pytest.raises(ConfigError):
        decision_for(
            "git commit -m wip",
            {
                "allowedCommands": [
                    {
                        "program": "git",
                        "commandParser": {"type": "structured", "options": []},
                        "filters": [
                            {"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}
                        ],
                    }
                ]
            },
        )


def test_option_value_filter_loads_when_the_parser_declares_the_option_consumes_a_value():
    """2 of 4. Declared as consuming, so the filter has a value to inspect.

    Asserted with a message the pattern does NOT match, so a pass here proves
    the config loaded AND the filter evaluated - not merely that nothing blew up.
    """
    assert_decision(
        "git commit -m proper-message",
        {
            "allowedCommands": [
                {
                    "program": "git",
                    "commandParser": {"type": "structured", "options": [{"option": "-m", "arguments": 1}]},
                    "filters": [
                        {"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}
                    ],
                }
            ]
        },
        "allow",
    )


def test_option_value_filter_is_rejected_when_the_parser_declares_the_option_takes_no_value():
    """3 of 4, and the case that makes the interface two questions rather than one.

    `-m` IS declared (as a bare string - a valueless flag), so "does the
    parser know this option?" answers yes - but it consumes no arguments, so
    there is still no value for an `optionValue` filter to inspect. Knowing
    the option exists is not enough; the filter needs the option to CONSUME.
    """
    with pytest.raises(ConfigError):
        decision_for(
            "git commit -m wip",
            {
                "allowedCommands": [
                    {
                        "program": "git",
                        "commandParser": {"type": "structured", "options": ["-m"]},
                        "filters": [
                            {"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}
                        ],
                    }
                ]
            },
        )


def test_option_value_filter_loads_when_the_parser_declares_both_kinds_of_option():
    """4 of 4. Both declarations coexist on one parser and the filter correctly
    targets the consuming one - so the rule discriminates between the two
    declaration kinds rather than merely checking the option appears somewhere.
    """
    assert_decision(
        "git commit -v -m proper-message",
        {
            "allowedCommands": [
                {
                    "program": "git",
                    "commandParser": {
                        "type": "structured",
                        "options": ["-v", {"option": "-m", "arguments": 1}],
                    },
                    "filters": [
                        {"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}
                    ],
                }
            ]
        },
        "allow",
    )

def test_propagation_does_not_see_operands_arriving_on_stdin(cwd_pinned_inside_project):
    """Flag List D3's KNOWN RESIDUAL LIMIT, specified rather than pretended away.

    The sensitive path is inside `filelist.txt`, not in the command text, so
    nothing static reveals what the pipe will hand the propagated `cat`.
    Specified as ALLOW because asserting deny would encode a guarantee the
    engine cannot keep. A config author who needs that guarantee must not
    allow-list the wrapper.

    THE LIMIT IS NARROWER THAN IT LOOKS, and the case below pins the boundary:
    a sensitive path written literally on the line IS caught, because
    sensitivePaths scans every literal in the command regardless of which
    program receives it. Only content the command merely REFERENCES - a file's
    contents, a runtime expansion - is out of reach.
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "cat filelist.txt | xargs cat",
            {
                "allowedCommands": [
                    {
                        "program": "xargs",
                        "commandParser": {"type": "provided", "name": "xargs"},
                        "filters": [{"type": "nestedCommand"}],
                    },
                    {"program": "cat"},
                ],
                "sensitivePaths": ["/vault/secret.txt"],
            },
            "allow",
        )


def test_a_sensitive_path_written_on_the_line_is_caught_even_when_piped_onward(
    cwd_pinned_inside_project,
):
    """The boundary of the limit above, and the reason it must be stated as a
    pair.

    Specifying only the ALLOW half would read as "piping defeats sensitivePaths",
    which is false and would invite an implementation that stops scanning
    literals once a pipe is present. The path here is a literal on the line, so
    it is caught no matter which program is about to receive it.
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "echo /vault/secret.txt | xargs cat",
            {
                "allowedCommands": [
                    {
                        "program": "xargs",
                        "commandParser": {"type": "provided", "name": "xargs"},
                        "filters": [{"type": "nestedCommand"}],
                    },
                    {"program": "echo"},
                    {"program": "cat"},
                ],
                "sensitivePaths": ["/vault/secret.txt"],
            },
            "deny",
        )


def test_command_substitution_deny_still_denies_a_heredoc_carrying_a_substitution():
    """Flag List A4: `CommandAst.with_heredoc_normalized_to_lit` rewrites a
    heredoc to a Lit node BEFORE the substitution check runs, so the check never
    sees it and the substitution policy is bypassed even when the inner command
    is not allow-listed. The normalisation must not be allowed to hide content
    from a policy that would otherwise refuse it.
    """
    assert_decision(
        "cat <<EOF\n$(uname -a)\nEOF",
        {"allowedCommands": ["cat"], "commandSubstitutionResponse": "deny"},
        "deny",
    )


def test_a_wrapped_allowed_command_is_allowed_for_each_of_the_four_bundled_wrapper_parsers():
    """The live symptom this improvement fixes, pinned for all four bundled
    wrapper parsers at once: `timeout`, `nix`/`nix-shell`, `xargs` denied
    even an allow-listed inner command, because each parser's carried-over
    `named["command"]`-only output never reached the nestedCommand filter's
    real channel. This is the case that must flip from deny to allow.
    """
    assert_decision("timeout 10 echo hi", wrapper_wrapping_allowed_program("timeout", "echo"), "allow")
    assert_decision("nix develop -c echo hi", wrapper_wrapping_allowed_program("nix", "echo"), "allow")
    assert_decision(
        "nix-shell --run 'echo hi'", wrapper_wrapping_allowed_program("nix-shell", "echo"), "allow"
    )
    assert_decision("xargs echo hi", wrapper_wrapping_allowed_program("xargs", "echo"), "allow")


def test_a_wrapped_blocked_command_is_denied_for_each_of_the_four_bundled_wrapper_parsers():
    """The negative half, proving propagation actually propagates rather than
    merely having stopped failing: an allow-listed wrapper whose wrapped
    command is BLOCKED must still deny, and the reason must be the
    `nestedCommand` filter rejecting - not some unrelated objection - so a
    parser that silently stopped publishing again would be caught here.
    `xargs` is already covered by
    `test_a_propagated_command_is_checked_against_blocked_commands`; this
    adds the other three so none of them can regress to allow silently.
    """
    timeout_result = assert_decision(
        "timeout 10 rm -rf ./build", wrapper_config("timeout", blocked=["rm"]), "deny"
    )
    assert_reason_includes(timeout_result, FilterRejected("timeout", "nestedCommand"))

    nix_result = assert_decision(
        "nix develop -c rm -rf ./build", wrapper_config("nix", blocked=["rm"]), "deny"
    )
    assert_reason_includes(nix_result, FilterRejected("nix", "nestedCommand"))

    nix_shell_result = assert_decision(
        "nix-shell --run 'rm -rf ./build'", wrapper_config("nix-shell", blocked=["rm"]), "deny"
    )
    assert_reason_includes(nix_shell_result, FilterRejected("nix-shell", "nestedCommand"))


# =============================================================================
# Batch 5: bypass and add-allow-policy escalation
#
# The two named escape hatches, plus the one guard neither of them can lift.
# Command names are the NEW ones settled by the scaffold leaf
# (`bypass-policy`, `add-allow-policy`), not today's
# `bypass-shfmt-permissions` / `propose-shfmt-permissions-*-allow`.
# =============================================================================


def test_the_bypass_wrapper_yields_passthrough_rather_than_allow():
    """Flag List C1, and branch 2 of the outcome model.

    The distinction matters more under deny-by-default, not less: `passthrough`
    means the engine states no opinion and Claude Code's own dialog decides, so
    a human still sees the command. It must never be conflated with `allow`,
    which would run it silently.
    """
    assert_decision(
        "bypass-policy some-unrecognised-tool --flag",
        {"allowedCommands": ["echo"]},
        "passthrough",
    )


def test_the_bypass_wrapper_escalates_a_blocked_command_to_a_human_decision():
    """Re-adjudicated 2026-09-17 (leaf 20260915-010959): a blocked-command
    objection is one of the two the wrapper can never launder around
    silently - it forces `ask` rather than `passthrough`, so the human sees
    it rather than a permissive settings.json or an accepting permission
    mode silently letting it through with no one ever seeing it.
    """
    assert_decision(
        "bypass-policy rm -rf ./build",
        {"allowedCommands": ["echo"], "blockedCommands": ["rm"]},
        "ask",
    )


def test_the_bypass_wrapper_treats_a_double_quoted_inner_command_like_the_single_quoted_form():
    """Finding 1, the worst false-ALLOW this improvement fixes. Before the
    Argument.text fix, `bypass-policy "rm -rf /"`'s wrapped_text read as the
    empty string, which escalation_policy.py's `bypass_transform` took as
    "nothing to re-evaluate" and returned `PermissionDecision.allow()`
    directly - AUTO-ALLOWED, no human ever involved. `rm` is merely not
    allow-listed (not blocked/sensitive-path/redirect-outside), so the
    correct outcome, matching the single-quoted form, is passthrough.
    """
    assert_decision('bypass-policy "rm -rf /"', {"allowedCommands": ["echo"]}, "passthrough")
    assert_decision("bypass-policy 'rm -rf /'", {"allowedCommands": ["echo"]}, "passthrough")


def test_the_bypass_wrapper_does_not_cover_a_command_chained_alongside_it():
    """The wrapper suspends analysis only for what IT runs.

    A command sharing the line is not wrapped and must still face normal
    analysis - otherwise `bypass-policy true && <anything>` would launder the
    whole line through a single opt-in. The hint names the fix: wrap the
    command you actually mean to escalate.
    """
    result = assert_decision(
        "bypass-policy echo hi && rm -rf ./build",
        {"allowedCommands": ["echo"], "blockedCommands": ["rm"]},
        "deny",
    )
    assert_reason_includes(result, NotEscalatedByAnUnrelatedBypassWrapper())


def test_the_shell_performed_redirect_veto_is_never_waived_but_escalates_to_a_human(
    cwd_pinned_inside_project,
):
    """The one guard `bypass-policy` cannot lift - re-adjudicated 2026-09-17
    (leaf 20260915-010959): NOT 'survives as deny' any more. `deny` would
    dead-end an escalation the caller made explicitly by name, pointing at
    alternatives that by definition do not exist for a shell-performed
    redirect. The veto is never WAIVED - the wrapper still cannot vouch for
    a redirect the calling shell performs before it ever starts - but it now
    surfaces to the human as `ask` rather than dead-ending as `deny`.
    """
    with cwd_pinned_inside_project():
        assert_decision(
            "bypass-policy echo x > /vault/secret.txt",
            {"allowedCommands": ["echo"], "sensitivePaths": ["/vault/secret.txt"]},
            "ask",
        )


def test_add_allow_policy_forces_ask_as_the_durable_fix_escalation():
    """Flag List C2. Re-adjudicated 2026-09-17 (leaf 20260915-010959):
    `add-allow-policy` is no longer the ONLY path that forces `ask` -
    `bypass-policy` now also forces it for a blocked-command/sensitive-path/
    redirect objection (see the two tests above) - but it remains the ONLY
    path whose ask dialog IS the durable config write, where a bypass ask
    only gets one command past the gate this once.

    RE-AUTHORED 2026-09-17 (reopened for the strict grammar, Task 1): the
    original case omitted `--intent` and a quoted command, which is now
    itself a malformed shape (see the cases below) rather than this escalation
    - the canonical form is required to exercise the forced-ask path at all.
    """
    assert_decision(
        'add-allow-policy --scope user --intent "why" "rg"',
        {"allowedCommands": ["echo"]},
        "ask",
    )


def test_add_allow_policy_forces_ask_for_the_project_scope_too():
    """RE-AUTHORED 2026-09-17 - see the note above."""
    assert_decision(
        'add-allow-policy --scope project --intent "why" "rg"',
        {"allowedCommands": ["echo"]},
        "ask",
    )


def test_the_two_escape_hatches_produce_different_outcomes_by_design():
    """Guards against a later simplification collapsing them into one path.

    They answer different questions - "run this once anyway" versus "make this
    permanently allowed" - so they must not converge on a single outcome.

    RE-AUTHORED 2026-09-17: the `add-allow-policy` call independently broke
    under the strict grammar (missing `--intent`, unquoted command) though it
    was not one of the two cases the reopening task named - fixed here as a
    necessary consequence of Task 1, not a revisit of anything else.
    """
    assert_decision("bypass-policy rg pattern", {"allowedCommands": []}, "passthrough")
    assert_decision('add-allow-policy --scope user --intent "why" "rg"', {"allowedCommands": []}, "ask")


# -- add-allow-policy's strict grammar (reopened 2026-09-17, Task 1) ---------
#
# The decision spec suite asserts STRUCTURE, not one case per malformed shape
# - the exhaustive grammar surface (missing/duplicate/invalid --scope, missing
# --intent, zero/multiple command arguments, chained/piped/backgrounded/
# substitution-bearing invocations) is unit-tested directly against
# add_allow_policy_transform in test_escalation_policy.py. These few
# black-box cases exist for the one shape with a real user-visible
# consequence (the unquoted redirect the reopening task called out by name),
# plus one representative of the "quoting matters even with no redirect"
# property.


def test_add_allow_policy_denies_an_unquoted_redirect_as_wrong_usage():
    """The flagship malformed shape: `add-allow-policy --scope user --intent
    "x" echo something > somewhere` persists the policy "echo something"
    while the OUTER shell performs "> somewhere" against add-allow-policy's
    own stdout - a different thing than what the caller asked to allow.
    """
    result = assert_decision(
        'add-allow-policy --scope user --intent "x" echo something > somewhere',
        {"allowedCommands": []},
        "deny",
    )
    assert_reason_includes(result, AddAllowPolicyGrammarViolation("redirect_on_invocation"))


def test_add_allow_policy_denies_an_unquoted_multi_word_command_with_no_redirect_involved():
    """Quoting matters even with no redirect on the line: an unquoted
    multi-word command still reaches the tool as more than one argument."""
    result = assert_decision(
        'add-allow-policy --scope user --intent "x" echo hi',
        {"allowedCommands": []},
        "deny",
    )
    assert_reason_includes(result, AddAllowPolicyGrammarViolation("multiple_command_arguments"))



def test_add_allow_policy_denies_a_parameter_expansion_in_the_command_entry():
    """Finding 5: a bare `ParamExp` in the entry (command) argument is
    invisible to `as_sole_invoked_program()`'s shell_touched gate - that gate
    only sees `CmdSubst`/`ProcSubst` (Statement subtypes reachable via
    `sub_statements()`), and a `ParamExp` is not one. Without the added
    `referenced_variables` check, the human would see a narrower entry string
    than `lib/add_allow_write.py` would actually persist (it parses real
    post-expansion argv)."""
    result = assert_decision(
        'add-allow-policy --scope user --intent "x" "cat $HOME/file"',
        {"allowedCommands": []},
        "deny",
    )
    assert_reason_includes(result, AddAllowPolicyGrammarViolation("shell_touched"))


def test_substitution_policy_is_decided_before_sensitive_variable_detection():
    """Flag List E7, ordering property 1.

    Both objections apply to this command. The specification pins WHICH one the
    engine reports, because a hint that names a different cause on each run is
    not actionable. Ordering is asserted as a property here, not as a numeric
    Pass value - the concrete pass numbers are leaf 20260914-213652's to declare.
    """
    result = assert_decision(
        "echo $(cat secrets) $API_TOKEN",
        {
            "allowedCommands": [{"program": "echo", "onlyTheseVariables": ["API_TOKEN"]}],
            "sensitiveVariables": ["API_TOKEN"],
            "commandSubstitutionResponse": "deny",
        },
        "deny",
    )
    assert_primary_reason(result, CommandSubstitutionPresent())


def test_a_sensitive_path_is_decided_before_a_sensitive_variable():
    """Flag List E7, ordering property 2."""
    result = assert_decision(
        "cat /vault/secret.txt $API_TOKEN",
        {
            "allowedCommands": [{"program": "cat", "onlyTheseVariables": ["API_TOKEN"]}],
            "sensitivePaths": ["/vault/secret.txt"],
            "sensitiveVariables": ["API_TOKEN"],
        },
        "deny",
    )
    assert_primary_reason(result, SensitivePathReferenced("/vault/secret.txt"))


def test_a_sensitive_variable_is_decided_before_the_allowlist_check():
    """Flag List E7, ordering property 3.

    The program is not allow-listed AND a sensitive variable is referenced.
    Reporting the allowlist miss would send the reader off to add an allowlist
    entry that would not have helped - the variable would still stop it.
    """
    result = assert_decision(
        "some-unlisted-tool $API_TOKEN",
        {"allowedCommands": ["echo"], "sensitiveVariables": ["API_TOKEN"]},
        "deny",
    )
    assert_primary_reason(result, SensitiveVariableReferenced("API_TOKEN"))


# --- cases added to close branches the coverage manifest reported unreached ---


def test_a_config_with_no_allowed_commands_denies_everything():
    """An empty allowlist is a coherent, reachable config: it allows nothing.

    Under the old model this hit `defaultDecision` and so PASSED THROUGH by
    default, which is how a user who had not finished configuring got a
    silently permissive engine. Deny-by-default removes that failure mode.
    """
    assert_decision("echo hi", {"allowedCommands": []}, "deny")


def test_a_sensitive_variable_reference_is_denied():
    """`sensitiveVariableResponse` is gone, so detection no longer routes
    through a knob that defaulted to `ask` - referencing a sensitive variable
    now simply denies.
    """
    result = assert_decision(
        "echo $AWS_SECRET_ACCESS_KEY",
        {
            "allowedCommands": [{"program": "echo", "onlyTheseVariables": ["AWS_SECRET_ACCESS_KEY"]}],
            "sensitiveVariables": ["AWS_SECRET_ACCESS_KEY"],
        },
        "deny",
    )
    assert_reason_includes(result, SensitiveVariableReferenced("AWS_SECRET_ACCESS_KEY"))


def test_multiple_sensitive_variables_are_reported_in_a_deterministic_order():
    """Flag List E4, adjudicated here: PIN AN ORDER rather than assert
    order-independently.

    Today the reasons accumulate by iterating a SET, so the hint text can vary
    between runs on identical input. A hint that changes run-to-run cannot be
    tested, cached, or trusted by a reader comparing two denials - so the
    specification requires a stable order (sorted) rather than merely tolerating
    whatever order arrives.
    """
    result = decision_for(
        "echo $BETA_TOKEN $ALPHA_TOKEN",
        {
            "allowedCommands": [
                {"program": "echo", "onlyTheseVariables": ["ALPHA_TOKEN", "BETA_TOKEN"]}
            ],
            "sensitiveVariables": ["ALPHA_TOKEN", "BETA_TOKEN"],
        },
    )

    assert result.decision == "deny"
    assert result.reason.index(SensitiveVariableReferenced("ALPHA_TOKEN")) < result.reason.index(
        SensitiveVariableReferenced("BETA_TOKEN")
    ), f"sensitive-variable reasons are not in a deterministic order: {result.reason}"


def test_a_denial_reports_a_blocked_command_and_a_sensitive_path_together():
    """The reason list is FLAT and HETEROGENEOUS on purpose (leaf
    20260915-010959's Design Decisions, 'The shape of a denial's reason'): a
    single command can legitimately carry a categorical blocked-command
    objection AND a categorical sensitive-path objection at once, and both
    must be reported - not just whichever pass happens to run first.
    """
    result = decision_for(
        "rm /vault/secret.txt",
        {"blockedCommands": ["rm"], "sensitivePaths": ["/vault/secret.txt"]},
    )

    assert result.decision == "deny"
    assert BlockedCommandInvoked("rm") in result.reason
    assert SensitivePathReferenced("/vault/secret.txt") in result.reason


def test_exceeding_the_propagation_depth_limit_is_denied():
    """Another outcome re-derived for the new model rather than inherited.

    The old engine returns `ask` when propagation recurses past `maxDepth`.
    `ask` is now reserved exclusively for `add-allow-policy`, so a wrapper chain
    the engine cannot finish evaluating must fail closed instead - it is
    precisely the case where the engine knows it has NOT established that the
    command is safe.

    Asserted at the REASON level, not only the outcome (leaf 20260918-223632):
    before `parsers/xargs.py` existed, this denied via
    `ParserCouldNotInterpretInvocation` - a parse failure, never reaching the
    depth guard at all - which would have made this case pass whether or not
    the guard worked. `FilterRejected("xargs", "nestedCommand")` is the shape
    that distinguishes a genuine depth-guard denial from that parse failure.
    """
    config = wrapper_config("xargs")
    config["allowedCommands"][0]["filters"] = [{"type": "nestedCommand", "maxDepth": 1}]

    result = assert_decision("xargs xargs xargs rm -rf ./build", config, "deny")
    assert_reason_includes(result, FilterRejected("xargs", "nestedCommand"))


# =============================================================================
# Parse-failure posture - re-adjudicated for the new model, not inherited.
#
# Migrated from shfmt-permissions' `TestShfmtParseFailure` (old :3057-3123).
# The OLD engine treated a parse failure (missing shfmt binary, non-zero
# exit, malformed JSON stdout, timeout) as deliberate ABSTENTION -
# `passthrough`, even against a config with a real denylist/allowlist that
# would otherwise fire (see shfmt-permissions' own CLAUDE.md ## Dependencies:
# "the plugin grants nothing here it could not also grant with a working
# parser"). Under the new deny+hint model this posture flips: `config.py`'s
# `_parse_and_normalize` returns `PermissionDecision.deny(...)` for a `None`
# `Statement`, not passthrough - there is no longer a reason to abstain when
# denying is itself safe (a hint, not a block; see this suite's own module
# docstring). This is a DELIBERATE reversal already implemented by leaf
# 20260914-213652, not a gap - these cases pin the reversal explicitly so a
# future change cannot silently reintroduce abstention.
# =============================================================================


def _break_shfmt(monkeypatch, mode):
    """Monkeypatch `statement`'s own `shutil`/`subprocess` seams so
    `Statement.from_command` fails via one of the four modes `_parse`
    guards against - mirrors the old suite's `fake_shfmt_on_path`/
    `TimeoutExpired`-raising monkeypatches, but against the real seam
    (`statement.py`'s own imports) instead of writing a fake binary to PATH.
    """
    import subprocess

    import statement

    if mode == "missing_binary":
        monkeypatch.setattr(statement.shutil, "which", lambda name: None)
    elif mode == "non_zero_exit":
        monkeypatch.setattr(
            statement.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, returncode=1, stdout="", stderr="boom"),
        )
    elif mode == "malformed_json":
        monkeypatch.setattr(
            statement.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, returncode=0, stdout="not json", stderr=""),
        )
    elif mode == "timeout":
        def _raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="shfmt", timeout=5)

        monkeypatch.setattr(statement.subprocess, "run", _raise_timeout)
    else:
        raise ValueError(mode)


def test_control_a_denylist_bearing_config_fires_with_real_shfmt():
    """CONTROL: guards every case below from passing vacuously - if a future
    change makes this config stop enforcing, this test fails first."""
    config = {"blockedCommands": ["rm"], "allowedCommands": ["ls"]}

    assert_decision("rm -rf /tmp/x", config, "deny")
    assert_decision("ls -la", config, "allow")


@pytest.mark.parametrize("mode", ["missing_binary", "non_zero_exit", "malformed_json", "timeout"])
def test_a_parse_failure_denies_with_a_hint_rather_than_passing_through(monkeypatch, mode):
    _break_shfmt(monkeypatch, mode)
    config = {"blockedCommands": ["rm"], "allowedCommands": ["ls"]}

    result = decision_for("ls -la", config)

    assert result.decision == "deny"


_FAKE_PARSERS = Path(__file__).parent / "fixtures" / "fake_parsers"


def test_an_external_command_parser_that_fails_denies_rather_than_falling_back_silently():
    """Restores coverage for a property the deleted old commandParser.fallback
    specs pinned (carried-forward finding #5): an external `command`-type
    parser script that exits non-zero produces `None` (`ExternalParserFactory.
    raw_output_for`'s own contract), which the pipeline turns into
    `ParserCouldNotInterpretInvocation` - a deny, never a silent allow."""
    from reason import ParserCouldNotInterpretInvocation

    config = {
        "allowedCommands": [
            {
                "program": "vim",
                "commandParser": {"type": "command", "command": str(_FAKE_PARSERS / "exits_nonzero.py")},
            }
        ]
    }

    result = decision_for("vim file.txt", config)

    assert result.decision == "deny"
    assert ParserCouldNotInterpretInvocation("vim") in result.reason


# =============================================================================
# Variable-invoked command words - Bug B (security fail-open), re-adjudicated
#
# Migrated from shfmt-permissions' `TestVariableInvokedCommands` (old
# :4868-5013). Bug B: a variable-invoked command word (`Command.command_word
# is None` - a quoted or unquoted `"$VAR/rm" -rf /` shape) must NEVER decide
# `allow` merely because allowedCommands happens to be configured; it must go
# through the ordinary deny-by-default path like any other unresolvable
# invocation. The old suite's `defaultDecision`-honoring and
# suffix-matching-removal sub-cases are DROPPED here (both concepts are
# gone - there is no `defaultDecision` knob under the deny+hint model, only
# `deny`, and `pluginProgram` suffix matching was already removed before this
# rewrite). What survives is the core regression property itself, plus the
# `programGlob`-entry crash this leaf found and fixed while porting it (see
# this leaf's Implementation Notes) - `_entry_matches_program` used to raise
# `TypeError` for exactly this shape.
# =============================================================================


def test_an_unresolvable_command_word_is_denied_not_allowed_even_with_a_matching_allowlist():
    """Bug B's core property: allowedCommands being non-empty must never by
    itself cause an unresolvable command word to decide allow."""
    config = {"allowedCommands": ["git"]}

    assert_decision('"$SOMEDIR/rm" -rf /', config, "deny")


def test_a_pipeline_with_one_resolvable_and_one_unresolvable_word_is_denied():
    """One allow-listed program sharing a pipeline with an unresolvable one
    must not let the unresolvable half ride along as allowed."""
    config = {"allowedCommands": ["git"]}

    assert_decision('git status | "$SOMEDIR/filter" --all', config, "deny")


def test_an_unresolvable_command_word_does_not_crash_a_program_glob_entry():
    """The `programGlob` counterpart of the property above - found while
    porting this class: `_entry_matches_program` used to call
    `fnmatch.fnmatch(None, pattern)`, raising `TypeError`, instead of simply
    not matching. Fixed in `allowed_command_policy.py` alongside this test."""
    config = {"allowedCommands": [{"programGlob": {"marketplace": "m", "plugin": "p", "path": "bin/foo"}}]}

    assert_decision('"$CLAUDE_PLUGIN_ROOT/bin/foo" clear', config, "deny")


# =============================================================================
# Bundled provided-parser wiring: npm/pnpm/yarn through a real namedValue filter
#
# Migrated from shfmt-permissions' `TestParserFilterIntegration`'s npm/pnpm/
# yarn-specific subtests (old :2515-2609). The bundled `parsers/npm.py`/
# `pnpm.py`/`yarn.py` scripts are byte-identical ports and publish
# `named.global`/`named.subcommand`/`named.script` - a shape the NEW
# `namedValue` matcher (`parsed.named.get(name)`) reads directly, no
# protocol change needed (unlike `timeout`/`nix`/`nix-shell` below). These
# were simply never exercised end to end through `Config.decision_for` in
# the new suite - closing that gap here.
# =============================================================================


def _provided_parser_config(name, filters):
    return {
        "allowedCommands": [
            {"program": name, "commandParser": {"type": "provided", "name": name}, "filters": filters}
        ]
    }


_GLOBAL_INSTALL_BLOCK_FILTER = [{"type": "namedValue", "name": "global", "pattern": "true", "action": "block"}]


def test_npm_global_install_detection_blocks_the_global_flag():
    config = _provided_parser_config("npm", _GLOBAL_INSTALL_BLOCK_FILTER)

    assert_decision("npm install -g typescript", config, "deny")
    assert_decision("npm install typescript", config, "allow")


def test_pnpm_global_install_detection_blocks_the_global_flag():
    config = _provided_parser_config("pnpm", _GLOBAL_INSTALL_BLOCK_FILTER)

    assert_decision("pnpm add -g typescript", config, "deny")
    assert_decision("pnpm add typescript", config, "allow")


def test_yarn_classic_global_add_prefix_is_detected_like_the_flag_form():
    """Yarn v1's distinctive `global add` PREFIX (no `-g` flag at all) must
    set the same `named.global` the block filter above keys on."""
    config = _provided_parser_config("yarn", _GLOBAL_INSTALL_BLOCK_FILTER)

    assert_decision("yarn global add typescript", config, "deny")
    assert_decision("yarn add typescript", config, "allow")


def test_pnpm_implicit_script_run_is_canonicalized_for_a_named_value_filter():
    """`pnpm build` (no `run` subcommand word) canonicalizes to
    `named.subcommand == "run"` / `named.script == "build"` - a `namedValue`
    filter on `script` must see the canonicalized name, not the raw
    positional."""
    config = _provided_parser_config(
        "pnpm", [{"type": "namedValue", "name": "script", "pattern": "^build$", "action": "required"}]
    )

    assert_decision("pnpm build", config, "allow")
    assert_decision("pnpm test", config, "deny")


# =============================================================================
# spawn-claude: an honest path-candidate set for a wrapper's own grammar
#
# improvement-20260920-142519. `spawn-claude`'s live operator entry falsely
# declares `hasNoPathParameters: true` even though it forwards arbitrary
# `claude` flags verbatim, several of which take paths (`--settings`,
# `--add-dir`, `--mcp-config`, `--plugin-dir`). `parsers/spawn-claude.py`
# closes this with NO flag-name enumeration: it splits at the first literal
# `--` the same way the real nushell script does, and gives the
# forwarded-args span (only) total path candidacy - the session name and the
# prompt are positively known not to be paths and are never examined.
# =============================================================================


def _spawn_claude_config():
    return {
        "allowedCommands": [
            {"program": "spawn-claude", "commandParser": {"type": "provided", "name": "spawn-claude"}},
            "echo",
        ],
        "commandSubstitutionResponse": "via-allowed-commands",
    }


SPAWN_CLAUDE_PATH_VALUED_FLAG_CASES = [
    ("spawn-claude foo --settings /etc/passwd", "/etc/passwd"),
    ("spawn-claude foo --settings=/etc/passwd", "/etc/passwd"),
    ("spawn-claude foo --add-dir /etc", "/etc"),
    ("spawn-claude foo --mcp-config /etc/passwd", "/etc/passwd"),
    ("spawn-claude foo --plugin-dir /etc", "/etc"),
]


@pytest.mark.parametrize("command,offending_path", SPAWN_CLAUDE_PATH_VALUED_FLAG_CASES)
def test_a_path_valued_claude_flag_forwarded_by_spawn_claude_denies(
    command, offending_path, cwd_pinned_inside_project
):
    """None of these flags is named anywhere in the parser - no block-list,
    no enumeration of claude's path-valued flags in either direction. The
    forwarded-args span gets total path candidacy, the same rule
    `DefaultParser` already applies, so `--plugin-dir` - a flag the
    originating brief never named - denies exactly like the ones it did."""
    with cwd_pinned_inside_project():
        result = assert_decision(command, _spawn_claude_config(), "deny")
        assert_primary_reason(result, ArgumentPathOutsideAllowedPaths("spawn-claude", offending_path))


def test_a_substitution_forwarded_to_claude_denies_as_an_unknowable_path_argument(cwd_pinned_inside_project):
    """The forwarded-args span has no knowledge of `--settings` specifically
    - it is not a mode, not a pattern, nothing this parser can rule out - so
    an unknowable value there is an unknowable PATH operand, the same
    outcome a bare `cat $(echo README.md)` gets against `DefaultParser`."""
    with cwd_pinned_inside_project():
        result = assert_decision(
            "spawn-claude foo --settings $(echo /etc/passwd)", _spawn_claude_config(), "deny"
        )
        assert_reason_includes(result, UnknowablePathArgument("spawn-claude"))


def test_a_real_orchestrator_dispatch_still_allows_as_a_regression_guard(cwd_pinned_inside_project):
    """This is what the false `hasNoPathParameters: true` flag is currently
    protecting: a real `/improvement:*` dispatch whose seed prompt starts
    with `/` because it is a slash command. Under a bare `DefaultParser` this
    reads as an absolute path and denies; the parser must classify the
    prompt span as not-a-path for the orchestrator to survive."""
    with cwd_pinned_inside_project():
        assert_decision(
            "spawn-claude claude-marketplace-impl-1 --permission-mode acceptEdits "
            "-- /improvement:implement docs/improvements/x.md",
            _spawn_claude_config(),
            "allow",
        )


def test_a_prompt_that_merely_mentions_a_path_valued_flag_in_prose_still_allows(cwd_pinned_inside_project):
    """The prompt is published on `named` only, which `ParameterRegexMatcher`/
    `PositionalArgRegexMatcher` never read (`ParsedResult.all_argument_texts()`
    reads only options/positionals) and which this parser's own path-candidate
    construction never scans either - so prose that merely quotes a dangerous
    flag cannot pollute either mechanism."""
    with cwd_pinned_inside_project():
        assert_decision(
            "spawn-claude foo -- mentions --add-dir /etc/passwd in prose only",
            _spawn_claude_config(),
            "allow",
        )


def test_an_in_project_forwarded_directory_still_allows(cwd_pinned_inside_project):
    """The change costs no legitimate forwarded path - only a path that
    resolves OUTSIDE the project denies."""
    with cwd_pinned_inside_project():
        assert_decision("spawn-claude foo --add-dir ./subdir", _spawn_claude_config(), "allow")


def test_the_session_name_slot_is_never_a_path_candidate_even_when_it_looks_like_an_absolute_path(
    cwd_pinned_inside_project,
):
    """Argument 0 is positively classified as not-a-path (a display name and
    a pane title, never a filename) - so it never reaches the path-candidate
    set at all, whatever it looks like."""
    with cwd_pinned_inside_project():
        assert_decision("spawn-claude /etc/passwd", _spawn_claude_config(), "allow")


def test_a_substitution_landing_in_the_session_name_slot_still_allows(cwd_pinned_inside_project):
    """Documented rather than hidden: this still ALLOWs, but for a narrow
    TRUE reason now (the session-name slot is not a path) instead of the
    blanket false `hasNoPathParameters` claim it relied on before."""
    with cwd_pinned_inside_project():
        assert_decision("spawn-claude $(echo /etc/passwd)", _spawn_claude_config(), "allow")


def test_a_substitution_landing_in_the_prompt_span_still_allows(cwd_pinned_inside_project):
    """The prompt span twin of the case above - a substitution after the
    separator lands in a span this parser never treats as a path operand
    either, so it cannot trigger `UnknowablePathArgument`."""
    with cwd_pinned_inside_project():
        assert_decision("spawn-claude foo -- $(echo /etc/passwd)", _spawn_claude_config(), "allow")


# =============================================================================
# Branch-coverage manifest
#
# The ~30 MATCHING-level decision branches (the matching logic, not the
# collapsed outcome vocabulary) that the specification must reach. This is a
# hand-maintained manifest rather than runtime coverage on purpose: the engine
# does not exist yet, so there is nothing to instrument. Its job is to make an
# unreached branch VISIBLE instead of silently absent.
#
# Two guards keep it honest: a branch with no cases fails, and a case named
# here that does not exist fails. Without the second, a renamed test would
# quietly orphan its branch and the manifest would rot into a wish list.
# =============================================================================


MATCHING_BRANCH_COVERAGE = {
    # --- top-level pass ordering ---
    "blocked_commands_hit": ["test_blocked_commands_wins_over_allowed_commands_for_the_same_program"],
    "substitution_present_response_deny": [
        "test_command_substitution_response_deny_denies_regardless_of_inner_command",
        "test_command_substitution_deny_still_denies_a_heredoc_carrying_a_substitution",
    ],
    "substitution_present_response_via_allowed_commands": [
        "test_command_substitution_response_via_allowed_commands_checks_the_inner_command",
        "test_command_substitution_response_via_allowed_commands_allows_an_allow_listed_inner_command",
    ],
    "substitution_response_defaulted": ["test_command_substitution_response_defaults_to_via_allowed_commands"],
    "sensitive_variable_referenced": [
        "test_a_sensitive_variable_reference_is_denied",
        "test_multiple_sensitive_variables_are_reported_in_a_deterministic_order",
    ],
    "sensitive_path_in_literal": [
        "test_a_sensitive_path_is_denied_wherever_it_appears",
        "test_sensitive_path_matching_is_substring_and_deliberately_over_matches",
    ],
    "reason_list_reports_multiple_categorical_objections_at_once": [
        "test_a_denial_reports_a_blocked_command_and_a_sensitive_path_together"
    ],
    "no_allowed_commands_configured": ["test_a_config_with_no_allowed_commands_denies_everything"],
    "program_absent_from_allowed_commands": [
        "test_program_absent_from_allowed_commands_entirely_is_denied_with_a_hint"
    ],
    "all_invocations_allow_listed": ["test_allow_listed_command_with_no_objections_is_allowed"],
    "ordering_substitution_before_sensitive_variable": [
        "test_substitution_policy_is_decided_before_sensitive_variable_detection"
    ],
    "ordering_sensitive_path_before_sensitive_variable": [
        "test_a_sensitive_path_is_decided_before_a_sensitive_variable"
    ],
    "ordering_sensitive_variable_before_allowlist": [
        "test_a_sensitive_variable_is_decided_before_the_allowlist_check"
    ],
    # --- entry matching ---
    "entry_variable_gate_rejects": ["test_an_entry_does_not_vouch_for_a_variable_it_has_not_declared"],
    "entry_variable_gate_admits": ["test_an_entry_vouches_for_a_variable_it_has_declared"],
    "entry_without_filters_vouches": ["test_allow_listed_command_with_no_objections_is_allowed"],
    "entry_with_filters_meets_substitution": [
        "test_command_substitution_defeats_a_filter_forbidding_content_and_is_denied"
    ],
    "entry_with_filters_admits_provable_presence": [
        "test_command_substitution_does_not_defeat_a_filter_requiring_present_content"
    ],
    "entry_index_filter_meets_shifted_index": [
        "test_substitution_before_an_indexed_argument_defeats_a_required_index_filter",
        "test_substitution_before_an_indexed_positional_defeats_a_required_positional_filter",
    ],
    "entry_index_filter_pinned_ahead_of_substitution": [
        "test_substitution_after_an_indexed_argument_leaves_the_index_provable"
    ],
    "filters_all_pass": ["test_allow_listed_program_carrying_its_required_option_is_allowed"],
    "filter_rejects": ["test_allow_listed_program_whose_invocation_is_rejected_is_denied_with_a_hint"],
    "filters_and_ed_within_entry": ["test_all_filters_on_an_entry_must_pass_for_the_entry_to_vouch"],
    "entries_or_ed_across_list": ["test_a_later_entry_can_vouch_for_what_an_earlier_entry_rejects"],
    "filter_action_unrecognised": ["test_unknown_filter_action_is_rejected_at_config_load_time"],
    "filter_type_unrecognised": ["test_unknown_filter_type_is_rejected_at_config_load_time"],
    "filter_unevaluatable_at_match_time": ["test_a_filter_that_cannot_be_evaluated_fails_closed_at_match_time"],
    "filter_index_out_of_bounds": ["test_block_action_rejects_by_absence_when_the_index_is_out_of_bounds"],
    "block_filter_defeated_by_double_quoting": ["test_a_double_quoted_argument_cannot_evade_a_block_filter"],
    "substitution_index_bookkeeping_agrees_with_parser_after_double_quoting": [
        "test_a_double_quoted_flag_ahead_of_a_substitution_does_not_miscount_positions"
    ],
    # --- per-argument knowability (improvement-20260919-112214) ---
    "variable_fragment_defeats_required": ["test_a_variable_bearing_fragment_defeats_a_required_filter"],
    "variable_fragment_defeats_block": ["test_a_variable_bearing_fragment_defeats_a_block_filter"],
    "unquoted_variable_defeats_required_index": [
        "test_an_unquoted_variable_before_an_indexed_argument_defeats_a_required_index_filter"
    ],
    "substitution_fragment_defeats_required_non_index": [
        "test_a_substitution_bearing_fragment_defeats_a_required_non_index_filter"
    ],
    "dash_prefixed_unknowable_defeats_block": [
        "test_a_dash_prefixed_substitution_defeats_the_unconditional_block_rule"
    ],
    "option_present_required_defeated_by_unknowable_option_itself": [
        "test_option_present_required_denies_when_the_option_itself_is_unknowable"
    ],
    "unknowable_argument_dropped_rather_than_contributing_empty_text": [
        "test_dropping_an_unknowable_argument_lets_a_separate_literal_stay_provable"
    ],
    "word_safe_expansion_does_not_shift_a_pinned_index": [
        "test_a_double_quoted_substitution_does_not_shift_a_pinned_index"
    ],
    "entry_with_no_claim_unaffected_by_unknowable_content": [
        "test_an_entry_restricting_no_content_still_allows_a_variable_bearing_invocation"
    ],
    "single_quoted_content_is_fully_knowable": ["test_a_single_quoted_look_alike_is_fully_knowable_and_not_defeated"],
    "every_non_index_matcher_type_required": ["test_every_non_index_matcher_type_denies_its_own_required_fragment_case"],
    "every_non_index_matcher_type_block": [
        "test_every_non_index_matcher_type_denies_absence_next_to_its_own_block_fragment_case"
    ],
    "option_value_required_uses_knowable_only_reparse": [
        "test_option_value_required_denies_when_the_option_argument_is_a_fragment"
    ],
    "option_value_block_unconditional": ["test_option_value_block_denies_absence_next_to_a_fragment"],
    "named_value_required_external_parser_no_reparse": [
        "test_named_value_required_denies_when_the_named_field_came_from_a_fragment"
    ],
    "named_value_block_unconditional": ["test_named_value_block_denies_absence_next_to_a_fragment"],
    "argument_path_containment_fails_closed_next_to_unknowable_content": [
        "test_argument_path_containment_fails_closed_next_to_unknowable_content",
        "test_argument_path_containment_fails_closed_next_to_a_substitution_fragment_in_a_path_operand",
    ],
    "unknowable_argument_occupies_a_path_operand": [
        "test_a_substitution_into_a_default_parser_slot_is_a_path_operand",
        "test_one_allow_listed_string_producer_cannot_fill_a_path_operand",
        "test_the_same_shape_denies_for_a_program_that_really_does_take_paths",
        "test_the_same_parser_still_denies_a_substitution_in_its_real_path_slot",
        "test_an_unknowable_path_operand_is_reported_as_its_own_fact",
    ],
    "every_argument_is_a_default_parser_path_candidate": [
        "test_an_option_shaped_word_cannot_smuggle_a_literal_path_out_of_the_project"
    ],
    "structured_parser_denies_same_shapes_as_default_parser": [
        "test_structured_parser_denies_the_same_shapes_the_default_parser_denies"
    ],
    "structured_parser_positional_declared_path_false_earns_a_substitution": [
        "test_structured_parser_positional_declared_path_false_earns_an_exemption"
    ],
    "structured_parser_option_value_declared_path_false_earns_a_substitution": [
        "test_structured_parser_option_value_declared_path_false_earns_an_exemption"
    ],
    "structured_parser_partial_exemption_still_denies_undeclared_slot": [
        "test_structured_parser_still_denies_a_slot_it_did_not_rule_out"
    ],
    "structured_parser_joined_form_value_not_whole_word": [
        "test_structured_parser_joined_form_contributes_the_value_not_the_whole_word"
    ],
    "structured_parser_retired_key_rejected": ["test_a_retired_structured_parser_key_is_rejected_at_decision_time"],
    "structured_parser_undeclared_bare_flag_allows": ["test_structured_parser_undeclared_bare_flag_still_allows"],
    "structured_parser_paths_filter_heuristic_survives": [
        "test_structured_parser_paths_filter_heuristic_still_rejects_an_undeclared_in_project_path"
    ],
    "unknowable_argument_in_a_slot_the_parser_rules_out": [
        "test_a_parser_that_classifies_the_slot_as_a_mode_earns_a_substitution",
        "test_a_pattern_slot_is_not_a_path_operand_even_when_its_value_is_unknowable",
    ],
    "has_no_path_parameters_earns_a_substitution": [
        "test_an_honest_has_no_path_parameters_earns_a_substitution"
    ],
    # --- parsers and propagation ---
    "parser_publishes_named_value": [
        "test_an_external_script_parser_can_publish_a_command_that_reaches_blocked_commands"
    ],
    "propagated_command_reenters_pipeline": ["test_a_propagated_command_is_checked_against_blocked_commands"],
    "propagation_extracts_nothing": ["test_an_entry_whose_nested_command_filter_has_nothing_to_check_does_not_match"],
    "propagation_depth_exceeded": ["test_exceeding_the_propagation_depth_limit_is_denied"],
    "parser_declares_no_such_option": [
        "test_option_value_filter_is_rejected_when_the_parser_declares_no_such_option"
    ],
    "parser_declares_option_without_value": [
        "test_option_value_filter_is_rejected_when_the_parser_declares_the_option_takes_no_value"
    ],
    "parser_declares_option_consuming_value": [
        "test_option_value_filter_loads_when_the_parser_declares_the_option_consumes_a_value",
        "test_option_value_filter_loads_when_the_parser_declares_both_kinds_of_option",
    ],
    "nested_command_filter_composes": [
        "test_a_nested_command_filter_composes_with_other_filters_across_entries"
    ],
    "nested_command_filter_without_capable_parser": [
        "test_a_nested_command_filter_needs_a_parser_that_publishes_sub_commands"
    ],
    "propagation_cannot_see_piped_operands": [
        "test_propagation_does_not_see_operands_arriving_on_stdin",
        "test_a_sensitive_path_written_on_the_line_is_caught_even_when_piped_onward",
    ],
    # --- paths and redirects ---
    "argument_path_outside_prefixes": ["test_an_additional_allowed_prefix_does_not_match_a_longer_sibling_directory"],
    "argument_path_within_additional_prefix": ["test_a_path_under_an_additional_allowed_prefix_is_permitted"],
    "argument_path_normalised_before_judging": ["test_argument_paths_are_judged_after_normalisation"],
    "entry_path_validation_disabled": [
        "test_entry_level_path_validation_false_disables_only_the_argument_path_check"
    ],
    "redirect_target_outside_prefixes": ["test_a_redirect_leaving_the_project_is_denied_whatever_its_quoting"],
    "redirect_target_unresolvable": ["test_an_unresolvable_redirect_target_is_denied_never_resolved_to_cwd"],
    "paths_filter_exactly_match": [
        "test_a_relative_paths_filter_entry_resolves_against_the_project_not_the_process_cwd"
    ],
    "paths_filter_rejects": ["test_entry_level_path_validation_false_does_not_disable_the_paths_filter"],
    "argument_path_double_quote_evasion": [
        "test_a_double_quoted_path_argument_cannot_evade_the_project_containment_check"
    ],
    "redirect_target_double_quote_evasion_reason_fidelity": [
        "test_a_double_quoted_redirect_outside_the_project_denies_naming_the_real_path"
    ],
    # --- escalation paths ---
    "bypass_wrapper_sole_command": ["test_the_bypass_wrapper_yields_passthrough_rather_than_allow"],
    "bypass_wrapper_chained_alongside": ["test_the_bypass_wrapper_does_not_cover_a_command_chained_alongside_it"],
    "bypass_wrapper_double_quoted_inner_command": [
        "test_the_bypass_wrapper_treats_a_double_quoted_inner_command_like_the_single_quoted_form"
    ],
    "redirect_veto_overrides_bypass": [
        "test_the_shell_performed_redirect_veto_is_never_waived_but_escalates_to_a_human"
    ],
    "add_allow_policy_forces_ask": ["test_add_allow_policy_forces_ask_as_the_durable_fix_escalation"],
    "add_allow_policy_grammar_violation_redirect": [
        "test_add_allow_policy_denies_an_unquoted_redirect_as_wrong_usage"
    ],
    "add_allow_policy_grammar_violation_multiple_command_arguments": [
        "test_add_allow_policy_denies_an_unquoted_multi_word_command_with_no_redirect_involved"
    ],
    "add_allow_policy_grammar_violation_shell_touched_via_paramexp_in_entry": [
        "test_add_allow_policy_denies_a_parameter_expansion_in_the_command_entry"
    ],
    # --- spawn-claude span-classifying bundled parser (improvement-20260920-142519) ---
    "spawn_claude_forwarded_span_total_path_candidacy": [
        "test_a_path_valued_claude_flag_forwarded_by_spawn_claude_denies"
    ],
    "spawn_claude_forwarded_span_unknowable_denies": [
        "test_a_substitution_forwarded_to_claude_denies_as_an_unknowable_path_argument"
    ],
    "spawn_claude_session_name_and_prompt_spans_are_not_path_candidates": [
        "test_a_real_orchestrator_dispatch_still_allows_as_a_regression_guard",
        "test_a_prompt_that_merely_mentions_a_path_valued_flag_in_prose_still_allows",
        "test_the_session_name_slot_is_never_a_path_candidate_even_when_it_looks_like_an_absolute_path",
        "test_a_substitution_landing_in_the_session_name_slot_still_allows",
        "test_a_substitution_landing_in_the_prompt_span_still_allows",
    ],
    "spawn_claude_in_project_forwarded_path_allows": ["test_an_in_project_forwarded_directory_still_allows"],
}


def test_every_matching_branch_has_at_least_one_specification_case():
    uncovered = sorted(branch for branch, cases in MATCHING_BRANCH_COVERAGE.items() if not cases)

    assert not uncovered, (
        "These matching-level branches have no specification case:\n  " + "\n  ".join(uncovered)
    )


def test_every_case_named_in_the_coverage_manifest_exists():
    """Without this, renaming a test silently orphans its branch and the
    manifest degrades into a list of things someone once intended to cover.
    """
    defined = set(globals())
    missing = sorted(
        {case for cases in MATCHING_BRANCH_COVERAGE.values() for case in cases} - defined
    )

    assert not missing, "Manifest names cases that do not exist:\n  " + "\n  ".join(missing)
