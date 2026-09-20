"""Pass: the strict, total, greppable ordering the policy pipeline sorts by.

Passes order the OBJECTIONS, not the matches (see permission_decision.py and
config.py's decision_for). The decision is the first objection in pass order;
`allow` is the absence of any objection - never re-derive this as "lowest
matching pass wins", which inverts the redirect-validation case and fails
open (see the improvement's asymmetry analysis).

Named `pass_.py` rather than the plan's `pass.py`: `pass` is a Python
keyword, so `import pass` / `from pass import Pass` is a SyntaxError - a
gap in the plan discovered while implementing it (verified directly rather
than assumed). `Pass` (the class) is unaffected; only the module's own
filename needed the trailing underscore.

SensitiveVariables is a sixth pass, not in the plan's original five-pass
list (SensitivePaths/BlockedCommands/CommandSubstitution/
RedirectPathValidation/AllowedCommand) - added because the acceptance
suite's ordering cases (`test_substitution_policy_is_decided_before_
sensitive_variable_detection`, `test_a_sensitive_path_is_decided_before_a_
sensitive_variable`, `test_a_sensitive_variable_is_decided_before_the_
allowlist_check`) pin `sensitiveVariables` (the config-wide denylist) as its
own independently-ordered objection, distinct from `onlyTheseVariables`
per-entry vouching (which stays folded into AllowedCommand per the plan).
The acceptance suite is the binding acceptance gate, so its ordering
requirements win over the plan's five-pass enumeration.
"""

from __future__ import annotations

import enum


class Pass(enum.IntEnum):
    SENSITIVE_PATHS = 0
    BLOCKED_COMMANDS = 1
    COMMAND_SUBSTITUTION = 2
    SENSITIVE_VARIABLES = 3
    REDIRECT_PATH_VALIDATION = 4
    ALLOWED_COMMAND = 5
