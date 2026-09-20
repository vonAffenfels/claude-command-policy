"""Pins the prose of a handful of REPRESENTATIVE reason lists - not one case
per decision case (the decision spec suite asserts reason STRUCTURE, never
rendered prose; see test_permission_decisions.py's assert_reason_includes/
assert_primary_reason). This is the only place wording is pinned at all.
"""

from reason import (
    AddAllowPolicyGrammarViolation,
    ArgumentPathOutsideAllowedPaths,
    BlockedCommandInvoked,
    CommandSubstitutionPresent,
    DisallowedVariableReferenced,
    FilterRejected,
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


def test_renders_every_reason_kind_without_crashing():
    """Not a wording pin for each - just proof every kind has a clause, so a
    newly-added Reason subtype that forgets to register with the renderer
    fails loudly (a repr fallback) rather than at some unrelated call site.
    """
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
        FilterRejected("echo", "optionPresent"),
        AddAllowPolicyGrammarViolation("redirect_on_invocation"),
    )

    text = render(every_kind)

    for reason in every_kind:
        assert repr(reason) not in text, f"{reason!r} fell through to the repr fallback"


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
