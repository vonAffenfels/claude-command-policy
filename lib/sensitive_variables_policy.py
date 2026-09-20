"""SensitiveVariablesPolicy: an objection over `sensitiveVariables`, the
config-wide denylist of variable names that are denied outright wherever
referenced - independent of any entry's own `onlyTheseVariables` vouching
(AllowedCommandPolicy's concern). An entry can vouch for referencing a
variable and this policy still denies it
(`test_a_sensitive_variable_reference_is_denied` declares the variable in
both places and still expects deny).

NOT one of the plan's original five passes - added because the acceptance
suite's ordering cases pin it as its own independently-ordered objection
between CommandSubstitution and RedirectPathValidation (see pass_.py's
docstring for the full rationale).

Matches via a `$NAME`/`${NAME}` regex scan of the command's raw text, the
same "operate on raw text, not the parsed tree" simplification
SensitivePathsPolicy makes (see its own docstring) - shfmt's ParamExp word
nodes are not modelled by Statement at all, and a regex scan is simple,
robust, and sufficient for every case this suite exercises.
"""

from __future__ import annotations

import re

from pass_ import Pass
from permission_decision import PermissionDecision
from policy import Policy
from reason import SensitiveVariableReferenced


class SensitiveVariablesPolicy(Policy):
    pass_ = Pass.SENSITIVE_VARIABLES

    def __init__(self, sensitive_variables, command_text):
        super().__init__()
        self._sensitive_variables = sensitive_variables
        self._command_text = command_text

    def _matched(self):
        return sorted(
            name
            for name in self._sensitive_variables.names
            if re.search(rf"\$\{{?{re.escape(name)}\b", self._command_text)
        )

    def matches(self):
        return bool(self._matched())

    def decision(self):
        return PermissionDecision.deny(tuple(SensitiveVariableReferenced(name) for name in self._matched()))


def variable_references_in(command_text):
    """Every `$NAME`/`${NAME}` variable name referenced anywhere in
    `command_text` - shared with allowed_command_policy.py's per-entry
    `onlyTheseVariables` vouching, which asks the same "which variables does
    this command reference" question against a different, per-entry
    declared set.
    """
    return set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", command_text))
