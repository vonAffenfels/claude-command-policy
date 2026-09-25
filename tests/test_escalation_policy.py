"""Unit tests for the two escalation transformers, independent of the
black-box decision spec suite (test_permission_decisions.py's Batch 5 covers
the end-to-end behavioural contract through Config.decision_for).
"""

from escalation_policy import add_allow_policy_transform, bypass_chain_hint, bypass_transform
from permission_decision import PermissionDecision
from reason import (
    AddAllowPolicyGrammarViolation,
    AddAllowPolicyProposalInvalid,
    BlockedCommandInvoked,
    NotEscalatedByAnUnrelatedBypassWrapper,
    ProgramNotAllowListed,
)
from statement import Statement


def test_bypass_transform_is_none_for_a_statement_it_does_not_recognize():
    statement = Statement.from_command("echo hi")

    assert bypass_transform(statement, PermissionDecision.allow(), lambda text: None) is None


def test_bypass_transform_allows_when_nothing_objects():
    statement = Statement.from_command("bypass-policy echo hi")
    ordinary = PermissionDecision.deny((ProgramNotAllowListed("bypass-policy"),))

    result = bypass_transform(statement, ordinary, lambda text: PermissionDecision.allow())

    assert result == PermissionDecision.allow()


def test_bypass_transform_passes_through_an_ordinary_near_miss():
    statement = Statement.from_command("bypass-policy some-tool")
    ordinary = PermissionDecision.deny((ProgramNotAllowListed("bypass-policy"),))

    result = bypass_transform(
        statement, ordinary, lambda text: PermissionDecision.deny((ProgramNotAllowListed("some-tool"),))
    )

    assert result.decision == "passthrough"


def test_bypass_transform_forces_ask_for_a_blocked_command():
    statement = Statement.from_command("bypass-policy rm -rf /")
    ordinary = PermissionDecision.deny((ProgramNotAllowListed("bypass-policy"),))

    result = bypass_transform(
        statement, ordinary, lambda text: PermissionDecision.deny((BlockedCommandInvoked("rm"),))
    )

    assert result.decision == "ask"
    assert "rm" in result.reason


def test_bypass_transform_does_not_call_decide_wrapped_text_when_there_are_no_arguments():
    statement = Statement.from_command("bypass-policy")
    ordinary = PermissionDecision.deny((ProgramNotAllowListed("bypass-policy"),))

    result = bypass_transform(
        statement,
        ordinary,
        lambda text: (_ for _ in ()).throw(AssertionError("should not be called for an empty wrapped text")),
    )

    assert result == PermissionDecision.allow()


def test_bypass_chain_hint_is_none_when_the_wrapper_is_absent():
    statement = Statement.from_command("rm -rf /")
    ordinary = PermissionDecision.deny((BlockedCommandInvoked("rm"),))

    assert bypass_chain_hint(statement, ordinary) is None


def test_bypass_chain_hint_is_none_when_the_wrapper_covers_the_whole_line():
    statement = Statement.from_command("bypass-policy rm -rf /")
    ordinary = PermissionDecision.deny((ProgramNotAllowListed("bypass-policy"),))

    assert bypass_chain_hint(statement, ordinary) is None


def test_bypass_chain_hint_is_none_for_an_ordinary_near_miss():
    statement = Statement.from_command("bypass-policy echo hi && some-tool")
    ordinary = PermissionDecision.deny((ProgramNotAllowListed("some-tool"),))

    assert bypass_chain_hint(statement, ordinary) is None


def test_bypass_chain_hint_augments_a_blocked_command_chained_alongside_the_wrapper():
    statement = Statement.from_command("bypass-policy echo hi && rm -rf /")
    ordinary = PermissionDecision.deny((BlockedCommandInvoked("rm"),))

    hinted = bypass_chain_hint(statement, ordinary)

    assert hinted.decision == "deny"
    assert BlockedCommandInvoked("rm") in hinted.reason
    assert NotEscalatedByAnUnrelatedBypassWrapper() in hinted.reason


def test_add_allow_policy_transform_is_none_for_a_statement_it_does_not_recognize():
    statement = Statement.from_command("echo hi")

    assert add_allow_policy_transform(statement) is None


# -- the strict grammar (reopened 2026-09-17) --------------------------------
#
# The ONLY accepted shape is `add-allow-policy --scope <user|project> --intent
# "<why>" "<command>"`, with the command reaching the tool as ONE unmangled
# argument - see this leaf's Design Decisions, 'Whether the strict
# add-allow-policy grammar fixes flag ORDER or only flag/positional shape',
# for why flag ORDER itself is not part of what is enforced. Every malformed
# shape denies via the single reason renderer (lib/reason_renderer.py) rather
# than a hand-built prose string at this call site.


def test_add_allow_policy_transform_forces_ask_for_the_canonical_quoted_form():
    """Double-quoted, matching the canonical template literally. Reads its
    real content via `Argument.text` (statement.py), which recursively
    unwraps a `DblQuoted` word's own nested Parts (improvement-20260918-205740
    merged this recovery into `.text` itself) - before that fix, `.text`'s
    naive one-level concatenation (see test_statement.py's
    test_a_double_quoted_word_with_no_substitution_reads_its_real_content)
    left this dialog showing an empty command and an empty intent for
    exactly this, the operator-mandated canonical form."""
    statement = Statement.from_command('add-allow-policy --scope user --intent "testing" "rg"')

    result = add_allow_policy_transform(statement)

    assert result.decision == "ask"
    assert "rg" in result.reason
    assert "testing" in result.reason
    assert "user" in result.reason


def test_add_allow_policy_transform_forces_ask_and_names_the_proposed_entry():
    """Single-quoted: `SglQuoted` carries its literal `Value` directly (unlike
    `DblQuoted`), so this is the quoting style that let a content assertion
    exercise what the human sees in the ask dialog even before the
    double-quote fix existed. Kept alongside the double-quoted case above
    for both quoting styles' coverage."""
    statement = Statement.from_command("add-allow-policy --scope user --intent 'testing' 'rg'")

    result = add_allow_policy_transform(statement)

    assert result.decision == "ask"
    assert "rg" in result.reason
    assert "testing" in result.reason
    assert "user" in result.reason


def test_add_allow_policy_transform_accepts_a_double_quoted_scope_value():
    """Regression cover for the defect found in review: a double-quoted
    `--scope "user"` was wrongly DENIED as `invalid_scope_value` because the
    value used to read as "" through `Argument.text` - a false rejection of
    a legitimate, correctly quoted canonical invocation, not merely a
    display bug. Fixed at the source (improvement-20260918-205740 merged the
    double-quote recovery into `.text` itself), not at this call site."""
    statement = Statement.from_command('add-allow-policy --scope "user" --intent "x" "rg"')

    result = add_allow_policy_transform(statement)

    assert result.decision == "ask"
    assert "user" in result.reason
    assert "rg" in result.reason


def test_add_allow_policy_transform_forces_ask_regardless_of_flag_order():
    """Order-agnostic by design (see the Design Decision cited above) - only
    the FLAG SHAPE is fixed, not a byte-for-byte positional template."""
    statement = Statement.from_command("add-allow-policy --intent 'testing' --scope user 'rg'")

    result = add_allow_policy_transform(statement)

    assert result.decision == "ask"


def test_add_allow_policy_transform_denies_a_missing_scope():
    statement = Statement.from_command('add-allow-policy --intent "testing" "rg"')

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("missing_scope") in result.reason


def test_add_allow_policy_transform_denies_a_repeated_scope():
    statement = Statement.from_command(
        'add-allow-policy --scope user --scope project --intent "testing" "rg"'
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("duplicate_scope") in result.reason


def test_add_allow_policy_transform_denies_a_scope_value_other_than_user_or_project():
    statement = Statement.from_command('add-allow-policy --scope global --intent "testing" "rg"')

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("invalid_scope_value") in result.reason


def test_add_allow_policy_transform_denies_a_missing_intent():
    """`--intent` is now required by the GRAMMAR itself (operator decision,
    reopening this leaf), not only by the bin script's write-time validation
    in lib/add_allow_write.py - defence in depth, not a replacement."""
    statement = Statement.from_command('add-allow-policy --scope user "rg"')

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("missing_intent") in result.reason


def test_add_allow_policy_transform_denies_zero_command_arguments():
    statement = Statement.from_command('add-allow-policy --scope user --intent "testing"')

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("no_command_argument") in result.reason


def test_add_allow_policy_transform_denies_more_than_one_command_argument():
    """An unquoted multi-word command splits into several arguments - exactly
    the shape the grammar exists to reject, even with no redirect involved."""
    statement = Statement.from_command('add-allow-policy --scope user --intent "testing" echo hi')

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("multiple_command_arguments") in result.reason


def test_add_allow_policy_transform_denies_a_redirect_on_the_invocation_itself():
    """The flagship malformed shape: `add-allow-policy --scope user --intent
    "x" echo something > somewhere` persists the policy "echo something" while
    the outer shell performs "> somewhere" against add-allow-policy's own
    stdout - a different thing than what the caller asked to allow."""
    statement = Statement.from_command(
        'add-allow-policy --scope user --intent "x" echo something > somewhere'
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("redirect_on_invocation") in result.reason


def test_add_allow_policy_transform_denies_when_chained_with_another_command():
    statement = Statement.from_command(
        'add-allow-policy --scope user --intent "x" "rg" && rm -rf /'
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("shell_touched") in result.reason


def test_add_allow_policy_transform_denies_when_piped():
    statement = Statement.from_command('add-allow-policy --scope user --intent "x" "rg" | cat')

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("shell_touched") in result.reason


def test_add_allow_policy_transform_denies_when_backgrounded():
    statement = Statement.from_command('add-allow-policy --scope user --intent "x" "rg" &')

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("shell_touched") in result.reason


def test_add_allow_policy_transform_denies_a_parameter_expansion_in_the_entry_argument():
    """Finding 5 (improvement-20260918-205740): a bare `ParamExp` in the
    entry argument is invisible to `Statement.as_sole_invoked_program()`'s
    own shell_touched gate (checked by the caller, `add_allow_policy_
    transform`, before this function is even reached) - that gate only sees
    `CmdSubst`/`ProcSubst`, which are Statement subtypes reachable via
    `sub_statements()`, where a `ParamExp` is not. `_classify_add_allow_
    invocation` is the one place left that can catch it, via the entry
    argument's own `referenced_variables`. Without this, the human would see
    a narrower entry string ('cat /file') than `lib/add_allow_write.py`
    would actually persist (it parses real post-expansion argv)."""
    statement = Statement.from_command(
        'add-allow-policy --scope user --intent "x" "cat $HOME/file"'
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("shell_touched") in result.reason


def test_add_allow_policy_transform_accepts_a_double_quoted_entry_with_no_variable():
    """The flagship KB example must remain accepted - a double-quoted entry
    with no variable reference is not shell_touched merely for being
    quoted."""
    statement = Statement.from_command(
        'add-allow-policy --scope user --intent "x" "echo something > somewhere"'
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "ask"


def test_add_allow_policy_transform_denies_command_substitution_anywhere_in_it():
    statement = Statement.from_command(
        'add-allow-policy --scope user --intent "$(echo x)" "rg"'
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert AddAllowPolicyGrammarViolation("shell_touched") in result.reason


# -- refusing a well-formed grammar's malformed ENTRY, before asking --------
#
# improvement 20260925-120037: the grammar can be perfectly formed while the
# proposed entry itself would never vouch for anything once loaded for real.


def test_add_allow_policy_transform_denies_a_proposal_naming_an_unknown_filter_type():
    entry = '{"program": "echo", "filters": [{"type": "madeUp", "action": "block"}]}'
    statement = Statement.from_command(
        f'add-allow-policy --scope user --intent "testing" \'{entry}\''
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    [reason] = result.reason
    assert isinstance(reason, AddAllowPolicyProposalInvalid)
    assert "madeUp" in reason.problem


def test_add_allow_policy_transform_denies_a_proposal_with_a_malformed_program_glob():
    entry = '{"programGlob": {"marketplace": "m", "plugin": "p", "path": "/bin/foo"}}'
    statement = Statement.from_command(
        f'add-allow-policy --scope user --intent "testing" \'{entry}\''
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    assert any(isinstance(reason, AddAllowPolicyProposalInvalid) for reason in result.reason)


def test_add_allow_policy_transform_denies_invalid_json():
    statement = Statement.from_command(
        "add-allow-policy --scope user --intent \"testing\" '{not json'"
    )

    result = add_allow_policy_transform(statement)

    assert result.decision == "deny"
    [reason] = result.reason
    assert isinstance(reason, AddAllowPolicyProposalInvalid)
    assert "not valid JSON" in reason.problem
