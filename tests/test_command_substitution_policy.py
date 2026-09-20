"""Unit tests for CommandSubstitutionPolicy: Pass 2, active only in
commandSubstitutionResponse "deny" mode."""

from command_substitution_policy import CommandSubstitutionPolicy
from pass_ import Pass
from statement import Statement


def _policy(deny_mode_active, command):
    policy = CommandSubstitutionPolicy(deny_mode_active)
    return policy.for_statement(Statement.from_command(command))


def test_pass_is_two():
    assert CommandSubstitutionPolicy(True).pass_ == Pass.COMMAND_SUBSTITUTION


def test_never_matches_when_deny_mode_is_inactive_even_with_a_substitution_present():
    policy = _policy(False, "echo $(echo safe)")

    assert policy.matches() is False


def test_does_not_match_a_command_with_no_substitution_even_in_deny_mode():
    policy = _policy(True, "echo hi")

    assert policy.matches() is False


def test_matches_a_top_level_substitution_in_deny_mode():
    policy = _policy(True, "echo $(echo safe)")

    assert policy.matches() is True


def test_matches_a_substitution_buried_inside_a_redirect_target():
    policy = _policy(True, 'cat < "$(echo /etc/passwd)"')

    assert policy.matches() is True


def test_matches_a_substitution_nested_inside_a_later_statement():
    policy = _policy(True, "echo hi; cat $(echo /etc/passwd)")

    assert policy.matches() is True
