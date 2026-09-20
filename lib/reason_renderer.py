"""render(reasons) -> str: the ONE place a Reason list becomes prose.

Every Policy (and the escalation transformers) constructs Reason value
objects carrying facts; nothing else in this package formats them into text.
This keeps wording changeable in one place without touching a Policy class
(see the improvement's Design Decisions, 'The shape of a denial's reason').

The equivalence-search pointer is UNCONDITIONAL - it is appended to every
non-empty reason list regardless of what kind of Reason it holds, because
even a near-miss ("this program almost vouched") does not mean the
resulting, adjusted command still does the job the caller needed (see the
improvement's Design Decisions, 'Which denials carry the equivalence
pointer'). It names `command-policy:find-auto-allowed-command`, a frozen
contract leaf 20260915-011123 must honour, kept to one short clause since it
appears on every denial. As of improvement-20260919-081655 this names an
AGENT to be dispatched (via the Task tool), not a same-conversation skill -
the wording says so explicitly rather than relying on the model to infer
dispatch from the bare name alone.

As of improvement-20260919-230721 the pointer also names what to pass the
agent: the denied command and this reason. The agent's own Input Contract
stops cold if either is missing from its dispatch prompt, which used to be a
one-sided contract - the caller had no way to learn that from the pointer
text alone. Both are already in the caller's own hands at the moment of
denial (the command is its own just-attempted tool call, still in its
context; the reason is this very rendered text), so naming them costs no new
plumbing, only two words.
"""

from __future__ import annotations

from reason import (
    AddAllowPolicyGrammarViolation,
    ArgumentPathOutsideAllowedPaths,
    BlockedCommandInvoked,
    CommandSubstitutionPresent,
    DisallowedVariableReferenced,
    FilterRejected,
    NotEscalatedByAnUnrelatedBypassWrapper,
    ParserCouldNotInterpretInvocation,
    ProgramNotAllowListed,
    RedirectOutsideAllowedPaths,
    SensitivePathReferenced,
    SensitiveVariableReferenced,
    SubstitutedCommandNotAllowListed,
    UnknowablePathArgument,
)

EQUIVALENCE_POINTER = (
    "dispatch the command-policy:find-auto-allowed-command agent, passing it this denied command and this reason, "
    "for an auto-approved alternative"
)

ADD_ALLOW_POLICY_CANONICAL_FORM = 'add-allow-policy --scope <user|project> --intent "<why>" "<command>"'

_ADD_ALLOW_POLICY_VIOLATION_EXPLANATIONS = {
    "missing_scope": "--scope <user|project> is required, given exactly once",
    "duplicate_scope": "--scope was given more than once",
    "invalid_scope_value": "--scope must be exactly 'user' or 'project'",
    "missing_intent": '--intent "<why>" is required',
    "no_command_argument": (
        "no command argument was given - the command to allow must be one quoted argument"
    ),
    "multiple_command_arguments": (
        "more than one command argument was given - the whole command must be a SINGLE quoted "
        "argument, or the outer shell will split it and only the first piece reaches the tool"
    ),
    "redirect_on_invocation": (
        "a redirect on this invocation is performed by the OUTER shell against add-allow-policy's "
        'own stdout, not by the tool - for example add-allow-policy --scope user --intent "x" echo '
        "something > somewhere persists the policy \"echo something\" while \"> somewhere\" never "
        'reaches the tool at all. Quote the whole command as ONE argument instead: '
        'add-allow-policy --scope user --intent "x" "echo something > somewhere"'
    ),
    "shell_touched": (
        "the outer shell has touched this invocation (a pipeline, a && / || / ; list, "
        "backgrounding, or command substitution) - add-allow-policy must be the only thing on the "
        "line so nothing else can intercept its arguments or its output"
    ),
}

_CLAUSE_BUILDERS = {
    SensitivePathReferenced: lambda r: f"sensitive path referenced: {r.path}",
    BlockedCommandInvoked: lambda r: f"blocked command invoked: {r.program}",
    CommandSubstitutionPresent: lambda r: (
        "command substitution is present and commandSubstitutionResponse is 'deny'"
    ),
    SensitiveVariableReferenced: lambda r: f"sensitive variable referenced: {r.name}",
    RedirectOutsideAllowedPaths: lambda r: (
        f"redirect target outside the project/allowed prefixes: {r.target!r}"
    ),
    ProgramNotAllowListed: lambda r: f"no allowedCommands entry vouches for: {r.program}",
    SubstitutedCommandNotAllowListed: lambda r: (
        f"a command-substituted program is not itself allow-listed: {r.program}"
    ),
    ParserCouldNotInterpretInvocation: lambda r: (
        f"{r.program}: the matched entry's parser could not interpret this invocation"
    ),
    DisallowedVariableReferenced: lambda r: (
        f"{r.program}: entry does not declare variable {r.variable!r}"
    ),
    ArgumentPathOutsideAllowedPaths: lambda r: (
        f"{r.program}: argument path outside the project/allowed prefixes: {r.path!r}"
    ),
    UnknowablePathArgument: lambda r: (
        f"{r.program}: an argument whose value cannot be known at analysis time occupies a "
        "path operand - substitute the real value first, or choose a different program that "
        "genuinely takes no path operands"
    ),
    FilterRejected: lambda r: f"{r.program}: a {r.filter_type} filter rejected this invocation",
    NotEscalatedByAnUnrelatedBypassWrapper: lambda r: (
        "bypass-policy appears on this line but does not wrap this command - wrap it "
        "explicitly to escalate it"
    ),
    AddAllowPolicyGrammarViolation: lambda r: (
        "wrong use of add-allow-policy. Correct use: "
        f"{ADD_ALLOW_POLICY_CANONICAL_FORM}. "
        f"{_ADD_ALLOW_POLICY_VIOLATION_EXPLANATIONS.get(r.violation, f'malformed invocation ({r.violation})')}"
    ),
}


def render(reasons):
    """One short paragraph naming every reason, primary (pass-order) first,
    ending with the unconditional equivalence-search pointer. Empty for an
    empty/None reason list - there is nothing to render for `allow`."""
    if not reasons:
        return ""
    clauses = [_clause_for(reason) for reason in reasons]
    return "; ".join(clauses) + f" ({EQUIVALENCE_POINTER})"


def _clause_for(reason):
    builder = _CLAUSE_BUILDERS.get(type(reason))
    if builder is None:
        return repr(reason)
    return builder(reason)
