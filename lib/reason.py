"""Reason: the facts behind one objection in a denial's reason list.

`PermissionDecision.deny(reasons)` now carries a TUPLE of these rather than a
single prose string (see permission_decision.py's hand-back from leaf
20260914-213652). The list is FLAT and HETEROGENEOUS - a command can
legitimately carry both a categorical objection (it is simply forbidden,
whatever else is true) and a near-miss objection (some allowedCommands entry
almost vouched for it) at once, which is exactly why they share one list
rather than two homogeneous ones (see the improvement's Design Decisions,
'The shape of a denial's reason').

Each Reason carries FACTS ONLY - which path, which program, which filter type
- never prose. Prose is rendered from these facts in exactly one place,
reason_renderer.py, so wording can change without touching a Policy class.

Kept deliberately SMALL (1-2 fields each) so a test can construct the
expected value by hand - a Reason needing more than that is a signal to split
it rather than to reach for a builder (see the improvement's Test
Architecture).

`@dataclass(frozen=True)` gives free structural equality/repr/hash - a new
convention for this leaf rather than the hand-rolled `__eq__` every other
value object in this package writes, chosen because a test comparing Reason
values benefits from it directly (see the improvement's Testability-driven
production decisions).

CATEGORICAL vs NEAR-MISS is a classification by ORIGIN, not by anything the
ordinary decision pipeline needs to branch on (any Reason present denies,
full stop - see config.py's _decision_for_statement). It matters only to the
bypass-policy escalation transformer (escalation_policy.py), which forces
`ask` specifically for the categorical kinds a wrapper cannot legitimately
launder around: a shell-performed redirect, a blocked command, or a
sensitive path are true regardless of which program ends up running, while
every near-miss kind is a property of one particular allowedCommands entry's
own vouching attempt.
"""

from __future__ import annotations

from dataclasses import dataclass


# -- categorical: true independent of any allowedCommands entry -------------


@dataclass(frozen=True)
class SensitivePathReferenced:
    path: str


@dataclass(frozen=True)
class BlockedCommandInvoked:
    program: str


@dataclass(frozen=True)
class CommandSubstitutionPresent:
    """No facts beyond its own kind - `commandSubstitutionResponse: 'deny'`
    denies on ANY substitution without inspecting it (see
    command_substitution_policy.py)."""


@dataclass(frozen=True)
class SensitiveVariableReferenced:
    name: str


@dataclass(frozen=True)
class RedirectOutsideAllowedPaths:
    target: str


CATEGORICAL_REASON_TYPES = (
    SensitivePathReferenced,
    BlockedCommandInvoked,
    CommandSubstitutionPresent,
    SensitiveVariableReferenced,
    RedirectOutsideAllowedPaths,
)


# -- near-miss: a specific allowedCommands entry's own vouching failed ------


@dataclass(frozen=True)
class ProgramNotAllowListed:
    """CASE A (old vocabulary): no allowedCommands entry names this program
    at all."""

    program: str


@dataclass(frozen=True)
class SubstitutedCommandNotAllowListed:
    """`commandSubstitutionResponse: 'via-allowed-commands'`: a CmdSubst/
    ProcSubst this invocation carries does not itself name an allow-listed
    program - checked before any entry for the OUTER program is even
    considered (see allowed_command_policy.py)."""

    program: str


@dataclass(frozen=True)
class ParserCouldNotInterpretInvocation:
    """CASE B: an entry's own commandParser could not make sense of this
    invocation's arguments at all (before any filter is even evaluated)."""

    program: str


@dataclass(frozen=True)
class DisallowedVariableReferenced:
    """CASE B: this invocation references a variable the matched entry never
    declared in `onlyTheseVariables` - deny-by-default, not a narrowing."""

    program: str
    variable: str


@dataclass(frozen=True)
class ArgumentPathOutsideAllowedPaths:
    """CASE B: the matched entry does not set `hasNoPathParameters` and one
    of this invocation's own argument paths resolves outside the project/
    allowed prefixes."""

    program: str
    path: str


@dataclass(frozen=True)
class UnknowablePathArgument:
    """CASE B: the matched entry does not set `hasNoPathParameters`, and an
    argument whose value cannot be known at analysis time (a variable, a
    command substitution) occupies a slot this entry's own parser treats as
    a path operand.

    Distinct from `ArgumentPathOutsideAllowedPaths` because the fact is
    different in kind: there, a path IS known and sits outside the boundary;
    here, no path can be named at all, so there is nothing to report as
    'outside' and nothing to prove contained either. Carries only the
    program - naming the fragment would suggest the engine knows more about
    the argument than it does."""

    program: str


@dataclass(frozen=True)
class FilterRejected:
    """CASE B: one of the matched entry's own filters rejected this
    invocation - `filter_type` names which kind (e.g. 'optionPresent'),
    never the pattern/option itself, keeping this Reason small enough to
    construct by hand in a test."""

    program: str
    filter_type: str


NEAR_MISS_REASON_TYPES = (
    ProgramNotAllowListed,
    SubstitutedCommandNotAllowListed,
    ParserCouldNotInterpretInvocation,
    DisallowedVariableReferenced,
    ArgumentPathOutsideAllowedPaths,
    UnknowablePathArgument,
    FilterRejected,
)


# -- routing note, not an objection -----------------------------------------


@dataclass(frozen=True)
class NotEscalatedByAnUnrelatedBypassWrapper:
    """`bypass-policy` appears elsewhere on this line but does not wrap the
    command a categorical objection above this in the list is about - only
    what the wrapper actually invokes escalates (the deliberate carve-out
    against `bypass-policy true && rm -rf /` upgrading the unwrapped `rm`
    from deny to ask - see escalation_policy.py's module docstring). Never
    itself the reason a command was denied; always accompanies a categorical
    Reason it clarifies, naming the fix: wrap the objecting command
    explicitly to escalate it."""


# -- add-allow-policy's own strict grammar (never produced by the ordinary
#    policy pipeline - only by escalation_policy.add_allow_policy_transform) --


@dataclass(frozen=True)
class AddAllowPolicyGrammarViolation:
    """`add-allow-policy` was invoked in a shape other than the ONE accepted
    grammar - `--scope <user|project> --intent "<why>" "<command>"`, with the
    command reaching the tool as a single unmangled argument.

    `violation` is a short controlled-vocabulary code (never prose - see the
    renderer, the one place that turns it into the "wrong use of
    add-allow-policy. Correct use: ..." explanation): `missing_scope`,
    `duplicate_scope`, `invalid_scope_value`, `missing_intent`,
    `no_command_argument`, `multiple_command_arguments`,
    `redirect_on_invocation`, or `shell_touched` (a pipeline, a && / || / ;
    list, backgrounding, or command substitution anywhere in the invocation).

    Quoting is semantic here, not cosmetic: an unquoted
    `add-allow-policy --scope user --intent "x" echo something > somewhere`
    persists the policy "echo something" while the OUTER shell performs
    "> somewhere" against add-allow-policy's own stdout - a different thing
    than what the caller asked to allow. The grammar exists to guarantee the
    command reaches the tool as ONE unmangled argument."""

    violation: str


@dataclass(frozen=True)
class AddAllowPolicyProposalInvalid:
    """add-allow-policy's proposed ENTRY (not its grammar - see
    AddAllowPolicyGrammarViolation for that separate concern) has a
    construction-time problem `AllowedCommand.from_entry` would find loading
    it for real: an unrecognised filter/parser type, an uncompilable
    pattern, a malformed `programGlob`, an `optionValue`/`nestedCommand`
    filter naming a capability its parser (statically, or per its own
    describe response) does not have, and so on - the SAME `problems()` a
    merged config's own entries report through `Config.warnings()`.

    Caught and reported BEFORE asking (improvement 20260925-120037): a human
    approving the dialog should never be asked to bless an entry that would
    itself never vouch for anything. One Reason per problem, following the
    flat/heterogeneous reason-list convention every other Pass uses, rather
    than bundling every problem into one Reason's own tuple field."""

    problem: str

