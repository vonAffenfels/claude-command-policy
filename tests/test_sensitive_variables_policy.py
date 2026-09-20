"""Unit tests for SensitiveVariablesPolicy: the config-wide denylist,
independent of any entry's own onlyTheseVariables vouching."""

from name_collection import SensitiveVariables
from pass_ import Pass
from reason import SensitiveVariableReferenced
from sensitive_variables_policy import SensitiveVariablesPolicy, variable_references_in


def _policy(names, command_text):
    policy = SensitiveVariablesPolicy(SensitiveVariables.from_entries(names), command_text)
    return policy.for_statement(None)


def test_pass_sits_between_substitution_and_redirect_validation():
    from pass_ import Pass as P

    policy_pass = SensitiveVariablesPolicy(SensitiveVariables.from_entries([]), "").pass_

    assert P.COMMAND_SUBSTITUTION < policy_pass < P.REDIRECT_PATH_VALIDATION


def test_does_not_match_when_no_sensitive_variable_is_referenced():
    policy = _policy(["AWS_SECRET_ACCESS_KEY"], "echo $HOME")

    assert policy.matches() is False


def test_matches_a_bare_dollar_reference():
    policy = _policy(["AWS_SECRET_ACCESS_KEY"], "echo $AWS_SECRET_ACCESS_KEY")

    assert policy.matches() is True
    assert SensitiveVariableReferenced("AWS_SECRET_ACCESS_KEY") in policy.decision().reason


def test_matches_a_braced_reference():
    policy = _policy(["API_TOKEN"], "echo ${API_TOKEN}")

    assert policy.matches() is True


def test_reports_multiple_matches_in_sorted_order():
    policy = _policy(["ALPHA_TOKEN", "BETA_TOKEN"], "echo $BETA_TOKEN $ALPHA_TOKEN")

    reason = policy.decision().reason

    assert reason == (
        SensitiveVariableReferenced("ALPHA_TOKEN"),
        SensitiveVariableReferenced("BETA_TOKEN"),
    )


def test_variable_references_in_finds_every_name_referenced():
    assert variable_references_in("echo $HOME ${API_TOKEN} plain") == {"HOME", "API_TOKEN"}


def test_variable_references_in_finds_nothing_in_a_plain_command():
    assert variable_references_in("echo hi") == set()
