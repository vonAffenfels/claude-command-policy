"""CommandSubstitutionPolicy: Pass 2, active only when
commandSubstitutionResponse == "deny". Denies outright on ANY CmdSubst/
ProcSubst anywhere in the statement (recursing into every sub-statement,
including inside a heredoc body - shfmt parses an unquoted heredoc's
interpolated content the same way, so the generic recursive scan already
reaches it with no special-casing), without inspecting the inner command at
all.

When commandSubstitutionResponse is "via-allowed-commands" (the default),
this policy never matches - that mode's inner-command check instead happens
inside AllowedCommandPolicy's own recursion (see allowed_command_policy.py),
because "echo $(cat /etc/passwd)" with only "echo" allow-listed must still
deny, which only the vouching pass's recursive re-entry can decide.
"""

from __future__ import annotations

from pass_ import Pass
from permission_decision import PermissionDecision
from policy import Policy
from reason import CommandSubstitutionPresent
from statement import CmdSubst, ProcSubst


class CommandSubstitutionPolicy(Policy):
    pass_ = Pass.COMMAND_SUBSTITUTION

    def __init__(self, deny_mode_active):
        super().__init__()
        self._deny_mode_active = deny_mode_active

    def matches(self):
        return self._deny_mode_active and contains_substitution(self.statement)

    def decision(self):
        return PermissionDecision.deny((CommandSubstitutionPresent(),))


def contains_substitution(statement):
    if isinstance(statement, (CmdSubst, ProcSubst)):
        return True
    return any(contains_substitution(child) for child in statement.sub_statements())
