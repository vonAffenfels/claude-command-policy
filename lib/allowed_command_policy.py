"""AllowedCommandPolicy: Pass 5 (last), the deny-by-default backbone.

Objects (matches()) when SOME invocation in the statement (walking every
sub-statement, so a multi-statement command like `cat a; cat b` checks each
independently) has NO `allowedCommands` entry vouching for it. CASE A
(program never listed) and CASE B (listed but this invocation's own
vouching fails) collapse into this single objection - see the improvement's
"What this leaf must decide".

Vouching for one entry, ALL of which must hold:
  - the entry's own program name equals the invocation's command word, OR -
    for a `programGlob` entry (improvement 20260915-011123's cross-leaf
    hand-back, completed here since this leaf's own dependency chain landed
    after this Pass shipped) - the invocation's command word matches the
    entry's `{cache_root}/{marketplace}/{plugin}/*/{path}` fnmatch pattern,
    mirroring shfmt-permissions' `_build_plugin_program_pattern`/
    `_check_command_allowed`. A `programGlob` with a construction-time
    PROBLEM (see allowed_command.py) never matches any invocation - the same
    "never matches, reports its problem" rule every entry defect gets;
  - `onlyTheseVariables` vouching: every variable this invocation references
    is declared by the entry (deny-by-default, not a narrowing);
  - `hasNoPathParameters` (default False) gates only the entry's own
    argument-path containment check - independent of redirect validation
    (a separate Pass) and of a `paths` filter (unconditional either way).
    Containment asks two questions, not one: every path the parser NAMED
    must sit inside the boundary, and no argument whose value cannot be
    known at analysis time may occupy a slot the parser treats as a path
    operand (`_an_unknowable_argument_occupies_a_path_operand`). The second
    is what stops one allow-listed string-producing program from handing a
    path-taking entry an arbitrary absolute path, and it is earned back
    only by an honest `hasNoPathParameters` or by a parser that classifies
    the slot as something other than a path;
  - every filter on the entry passes, AND-ed, including the per-argument
    knowability rules covering BOTH variables and substitutions uniformly
    (`argument_knowability.py`): a `block` filter can never prove absence
    next to unknowable content; a `required` index filter is defeated only
    for positions at-or-after the first word-count-changing argument; every
    other `required` filter is proven against the knowable arguments only.
    A filter the entry's own construction could not build at all (an
    unrecognised type, an uncompilable pattern, or a capability its parser
    lacks - see allowed_command.py) is an `InvalidFilter` and always fails,
    the same as any other rejecting filter;
  - when `commandSubstitutionResponse == "via-allowed-commands"`: every
    CmdSubst/ProcSubst this invocation's own statement carries (arguments
    or redirects) must itself recursively decide `allow` through the same
    pipeline;
  - a `nestedCommand` filter (this entry's own wrapper-propagation filter,
    see nested_command_filter.py) requires every sub-command the parser
    published to itself recursively decide `allow`.

WHY NO ENTRY VOUCHED, PER COMMAND, PER ENTRY (leaf 20260915-010959): the old
engine's `_check_call_expr_against_entries` looped over every matching entry
but kept only a single overwritten `rejecting_filter_def`, so its emitted
text named whichever entry happened to be visited LAST - and an entry that
dropped out for a disallowed variable, a parser that could not interpret the
invocation, or an out-of-bounds argument path contributed NOTHING at all
(bare `continue`). `_reasons_for_command` below reports the whole candidate
set instead: one Reason per entry that matched the program but did not
vouch, or a single `ProgramNotAllowListed` when no entry names the program
at all.

Filter/parser CONSTRUCTION happens once, at `AllowedCommand.from_entry` time
(improvement 20260925-120037) - this Pass only EVALUATES the already-built
`entry.parser`/`entry.built_filters` against a command. No `ConfigError` is
raised here or anywhere downstream of it any more: a config defect this
package cannot make sense of becomes a construction-time PROBLEM
(`AllowedCommand.problems()`, surfaced through `Config.warnings()`), and the
defective entry simply never vouches - the same "fails closed, never raises"
posture an uncompilable filter pattern already had.
"""

from __future__ import annotations

import fnmatch
import os

from action import Action  # noqa: F401 - re-exported for parser-dispatch callers
from argument_knowability import ArgumentKnowability, IndexScheme
from nested_command_filter import NestedCommandFilter
from pass_ import Pass
from paths_filter import PathsFilter
from permission_decision import PermissionDecision
from policy import Policy
from reason import (
    ArgumentPathOutsideAllowedPaths,
    DisallowedVariableReferenced,
    FilterRejected,
    ParserCouldNotInterpretInvocation,
    ProgramNotAllowListed,
    SubstitutedCommandNotAllowListed,
    UnknowablePathArgument,
)
from statement import CmdSubst, Command, ProcSubst

_INDEX_MATCHER_TYPES = frozenset({"argumentAtIndex", "positionalArgAtIndex"})

# Injected by the engine into a re-parse, never read from an invocation - see
# `_an_unknowable_argument_occupies_a_path_operand`.
_UNKNOWABLE_OPERAND_MARKER = "__command_policy_unknowable_operand__"


class AllowedCommandPolicy(Policy):
    pass_ = Pass.ALLOWED_COMMAND

    def __init__(
        self,
        allowed_commands,
        path_resolution,
        allowed_prefixes,
        recurse_via_allowed_commands,
        evaluate_nested_text,
        depth,
        default_max_depth,
    ):
        super().__init__()
        self._allowed_commands = tuple(allowed_commands)
        self._path_resolution = path_resolution
        self._allowed_prefixes = tuple(allowed_prefixes)
        self._recurse_via_allowed_commands = recurse_via_allowed_commands
        self._evaluate_nested_text = evaluate_nested_text
        self._depth = depth
        self._default_max_depth = default_max_depth

    # -- Policy protocol ----------------------------------------------------

    def matches(self):
        return bool(self._all_reasons())

    def decision(self):
        return PermissionDecision.deny(self._all_reasons())

    # -- vouching -------------------------------------------------------

    def _all_reasons(self):
        return tuple(
            reason for command in _all_commands(self.statement) for reason in self._reasons_for_command(command)
        )

    def _reasons_for_command(self, command):
        """Every Reason explaining why NO entry currently vouches for
        `command` - empty when some entry does. `<unresolved>` covers a
        command word that is not a single plain literal (`$CMD`, `foo$X`),
        which can never match any entry's `program` by definition."""
        program = command.command_word or "<unresolved>"

        if self._recurse_via_allowed_commands and not self._substitution_recursion_passes(command):
            return (SubstitutedCommandNotAllowListed(program),)

        candidates = [entry for entry in self._allowed_commands if _entry_matches_program(entry, command.command_word)]
        if not candidates:
            return (ProgramNotAllowListed(program),)

        reasons = []
        for entry in candidates:
            reason = self._entry_rejection_reason(entry, command)
            if reason is None:
                return ()  # this entry vouches; the command is fully approved
            reasons.append(reason)
        return tuple(reasons)

    def _entry_rejection_reason(self, entry, command):
        """None means the entry vouches; otherwise the single Reason
        explaining why THIS entry does not - never a bool, so the caller
        never has to re-derive which of several checks actually failed."""
        arguments = command.arguments()
        argument_texts = [argument.text for argument in arguments]

        parsed = self._parsed_result_for(entry.parser, argument_texts)
        if parsed is None:
            return ParserCouldNotInterpretInvocation(entry.program_label)

        disallowed_variable = self._first_disallowed_variable(entry, arguments)
        if disallowed_variable is not None:
            return DisallowedVariableReferenced(entry.program_label, disallowed_variable)

        knowability = ArgumentKnowability.of(arguments)

        if not entry.has_no_path_parameters:
            offending_path = self._first_path_outside_allowed_prefixes(parsed)
            if offending_path is not None:
                return ArgumentPathOutsideAllowedPaths(entry.program_label, offending_path)
            if self._an_unknowable_argument_occupies_a_path_operand(entry.parser, knowability, argument_texts):
                return UnknowablePathArgument(entry.program_label)

        for definition, built_filter in zip(entry.filters, entry.built_filters):
            if not self._filter_passes(definition, built_filter, entry.parser, parsed, knowability):
                return FilterRejected(entry.program_label, definition.get("type", ""))

        return None

    def _first_disallowed_variable(self, entry, arguments):
        referenced = set()
        for argument in arguments:
            referenced |= argument.referenced_variables
        disallowed = sorted(referenced - set(entry.only_these_variables))
        return disallowed[0] if disallowed else None

    def _first_path_outside_allowed_prefixes(self, parsed):
        """The KNOWABLE half of argument-path containment: a path this
        entry's parser actually named, checked against the boundary. The
        unknowable half is a different question with a different answer -
        see `_an_unknowable_argument_occupies_a_path_operand`."""
        for path in parsed.paths_for_validation:
            if not path or not self._path_resolution.is_contained(path, self._allowed_prefixes):
                return path
        return None

    def _an_unknowable_argument_occupies_a_path_operand(self, parser, knowability, argument_texts):
        """Whether an argument whose value cannot be known at analysis time
        sits in a slot THIS entry's own parser treats as a path operand.

        Asked by re-parsing with a marker appended to every unknowable
        argument (`ArgumentKnowability.texts_with_unknowable_marked`) and
        seeing whether any resulting path carries it. That is the only sound
        way to correlate an argument to a path: `paths_for_validation` holds
        resolved absolute paths, so matching a fragment's own text against
        them proves nothing (the fragment is frequently empty, and an empty
        text resolves to the cwd - indistinguishable from a real argument
        naming `.`). The marker is injected by this engine, never read from
        the invocation, so it cannot collide with user content.

        This is what makes a config entry EARN a substitution instead of
        being handed one, and there are exactly three outcomes
        (improvement-20260919-112214, second fix round):
          1. `hasNoPathParameters` - a factual claim that the program takes
             no path operands at all. Checked by the caller, which skips
             this question entirely. The flag is a claim, never a waiver:
             asserting it falsely is wrong in the same way a wrong parser is.
          2. A parser that knows the grammar well enough to classify the
             slot as NOT a path (a pattern, a mode, a message) - the probe
             then finds no marker-bearing path and the entry vouches. This
             is why `grep $(echo pat) README.md` and `chmod $(echo 755)
             bin/x` are allowed while `cat $(echo README.md)` is not: the
             difference is parser quality, which is now the explicit
             currency rather than an accident of which entry has a parser.
          3. Neither - the DefaultParser rules nothing out, so the slot is a
             path operand and the invocation denies. The caller restructures
             (`project-root` is itself allow-listed, so read the real path
             and pass it as a literal - both halves auto-approved and both
             statically checkable) or escalates via `bypass-policy`.

        A probe the parser cannot interpret fails closed: an unanswerable
        question about a security boundary is not an exemption.

        Costs one extra parse, and for a `provided`/`command` entry that is a
        second subprocess. Deliberate, and NOT in tension with the
        'Unknowable content under an external parser' decision, which is
        about re-evaluating FILTERS: that one declines a re-parse because a
        filter can fail closed with no loss, while here declining would
        deny every external-parser entry any substitution at all and so
        remove outcome 2 - the one the operator explicitly wants."""
        if not knowability.defeats_absence_proof():
            return False

        probed = self._parsed_result_for(
            parser, knowability.texts_with_unknowable_marked(_UNKNOWABLE_OPERAND_MARKER)
        )
        if probed is None:
            return True
        return any(_UNKNOWABLE_OPERAND_MARKER in path for path in probed.paths_for_validation)

    def _substitution_recursion_passes(self, command):
        """`commandSubstitutionResponse == "via-allowed-commands"`'s own
        recursion: every CmdSubst/ProcSubst this invocation carries must
        itself name a program present in allowedCommands.

        Deliberately a bare PROGRAM-MEMBERSHIP check, not a full recursive
        `decision_for` re-running that program's own filters: the inner
        substitution's arguments are not this invocation's own arguments, so
        re-applying THIS entry's filters to them would wrongly entangle two
        independent questions ("is this outer invocation's own content
        acceptable" and "is the substituted program itself allow-listed at
        all") - proven by `test_command_substitution_does_not_defeat_a_
        filter_requiring_present_content` and `test_substitution_after_an_
        indexed_argument_leaves_the_index_provable`, both of which need the
        inner substitution ("echo safe" / "echo tail") to NOT be re-checked
        against the very filter the outer entry is applying to itself.
        `as_sole_invoked_program()` already returns None the instant the
        inner statement itself contains a nested CmdSubst/ProcSubst (its own
        `sub_statements()` is then non-empty), so a further-nested
        substitution fails closed by construction well before any depth
        counter would matter. The explicit `depth`/`default_max_depth`
        check below is threaded through anyway (never hidden state), so
        this recursion source is depth-guarded on the same explicit terms
        as the nested-command filter's - see
        test_allowed_command_policy.py's own depth-guard case.
        """
        if self._depth >= self._default_max_depth:
            return not any(isinstance(child, (CmdSubst, ProcSubst)) for child in command.sub_statements())

        for child in command.sub_statements():
            if not isinstance(child, (CmdSubst, ProcSubst)):
                continue
            inner = child.wrapped_statement
            if inner is None:
                return False
            program = inner.as_sole_invoked_program()
            if program is None:
                return False
            if not any(entry.program == program for entry in self._allowed_commands):
                return False
        return True

    # -- parsing / filter evaluation --------------------------------------

    def _parsed_result_for(self, parser, argument_texts):
        if hasattr(parser, "parse"):
            return parser.parse(argument_texts)
        return self._parsed_result_via_external(parser, argument_texts)

    def _parsed_result_via_external(self, parser, argument_texts):
        # Constructed lazily to avoid importing subprocess-touching code
        # into every AllowedCommandPolicy user (e.g. unit tests that never
        # exercise a command/provided parser).
        from external_parser_factory import ExternalParserFactory

        factory = ExternalParserFactory()
        raw_output = factory.raw_output_for(parser, argument_texts)
        if raw_output is None:
            return None
        return parser.interpret(raw_output)

    def _filter_passes(self, definition, built_filter, parser, parsed, knowability):
        """Consumes `knowability` per the improvement's asymmetric rule: a
        `block` filter can never prove absence next to unknowable content
        (any argument, dash-prefixed included); a `required` INDEX filter
        (argumentAtIndex/positionalArgAtIndex) is defeated only for a target
        at-or-after the first word-count-changing (non-word-safe) argument,
        using the SAME dash heuristic as before to decide option-vs-
        positional counting; every other `required` filter is proven against
        the KNOWABLE arguments only - a second, PURE re-parse - except for an
        external-parser-backed entry, which gets no re-parse attempt at all
        (a second subprocess invocation) and simply fails closed.

        `built_filter` is already constructed (`AllowedCommand.from_entry`) -
        a `paths`/`nestedCommand` filter is evaluated through its own,
        already-resolved value object; every other kind (including an
        `InvalidFilter` standing in for a defect the entry's own
        construction could not build) is a `Filter{Matcher, Action}` reused
        across both an ordinary and a knowable-only re-parse."""
        if isinstance(built_filter, PathsFilter):
            return built_filter.matches(parsed)

        if isinstance(built_filter, NestedCommandFilter):
            if knowability.defeats_absence_proof():
                return False
            return built_filter.matches(parsed, self._evaluate_nested_text, self._depth, self._default_max_depth)

        if definition.get("action", "block") == "block":
            if knowability.defeats_absence_proof():
                return False
            return built_filter.matches(parsed)

        return self._required_filter_passes(definition, built_filter, parser, parsed, knowability)

    def _required_filter_passes(self, definition, built_filter, parser, parsed, knowability):
        filter_type = definition.get("type")

        if filter_type in _INDEX_MATCHER_TYPES:
            scheme = IndexScheme.COMBINED if filter_type == "argumentAtIndex" else IndexScheme.POSITIONAL
            shift_position = knowability.first_shifting_position(scheme)
            if shift_position is not None and definition.get("index", 0) >= shift_position:
                return False
            return built_filter.matches(parsed)

        if not knowability.defeats_absence_proof():
            return built_filter.matches(parsed)

        if not hasattr(parser, "parse"):
            return False  # external parser: no knowable-only re-parse attempted

        knowable_parsed = parser.parse(knowability.knowable_texts())
        return built_filter.matches(knowable_parsed)


def _entry_matches_program(entry, command_word):
    """`command_word` is `None` for an unresolvable invocation (a variable-
    invoked program, `Command.command_word`'s own contract) - it can never
    match ANY entry, `programGlob` included. A `programGlob` entry with a
    construction-time PROBLEM (`has_valid_program_glob` False - a missing
    field, a `..`/leading-`/` escape, or `program`+`programGlob` both set)
    never matches any invocation either - the same "never matches, reports
    its problem" rule every entry defect gets (see allowed_command.py)."""
    if command_word is None:
        return False
    if entry.program_glob is not None:
        if not entry.has_valid_program_glob:
            return False
        pattern = _program_glob_pattern(entry.program_glob)
        return fnmatch.fnmatch(command_word, pattern)
    return entry.program == command_word


def _program_glob_pattern(program_glob):
    """`{cache_root}/{marketplace}/{plugin}/*/{path}` - the version segment
    between `{plugin}` and `{path}` is wildcarded so the entry keeps working
    across a plugin upgrade. Mirrors shfmt-permissions'
    `_build_plugin_program_pattern`; only ever called for a
    `has_valid_program_glob` entry, so every field is trusted present."""
    cache_root = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or os.path.expanduser("~/.claude/plugins/cache")
    return os.path.join(cache_root, program_glob["marketplace"], program_glob["plugin"], "*", program_glob["path"])


def _all_commands(statement):
    """Every Command node needing its OWN independent vouching - walks every
    sub-statement (so `cat a; cat b` checks both), but does NOT descend into
    a CmdSubst/ProcSubst's own wrapped command: substitution content is not
    an ordinary sibling invocation that always runs, it is conditional
    content the `_substitution_recursion_passes` bare-membership check (or
    Pass 2 in deny mode) handles on its own terms. Walking into it here too
    would double-vouch it as though it were a ";"-separated statement,
    wrongly requiring the SAME entry's filters (written for the OUTER
    invocation's own arguments) to also hold for the substitution's
    unrelated inner arguments.
    """
    commands = []
    if isinstance(statement, Command):
        commands.append(statement)
    for child in statement.sub_statements():
        if isinstance(child, (CmdSubst, ProcSubst)):
            continue
        commands.extend(_all_commands(child))
    return commands
