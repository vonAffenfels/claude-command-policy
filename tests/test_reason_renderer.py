"""Pins the prose of a handful of REPRESENTATIVE reason lists - not one case
per decision case (the decision spec suite asserts reason STRUCTURE, never
rendered prose; see test_permission_decisions.py's assert_reason_includes/
assert_primary_reason). This is the only place wording is pinned at all.
"""

from filter import Filter
from reason import (
    AddAllowPolicyEntryChangesNothing,
    AddAllowPolicyExampleRejected,
    AddAllowPolicyGrammarViolation,
    AddAllowPolicyProposalInvalid,
    ArgumentPathOutsideAllowedPaths,
    BlockedCommandInvoked,
    CommandSubstitutionPresent,
    DisallowedVariableReferenced,
    FilterRejected,
    FilterUnprovable,
    ParserCouldNotInterpretInvocation,
    ProgramNotAllowListed,
    RedirectOutsideAllowedPaths,
    SensitivePathReferenced,
    SensitiveVariableReferenced,
    SubstitutedCommandNotAllowListed,
    UnknowablePathArgument,
)
from reason_renderer import ADD_ALLOW_POLICY_CANONICAL_FORM, EQUIVALENCE_POINTER, render


def test_render_of_an_empty_reason_list_is_empty():
    assert render(()) == ""
    assert render(None) == ""


def test_every_denial_ends_with_the_unconditional_equivalence_pointer():
    text = render((ProgramNotAllowListed("rm"),))

    assert text.endswith(f"({EQUIVALENCE_POINTER})")
    assert "find-auto-allowed-command" in text


def test_the_equivalence_pointer_names_the_vehicle_as_a_dispatched_agent():
    """improvement-20260919-081655: the pointer used to name the target bare
    (vehicle-neutral between skill and agent). Now that the vehicle is
    settled as an agent, the pointer must say so explicitly rather than
    relying on the model inferring dispatch from the bare name alone."""
    text = render((ProgramNotAllowListed("rm"),))

    assert "find-auto-allowed-command" in text
    assert "agent" in text
    assert "dispatch" in text


def test_the_equivalence_pointer_states_what_to_pass_the_agent():
    """improvement-20260919-230721 review finding: the agent's own Input
    Contract stops it cold if the denied command or its deny reason is
    missing from its dispatch prompt - but the pointer never told the caller
    that, a one-sided contract. Both are already in the caller's own hands at
    the moment of denial (the command is its own just-attempted tool call;
    the reason is this very text), so the fix is naming them, not new
    plumbing."""
    text = render((ProgramNotAllowListed("rm"),))

    assert "denied command" in text
    assert "this reason" in text


def test_unknowable_path_argument_hint_points_at_a_different_program_not_a_flag_to_add():
    """Regression for a waiver-not-a-factual-claim wording defect: the old
    clause ('...or invoke a program whose entry declares
    hasNoPathParameters') could be misread as 'add that flag to this entry
    and the denial goes away' - live and load-bearing, since an audit of the
    operator's real config found the flag declared FALSELY on three entries,
    one of which measurably allowed a command substitution to reach a
    sensitive path. The hint must point at choosing a genuinely different
    program, never at declaring a flag on the one that was just denied.
    """
    text = render((UnknowablePathArgument("cat"),))

    assert "hasNoPathParameters" not in text
    assert "different program" in text


def test_renders_a_single_categorical_reason():
    text = render((SensitivePathReferenced("/etc/passwd"),))

    assert "sensitive path" in text
    assert "/etc/passwd" in text


def test_renders_a_single_near_miss_reason_naming_the_program():
    text = render((ProgramNotAllowListed("rm"),))

    assert "rm" in text
    assert "no allowedCommands entry vouches" in text


def test_renders_multiple_reasons_as_one_paragraph_primary_first():
    text = render((BlockedCommandInvoked("rm"), SensitivePathReferenced("/vault/secret.txt")))

    assert text.index("rm") < text.index("/vault/secret.txt")


SUBCOMMAND_RULE = Filter.from_definition(
    {"type": "namedValue", "name": "subcommand", "pattern": "^(status|commit)$", "action": "required"}
)


def test_a_rejected_filter_is_rendered_as_the_rule_it_broke():
    text = render((FilterRejected("git", SUBCOMMAND_RULE),))

    assert "git: rejected by the rule: value `subcommand` must be present and must match `^(status|commit)$`" in text


def test_an_unprovable_filter_names_the_unknowable_content_and_the_decomposition_route():
    text = render((FilterUnprovable("git", SUBCOMMAND_RULE),))

    assert "value `subcommand` must be present and must match `^(status|commit)$`" in text
    assert "$VAR or $(...)" in text
    assert "run the value-producing command first" in text


def test_a_redirect_outside_the_allowed_paths_names_the_session_scratchpad_as_an_allowed_location():
    text = render((RedirectOutsideAllowedPaths("/x/out.txt"),))

    assert "outside the project, the session scratchpad and the allowed prefixes" in text
    assert "/x/out.txt" in text


def test_an_argument_path_outside_the_allowed_paths_names_the_session_scratchpad_as_an_allowed_location():
    text = render((ArgumentPathOutsideAllowedPaths("cat", "/x/notes.txt"),))

    assert "cat: argument path outside the project, the session scratchpad and the allowed prefixes" in text
    assert "/x/notes.txt" in text


def test_renders_every_reason_kind_without_crashing():
    """Not a wording pin for each - just proof every kind has a clause, so a
    newly-added Reason subtype that forgets to register with the renderer
    fails loudly (a repr fallback) rather than at some unrelated call site.
    """
    echo_flag_rule = Filter.from_definition({"type": "optionPresent", "option": "--x", "action": "block"})
    every_kind = (
        SensitivePathReferenced("/x"),
        BlockedCommandInvoked("rm"),
        CommandSubstitutionPresent(),
        SensitiveVariableReferenced("TOKEN"),
        RedirectOutsideAllowedPaths("/x"),
        ProgramNotAllowListed("rm"),
        SubstitutedCommandNotAllowListed("cat"),
        ParserCouldNotInterpretInvocation("cat"),
        DisallowedVariableReferenced("echo", "HOME"),
        ArgumentPathOutsideAllowedPaths("cat", "/x"),
        FilterRejected("echo", echo_flag_rule),
        FilterUnprovable("echo", echo_flag_rule),
        AddAllowPolicyGrammarViolation("redirect_on_invocation"),
        AddAllowPolicyProposalInvalid("unknown filter type 'madeUp'"),
        AddAllowPolicyExampleRejected("git status", "why"),
        AddAllowPolicyEntryChangesNothing(),
    )

    text = render(every_kind)

    for reason in every_kind:
        assert repr(reason) not in text, f"{reason!r} fell through to the repr fallback"


def test_renders_the_proposed_entrys_own_problem():
    text = render((AddAllowPolicyProposalInvalid("unknown filter type 'madeUp'"),))

    assert text.startswith("add-allow-policy's proposed entry is invalid: unknown filter type 'madeUp'")
    assert text.endswith(f"({EQUIVALENCE_POINTER})")


def test_the_canonical_form_names_an_entry_not_a_command():
    assert "'<entry>'" in ADD_ALLOW_POLICY_CANONICAL_FORM
    assert '--example "<command>"' in ADD_ALLOW_POLICY_CANONICAL_FORM
    assert ADD_ALLOW_POLICY_CANONICAL_FORM.endswith("'<entry>'")


def test_renders_the_example_an_entry_would_not_allow_without_the_equivalence_pointer_inside_it():
    text = render((AddAllowPolicyExampleRejected("git status", "no allowedCommands entry vouches for: git"),))

    assert text.startswith(
        "add-allow-policy's proposed entry would not allow its own example 'git status': "
        "no allowedCommands entry vouches for: git"
    )
    assert text.count(EQUIVALENCE_POINTER) == 1


def test_renders_an_entry_that_changes_nothing():
    text = render((AddAllowPolicyEntryChangesNothing(),))

    assert "changes nothing" in text


def test_renders_the_wrong_use_of_add_allow_policy_teaching_the_correct_form():
    """Pins the shape Task 1 (reopened 2026-09-17) requires: 'wrong use of
    add-allow-policy. Correct use: ...' followed by the canonical form and a
    short explanation - never a hand-built prose string at the policy site.
    """
    text = render((AddAllowPolicyGrammarViolation("redirect_on_invocation"),))

    assert text.startswith("wrong use of add-allow-policy. Correct use: ")
    assert ADD_ALLOW_POLICY_CANONICAL_FORM in text
    assert "OUTER shell" in text
    assert text.endswith(f"({EQUIVALENCE_POINTER})")


def test_renders_a_short_explanation_for_each_add_allow_policy_violation_code():
    """Not a wording pin for each - just proof every violation code known to
    escalation_policy.py has an explanation, so a newly-added code that
    forgets to register here fails loudly (the generic fallback clause)
    rather than silently shipping an unexplained deny."""
    for violation in (
        "missing_scope",
        "duplicate_scope",
        "invalid_scope_value",
        "missing_intent",
        "no_command_argument",
        "multiple_command_arguments",
        "redirect_on_invocation",
        "shell_touched",
    ):
        text = render((AddAllowPolicyGrammarViolation(violation),))
        assert f"malformed invocation ({violation})" not in text, (
            f"{violation!r} fell through to the generic fallback explanation"
        )
