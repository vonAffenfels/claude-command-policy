"""The two named escalation paths out of an ordinary deny, plus the one
guard neither can lift.

Both are RESULT TRANSFORMERS applied OUTSIDE the pass pipeline (Config's own
decision_for wires them in after computing the ordinary decision) - the
pipeline itself never learns either wrapper exists, so leaf 20260914-213652's
Policy protocol needs no change to accommodate them (see the improvement's
Interface section).

`bypass-policy <cmd>` recognizes ONLY the "sole invoked program" shape
(`Statement.as_sole_invoked_program()`, leaf 20260914-213321) - a command
merely SHARING the line with it (`bypass-policy true && rm -rf /`) is not
wrapped and faces normal analysis, which is exactly what stops
`bypass-policy` from laundering a chained command. Recognizing it this way,
rather than a literal `startswith` prefix check, is the anti-smuggling rule
(see the improvement's Design Decisions).

Once recognized, TWO independent things are combined:
  - the SHELL-LEVEL reasons the wrapper's own invocation already carries
    (its own redirects, and anything a raw-text scan finds - SensitivePaths,
    SensitiveVariables, CommandSubstitution) - these are true regardless of
    which program ends up running, because the calling shell resolves them
    before the wrapped program (or its child) ever starts, so the wrapper
    cannot vouch for them. The near-miss reason ABOUT the wrapper program
    itself ("bypass-policy" is never allow-listed) is filtered out - it says
    nothing about whether the ESCAPE HATCH should fire.
  - the WRAPPED command's own decision, from re-entering the ordinary
    pipeline on everything after the wrapper (its arguments only - a
    redirect belongs to the wrapper's own invocation, not to what it wraps).

If the union of both is empty, the command needed no escalation at all and
is simply allowed. Otherwise: a blocked command, a sensitive path, or a
redirect landing outside the project/allowed prefixes forces `ask` - these
are the ones bypass MUST NOT silently launder around (the "never waived, but
escalated" rule for the shell-performed-redirect veto, and the parallel rule
for blocked/sensitive). Every other objection becomes `passthrough` - the
engine states no opinion and whatever governs the call outside this hook
decides.

`add-allow-policy --scope user|project --intent "<why>" "<command>"` is the
ONE accepted grammar (reopened 2026-09-17, operator decision) - it always
forces `ask` when matched, carrying a JSON diff of the exact entry it would
append plus the stated intent - approving the dialog IS the durable config
write. `--intent` IS now required by the grammar itself, overriding this
leaf's own earlier reading (see Implementation Notes) that located the
requirement only on the write side (`lib/add_allow_write.py`); that write-side
check stays too, as defence in depth rather than a replacement.

Every OTHER shape whose command word is `add-allow-policy` - anywhere the
outer shell has touched the invocation (a redirect on it, a pipeline, a
&&/||/; list, backgrounding, or command substitution anywhere in it), a
missing/repeated `--scope`, an invalid `--scope` value, a missing `--intent`,
or zero/more-than-one command arguments - DENIES with an
`AddAllowPolicyGrammarViolation` Reason, rendered by the single renderer
(reason_renderer.py) like every other reason, never a hand-built string here.
Quoting is semantic, not cosmetic: an unquoted `add-allow-policy --scope user
--intent "x" echo something > somewhere` parses as add-allow-policy with args
`[echo, something]` and a redirect the OUTER shell performs against
add-allow-policy's own stdout - the policy persisted would be "echo
something", not what the caller meant. Quoting the whole command
(`"echo something > somewhere"`) makes it ONE argument, which is what the
grammar exists to guarantee.

Flag ORDER itself is not fixed - only the flag/positional SHAPE is (exactly
one `--scope`, exactly one `--intent`, exactly one remaining command
argument) - see this leaf's Design Decisions, 'Whether the strict
add-allow-policy grammar fixes flag ORDER or only flag/positional shape', for
why (an unattended judgment call, recorded there for review).
"""

from __future__ import annotations

import json

from permission_decision import PermissionDecision
from proposal_validation import parse_entry, proposal_problems
from reason import (
    NEAR_MISS_REASON_TYPES,
    AddAllowPolicyEntryChangesNothing,
    AddAllowPolicyExampleRejected,
    AddAllowPolicyGrammarViolation,
    AddAllowPolicyProposalInvalid,
    BlockedCommandInvoked,
    NotEscalatedByAnUnrelatedBypassWrapper,
    RedirectOutsideAllowedPaths,
    SensitivePathReferenced,
)
from reason_renderer import render, render_clauses
from statement import Command
from workspace import Workspace

BYPASS_WRAPPER_PROGRAM = "bypass-policy"
ADD_ALLOW_POLICY_PROGRAM = "add-allow-policy"
_VALID_ADD_ALLOW_SCOPES = ("user", "project")

_FORCES_ASK_REASON_TYPES = (BlockedCommandInvoked, SensitivePathReferenced, RedirectOutsideAllowedPaths)

PASSTHROUGH_REASON = (
    f"Command wrapped in {BYPASS_WRAPPER_PROGRAM} - analysis skipped by design. This hands "
    "the decision to whatever governs the call outside this hook: it MAY show Claude Code's "
    "own permission dialog, but under a permissive settings.json rule or an accepting "
    "permission mode it can auto-approve with no human ever seeing it - it is NOT a "
    "guarantee of human review."
)


def bypass_transform(statement, ordinary_decision, decide_wrapped_text, command_text=None):
    """None when `statement` is not exactly `bypass-policy` and nothing
    else - the caller should use `ordinary_decision` unmodified. Otherwise
    the transformed PermissionDecision (allow/ask/passthrough - this
    transformer never itself produces `deny`, per the escalation's whole
    purpose).

    The wrapped command is re-analysed from its own SOURCE TEXT inside
    `command_text` (what the shell will hand `execvp`), so a quoted `;`/`>`
    stays one argument and `$X` stays unknowable. Without `command_text` the
    arguments' literal texts are joined instead - quoting is lost.
    """
    if statement.as_sole_invoked_program() != BYPASS_WRAPPER_PROGRAM:
        return None

    wrapped_text = _wrapped_source_text(statement, command_text)
    inner_decision = decide_wrapped_text(wrapped_text) if wrapped_text else PermissionDecision.allow()

    outer_shell_reasons = tuple(
        reason for reason in (ordinary_decision.reason or ()) if not isinstance(reason, NEAR_MISS_REASON_TYPES)
    )
    inner_reasons = () if inner_decision.is_allow else (inner_decision.reason or ())
    reasons = outer_shell_reasons + inner_reasons

    if not reasons:
        return PermissionDecision.allow()

    forcing = [reason for reason in reasons if isinstance(reason, _FORCES_ASK_REASON_TYPES)]
    if forcing:
        return PermissionDecision.ask(
            f"{BYPASS_WRAPPER_PROGRAM} cannot escalate this: {render(forcing)} This is never "
            "waived by the wrapper - it surfaces to you rather than dead-ending as a denial."
        )
    return PermissionDecision.passthrough(PASSTHROUGH_REASON)


def _wrapped_source_text(statement, command_text):
    if command_text is not None:
        source_text = statement.arguments_source_text(command_text)
        if source_text is not None:
            return source_text
    return " ".join(argument.text for argument in statement.arguments())


def bypass_chain_hint(statement, ordinary_decision):
    """None when irrelevant. Otherwise `ordinary_decision` augmented with a
    `NotEscalatedByAnUnrelatedBypassWrapper` Reason: `bypass-policy` appears
    SOMEWHERE on this line (so a reader might expect it to have escalated
    this) but does not wrap the objecting command (`statement` is not
    exactly the wrapper - `bypass_transform` owns that case instead). The
    carve-out this documents: a blocked command merely sharing a line with
    the wrapper does not escalate, only what the wrapper actually invokes
    does - `bypass-policy true && rm -rf /` must not upgrade the unwrapped
    `rm` from `deny` to `ask`. User agency is still preserved: the hint
    names the fix (wrap the command you actually mean to escalate).
    """
    if ordinary_decision.is_allow:
        return None
    if statement.as_sole_invoked_program() == BYPASS_WRAPPER_PROGRAM:
        return None  # it IS the wrapper - bypass_transform's case, not this one
    if not _mentions_program(statement, BYPASS_WRAPPER_PROGRAM):
        return None

    forcing = any(isinstance(reason, _FORCES_ASK_REASON_TYPES) for reason in (ordinary_decision.reason or ()))
    if not forcing:
        return None

    return PermissionDecision.deny((ordinary_decision.reason or ()) + (NotEscalatedByAnUnrelatedBypassWrapper(),))


def _mentions_program(statement, program):
    if isinstance(statement, Command) and statement.command_word == program:
        return True
    return any(_mentions_program(child, program) for child in statement.sub_statements())


def add_allow_policy_transform(
    statement,
    path_resolution=None,
    project_config_file=None,
    decide_example=None,
    decide_example_with_entry=None,
):
    """None when `add-allow-policy` is not invoked anywhere on this line.
    Otherwise `ask` for the one accepted grammar with a well-formed entry,
    `deny` (with an `AddAllowPolicyGrammarViolation` Reason) for any other
    shape - see this module's docstring for the grammar and its quoting
    rationale - or `deny` (with an `AddAllowPolicyProposalInvalid` Reason per
    problem) when the grammar is right but the entry itself has a static or
    described problem (improvement 20260925-120037): a human approving the
    dialog should never be asked to bless an entry that would never vouch
    for anything. `path_resolution` and `project_config_file` (the file a
    project-scope diff names) default to this session's `Workspace`,
    mirroring every other caller-optional context parameter in this package.

    Every `--example` must be proven: `decide_example(example)` is the
    session's effective config alone, `decide_example_with_entry(entry,
    example)` that config plus the proposed entry. Each example must come out
    `allow` WITH the entry, and at least one must NOT be allowed without it
    (otherwise the entry adds nothing). The transform loads no config itself -
    it receives these callables (None skips the check, for pure grammar
    tests).
    """
    if not _mentions_program(statement, ADD_ALLOW_POLICY_PROGRAM):
        return None

    if statement.as_sole_invoked_program() != ADD_ALLOW_POLICY_PROGRAM:
        return _malformed_add_allow_policy("shell_touched")
    if statement.redirects:
        return _malformed_add_allow_policy("redirect_on_invocation")

    violation, parsed = _classify_add_allow_invocation(statement.arguments())
    if violation is not None:
        return _malformed_add_allow_policy(violation)

    scope, intent, examples, entry_text = parsed

    problems = proposal_problems(entry_text, scope, path_resolution or Workspace.of_this_session().path_resolution())
    if problems:
        return PermissionDecision.deny(tuple(AddAllowPolicyProposalInvalid(problem) for problem in problems))

    if decide_example is not None and decide_example_with_entry is not None:
        example_objections = example_objections_for(
            parse_entry(entry_text), examples, decide_example, decide_example_with_entry
        )
        if example_objections:
            return PermissionDecision.deny(example_objections)

    diff = _entry_diff(_displayed_config_file(scope, project_config_file), entry_text)
    reason = (
        f"PROPOSED command-policy config change ({scope} scope). Diff: {diff}. "
        f"Stated intent: {intent}. Examples this entry is proven to allow: "
        f"{', '.join(repr(example) for example in examples)}. "
        "Approving this runs the write - nothing else changes."
    )
    return PermissionDecision.ask(reason)


def example_objections_for(entry, examples, decide_example, decide_example_with_entry):
    """Reasons an add-allow-policy proposal fails its own examples; empty
    when every example is allowed with `entry` and at least one is not
    allowed without it. Shared by the ask path and the write side."""
    rejected = tuple(
        AddAllowPolicyExampleRejected(example, _decision_text(decision))
        for example in examples
        for decision in (decide_example_with_entry(entry, example),)
        if not decision.is_allow
    )
    if rejected:
        return rejected
    if all(decide_example(example).is_allow for example in examples):
        return (AddAllowPolicyEntryChangesNothing(),)
    return ()


def _decision_text(decision):
    reason = decision.reason
    if isinstance(reason, tuple):
        return render_clauses(reason)
    return str(reason) if reason else f"decided {decision.decision}"


def _malformed_add_allow_policy(violation):
    return PermissionDecision.deny((AddAllowPolicyGrammarViolation(violation),))


def _classify_add_allow_invocation(arguments):
    """Scans `add-allow-policy`'s own arguments (the wrapper's invocation is
    already confirmed shell-untouched by the caller) against the strict
    grammar. Returns `(violation_code, None)` for the first violation found,
    or `(None, (scope, intent, examples, entry_text))` once exactly one valid
    `--scope`, one `--intent`, at least one `--example` and one remaining
    entry argument are all present.

    Flag ORDER is deliberately not checked here - `--scope`/`--intent` may
    appear in either order or interleaved with the command argument (see this
    module's docstring and the Design Decision it points to).

    The entry (command) argument is ALSO rejected as `shell_touched` when it
    references any variable (`Argument.referenced_variables`): a bare
    `ParamExp` (`$HOME`/`${HOME}`) is invisible to the caller's own
    `as_sole_invoked_program()` shell_touched gate - that gate only sees
    `CmdSubst`/`ProcSubst`, which are Statement subtypes reachable via
    `sub_statements()`, where a `ParamExp` is not - so this is the one place
    left that can catch it. Uniform across quote style ($HOME / "$HOME" /
    ${HOME}), since `referenced_variables` already recurses through
    DblQuoted the same way the now-corrected `.text` does.
    """
    scope = intent = entry_text = None
    entry_argument = None
    examples = []
    scope_count = intent_count = command_arg_count = 0
    tokens = list(arguments)
    index = 0
    while index < len(tokens):
        text = tokens[index].text
        if text == "--scope":
            if index + 1 >= len(tokens):
                return "missing_scope", None
            scope_count += 1
            scope = tokens[index + 1].text
            index += 2
            continue
        if text == "--intent":
            if index + 1 >= len(tokens):
                return "missing_intent", None
            intent_count += 1
            intent = tokens[index + 1].text
            index += 2
            continue
        if text == "--example":
            if index + 1 >= len(tokens):
                return "missing_example", None
            if tokens[index + 1].referenced_variables:
                return "shell_touched", None
            examples.append(tokens[index + 1].text)
            index += 2
            continue
        command_arg_count += 1
        entry_text = text
        entry_argument = tokens[index]
        index += 1

    if scope_count == 0:
        return "missing_scope", None
    if scope_count > 1:
        return "duplicate_scope", None
    if scope not in _VALID_ADD_ALLOW_SCOPES:
        return "invalid_scope_value", None
    if intent_count == 0:
        return "missing_intent", None
    if not examples:
        return "missing_example", None
    if command_arg_count == 0:
        return "no_command_argument", None
    if command_arg_count > 1:
        return "multiple_command_arguments", None
    if entry_argument.referenced_variables:
        return "shell_touched", None
    return None, (scope, intent, tuple(examples), entry_text)


def _displayed_config_file(scope, project_config_file):
    if scope == "user":
        return "~/.claude/command-policy.json"
    return str(project_config_file or Workspace.of_this_session().project_config_file())


def _entry_diff(config_file, entry_text):
    stripped = entry_text.strip()
    if stripped.startswith("{"):
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            entry = stripped
    else:
        entry = stripped

    return json.dumps({"file": config_file, "add": {"allowedCommands": [entry]}})
