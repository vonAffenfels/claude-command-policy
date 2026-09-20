"""Unit tests for SensitivePathsPolicy: Pass 0, the absolute veto.

The black-box behaviour (substring over-matching, ordering against every
other pass) is pinned end-to-end in test_permission_decisions.py; these
tests exercise the class in isolation - construction, matches()/decision()
independent of the full pipeline.
"""

from pass_ import Pass
from reason import SensitivePathReferenced
from sensitive_path import SensitivePath
from sensitive_paths_policy import SensitivePathsPolicy


def _policy(literals, command_text):
    sensitive_paths = [SensitivePath.from_entry(literal) for literal in literals]
    return SensitivePathsPolicy(sensitive_paths, command_text).for_statement(None)


def test_pass_is_zero_the_absolute_veto():
    assert SensitivePathsPolicy([], "").pass_ == Pass.SENSITIVE_PATHS


def test_does_not_match_when_no_sensitive_path_appears():
    policy = _policy(["/etc/passwd"], "cat ./README.md")

    assert policy.matches() is False


def test_matches_when_a_sensitive_path_appears_as_a_substring():
    policy = _policy(["/etc/passwd"], "cat /etc/passwd")

    assert policy.matches() is True
    assert SensitivePathReferenced("/etc/passwd") in policy.decision().reason


def test_over_matches_a_literal_that_merely_contains_the_sensitive_text():
    """Flag List D1: deliberate, documented over-matching - not a bug."""
    policy = _policy(["/etc/passwd"], "cat /home/me/etc/passwd-backup")

    assert policy.matches() is True


def test_decision_lists_every_matched_literal_in_sorted_order():
    policy = _policy(["/vault/beta", "/vault/alpha"], "cat /vault/alpha /vault/beta")

    reason = policy.decision().reason

    assert reason == (SensitivePathReferenced("/vault/alpha"), SensitivePathReferenced("/vault/beta"))
