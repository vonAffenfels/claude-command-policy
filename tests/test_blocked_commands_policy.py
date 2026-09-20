"""Unit tests for BlockedCommandsPolicy: Pass 1, out-ranking the allowlist
for the same program."""

from blocked_commands_policy import BlockedCommandsPolicy
from name_collection import BlockedCommands
from pass_ import Pass
from reason import BlockedCommandInvoked
from statement import Statement


def _policy(names, command):
    policy = BlockedCommandsPolicy(BlockedCommands.from_entries(names))
    return policy.for_statement(Statement.from_command(command))


def test_pass_is_one_out_ranking_the_allowlist():
    assert BlockedCommandsPolicy(BlockedCommands.from_entries([])).pass_ == Pass.BLOCKED_COMMANDS


def test_does_not_match_when_no_blocked_program_is_invoked():
    policy = _policy(["rm"], "echo hi")

    assert policy.matches() is False


def test_matches_when_the_top_level_program_is_blocked():
    policy = _policy(["rm"], "rm -rf /")

    assert policy.matches() is True
    assert BlockedCommandInvoked("rm") in policy.decision().reason


def test_matches_a_blocked_program_invoked_in_a_later_statement():
    """Multi-statement commands are walked sub-statement by sub-statement -
    `cat a; rm b` must catch the blocked program even though it is not the
    first invocation."""
    policy = _policy(["rm"], "cat a; rm b")

    assert policy.matches() is True
