"""BlockedCommandsPolicy: Pass 1. Out-ranks the allowlist for the same
program (`test_blocked_commands_wins_over_allowed_commands_for_the_same_
program`) - a program invoked ANYWHERE in the statement (recursing into
every sub-statement) matching `blockedCommands` denies outright, regardless
of any allowedCommands entry.

Does not by itself see a wrapper's trailing positionals as an invocation
(`xargs rm` has one Command node, program "xargs" - "rm" is just an
argument) - that hole is exactly why the nested-command filter exists (see
allowed_command_policy.py); this policy only walks the statement's own
Command nodes.
"""

from __future__ import annotations

from pass_ import Pass
from permission_decision import PermissionDecision
from policy import Policy
from reason import BlockedCommandInvoked
from statement import Command


class BlockedCommandsPolicy(Policy):
    pass_ = Pass.BLOCKED_COMMANDS

    def __init__(self, blocked_commands):
        super().__init__()
        self._blocked_commands = blocked_commands

    def _invoked_programs(self):
        return _command_words(self.statement)

    def _matched(self):
        blocked = set(self._blocked_commands.names)
        return sorted({word for word in self._invoked_programs() if word in blocked})

    def matches(self):
        return bool(self._matched())

    def decision(self):
        return PermissionDecision.deny(tuple(BlockedCommandInvoked(word) for word in self._matched()))


def _command_words(statement):
    words = []
    if isinstance(statement, Command) and statement.command_word:
        words.append(statement.command_word)
    for child in statement.sub_statements():
        words.extend(_command_words(child))
    return words
