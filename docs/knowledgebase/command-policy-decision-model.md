# Command-Policy Decision Model

This repository decides whether a Bash command is auto-approved, denied, or handed to the human. This article covers the
**decision model** — the outcome vocabulary and the rules governing what the engine may and may not conclude from a
command's text. It does not inventory the implementation; read the code for that.

## Two Plugins, One Job

`command-policy` (this repository) and `shfmt-permissions` (still in the `vonaffenfels-dev-tools` monorepo, at
`packages/shfmt-permissions/`) both exist on purpose. **`shfmt-permissions` is deprecated in favor of `command-policy`**
— its `plugin.json`/`marketplace.json` description say so — but the cutover is additive, not forced: `shfmt-permissions`
stays fully installed and fully functional (no functional code changed, no hooks flipped for an existing install) until
a user migrates on their own via `command-policy:migrate-config`. Do not delete, gut, or behaviourally change anything
in that package on the strength of the deprecation label alone.

- **command-policy is assembled behind a settled public entrypoint**, `Config.from_dict(cfg).decision_for(command)` in
  `lib/config.py`, plus its Read/Grep/Glob counterpart `Config.decision_for_path(tool_name, path)` — allowedPaths is its
  own decision domain (match -> `allow`, no match -> `passthrough`; it never denies, so a caller cannot lock themselves
  out of a path Claude Code's own permission rules would otherwise grant).

**Do not "fix" a divergence between the two by copying behaviour across.** The new engine deliberately makes decisions
the old one does not — see the outcome model below. A verbatim-copied config is not an equivalent config.

**This article describes the target design, not today's build state.** Which leaves have landed changes weekly; the
trunk improvement file is the only place that tracks it accurately. Check `Config`'s own methods and the `bin/`
entrypoints before assuming a piece described here is wired up — a stub raising `NotImplementedError` is a normal
intermediate state for this package, not a bug.

## The Outcome Vocabulary

**Deny is not prevention. Deny is routing.** This is the single most important thing to understand about this engine,
and the easiest to get backwards, because the word "deny" suggests a security control and this one is not.

There is exactly one privileged outcome — `allow` — and it is privileged because it is the only one that runs with no
human involved. Nothing else grants anything, and nothing else _stops_ anything either. The rest hand the decision
onward.

| Outcome         | What it actually says                                                                                                    | How it is reached                                                                                                                        |
| --------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **allow**       | Auto-approved; runs unseen. The only outcome that grants.                                                                | No objection survived any pass                                                                                                           |
| **deny + hint** | "Could not be auto-approved" — Claude should try another way                                                             | Anything not positively allowed                                                                                                          |
| **passthrough** | "No auto-approved route exists; the human decides"                                                                       | `bypass-policy`, for an ordinary (non-categorical) objection                                                                             |
| **ask**         | "This needs your attention" — either a durable config write, or a one-off escalation the wrapper cannot silently launder | `add-allow-policy` (always); `bypass-policy`, for a blocked command, a sensitive path, or a shell-performed redirect it cannot vouch for |

A denied command is not a blocked command. It is a command the caller is expected to attempt differently — using the
hint to find an auto-approved equivalent — or, if nothing auto-approved can achieve it, to escalate deliberately by name
through `bypass-policy`. The obligation that makes this work is on the caller: **run auto-approved commands whenever
possible, and escalate only when genuinely nothing else achieves the result.**

**The underlying goal this whole vocabulary serves, stated plainly:** every legitimate task is intended to be reachable
through some auto-approved shape, or SEQUENCE of shapes — not necessarily one single command. A denial is the routing
signal toward constructing that shape or sequence, not evidence that none exists. This is what makes strategies like
[command decomposition](#command-decomposition-recovering-from-an-unknowable-argument-denial) derivable rather than a
trick someone has to stumble onto: once the goal is stated, splitting a denied command into two auto-approved ones is
the obvious next move for the class of denial that motivates it, and so is whatever the next such strategy turns out to
be.

**Three things follow, each easy to get backwards:**

- **Denying more is not safer.** Narrowing `bypass-policy` removes the escalation route without adding protection,
  because bypass already routes to a human. A change that makes the engine refuse more, and gives the caller nowhere to
  go, has made the system worse rather than stricter.
- **The hint is load-bearing, not decoration.** It is the routing information the caller acts on. A deny whose hint
  names the wrong cause sends the caller down a route that cannot work — which is why pass ordering is specified in
  terms of _which reason surfaces_ when two objections both apply.
- **The defect class that matters is unintended AUTO-APPROVAL, not insufficient denial.** A filter that fails open is
  serious because the command then runs unseen. Every "fail closed" in this codebase means _decline to auto-approve_ —
  never _block_.

**Not-allowed collapses uniformly to deny+hint.** The config can express what IS allowed; it can no longer express
leniency. Four of the old engine's five decision knobs (`defaultDecision`, `sensitiveVariableResponse`,
`pathValidationResponse`, `filterRejectionResponse`) cease to exist rather than being renamed — there is nothing left to
configure once the not-allowed branch is a constant.

**The one surviving decision knob is `commandSubstitutionResponse`**, reduced to `{deny, via-allowed-commands}` with
`via-allowed-commands` the default. `deny` refuses any command containing a substitution outright;
`via-allowed-commands` continues evaluation, checking the inner command like any other invocation.

**The CASE A / CASE B distinction is abolished.** A program absent from `allowedCommands` entirely and a program that IS
allow-listed but whose invocation a filter rejected now produce the same outcome. Under the old engine these were two
different knobs that happened to share a default.

**One guard `bypass-policy` cannot lift: the shell-performed-redirect veto — never WAIVED, but ESCALATED rather than
denied.** A redirect is performed by the calling shell before the wrapped program (or its child) ever starts, so the
wrapper cannot legitimately vouch for it — the same is true of a blocked command or a sensitive path the wrapper's own
invocation carries. `bypass-policy` therefore forces `ask` for these three, rather than either `deny` (which would
dead-end an escalation the caller made explicitly by name, pointing at alternatives that by definition do not exist) or
`passthrough` (which discards the reason and, under a permissive `settings.json` or an accepting permission mode, can
auto-approve with no human ever seeing it — today's shipped `shfmt-permissions` behaviour, and the worst outcome). See
[The Reason List and Three Escalation Transformers](#the-reason-list-and-three-escalation-transformers) below for the
full mechanism.

## The Reason List and Three Escalation Transformers

A denial does not carry a single prose string. `PermissionDecision.reason` is a TUPLE of `Reason` value objects
(`lib/reason.py`), ordered primary-first by pass order. Each `Reason` is a small `@dataclass(frozen=True)` carrying
FACTS — which path, which program, which filter type — never prose; prose is rendered from those facts in exactly one
place, `reason_renderer.render(reasons)`, so wording can change without touching a Policy class.

**Every Reason subtype is classified by ORIGIN into one of two tuples** in `reason.py`:

- `CATEGORICAL_REASON_TYPES` — true regardless of which allowedCommands entry is in play: `SensitivePathReferenced`,
  `BlockedCommandInvoked`, `CommandSubstitutionPresent` (deny mode), `SensitiveVariableReferenced`,
  `RedirectOutsideAllowedPaths`.
- `NEAR_MISS_REASON_TYPES` — a specific allowedCommands entry's own vouching attempt failed: `ProgramNotAllowListed` (no
  entry names the program at all), `SubstitutedCommandNotAllowListed`, `ParserCouldNotInterpretInvocation`,
  `DisallowedVariableReferenced`, `ArgumentPathOutsideAllowedPaths`, `UnknowablePathArgument`, `FilterRejected`. The
  last two are deliberately distinct facts: one says a path WAS resolved and sits outside the boundary, the other that
  no path can be named at all because something unknowable occupies a path operand — different situations with different
  fixes, so they are not collapsed into one reason carrying a placeholder path.

**The list is flat and heterogeneous on purpose**: a single command can carry a categorical objection and a near-miss
objection at once (or two categorical objections — a blocked command AND a sensitive path — at once), and all of them
must be reported, not just the first by pass order. A twelfth Reason kind, `NotEscalatedByAnUnrelatedBypassWrapper`,
belongs to neither tuple: it is a ROUTING NOTE, never itself the cause of a denial (see `bypass_chain_hint` below).

**The decision is DERIVED from the list, never stored beside it**: `deny` when the concatenated reason list from every
objecting pass is non-empty, `allow` when it is empty. This makes a decision/reason disagreement unrepresentable.
**Every entry that matched a command's program but did not vouch for it contributes its own Reason** — this is the
direct fix for a defect in the old engine, which kept only a single overwritten "rejecting filter" per program, so its
emitted text named whichever entry happened to be visited last while entries that dropped out for a disallowed variable,
an uninterpretable invocation, or an out-of-bounds path contributed nothing at all.

**Every non-empty reason list ends with an unconditional pointer** to `command-policy:find-auto-allowed-command`
(`reason_renderer.EQUIVALENCE_POINTER`), an AGENT (dispatched via the Task tool, not a skill loaded into the calling
conversation) that reasons over the live rendered config already injected into its own context at dispatch — the
`SubagentStart` hook puts it there — and searches for a command that both achieves the caller's goal and is
auto-approved. It is unconditional — appended even to a pure near-miss — because a near-miss hint answers "how do I make
THIS command pass," a different question from "how do I accomplish the task within what is allowed": a program with a
forbidden `--json` flag might still be the same program without it, but no longer do what the caller needed it for.

**Three RESULT TRANSFORMERS, all in `escalation_policy.py`, are applied OUTSIDE the pass pipeline** — wired in by
`Config.decision_for`, in this order, after the ordinary pipeline runs; the pipeline itself never learns any of them
exists, and no Policy or `Pass` value references any of the three:

- **`bypass_transform`** recognizes `bypass-policy <cmd>` via `Statement.as_sole_invoked_program()` — the line consists
  of the wrapper and nothing else — never a `startswith` prefix check, which is what stops
  `bypass-policy true && rm -rf /` from laundering the chained `rm` through a single opt-in. It combines the wrapper's
  own shell-level objections (its own redirects; anything a raw-text scan of the whole line finds — sensitive
  paths/variables, command substitution) with the wrapped command's own decision, from re-entering the ordinary pipeline
  on everything after the wrapper. If nothing objects, the command is simply `allow`ed. Otherwise: a
  `BlockedCommandInvoked`, `SensitivePathReferenced`, or `RedirectOutsideAllowedPaths` reason forces `ask`; any other
  reason (an ordinary near-miss — the wrapped program merely isn't allow-listed, say) becomes `passthrough`.
- **`bypass_chain_hint`** runs when `bypass_transform` does NOT apply (the line is not exactly the wrapper) but
  `bypass-policy` appears somewhere else on it AND the ordinary decision already carries a forcing categorical reason —
  the carve-out for `bypass-policy true && rm -rf /`: the unwrapped `rm` still denies, but the reason list gains a
  trailing `NotEscalatedByAnUnrelatedBypassWrapper`, whose rendered clause names the fix ("wrap it explicitly to
  escalate it") rather than leaving a reader wondering why the wrapper on the line didn't help.
- **`add_allow_policy_transform`** recognizes `add-allow-policy`'s **strict grammar** — the ONE accepted shape is
  `add-allow-policy --scope <user|project> --intent "<why>" "<command>"`, and matching it forces `ask`, carrying a JSON
  diff of the exact entry it would append plus the stated intent — approving the dialog IS the write
  (`lib/add_allow_write.py`/`bin/add-allow-policy` perform it once approved). `--intent` is required by the GRAMMAR
  itself here (reopened 2026-09-17, operator decision superseding this leaf's own earlier reading) — the write-side
  script's own `--intent` check (`lib/add_allow_write.py`) stays too, as defence in depth rather than a replacement.

  **Quoting is semantic here, not cosmetic — it is the whole reason the grammar is strict.**
  `add-allow-policy --scope user --intent "x" echo something > somewhere` parses as `add-allow-policy` invoked with args
  `[echo, something]` plus a redirect the OUTER shell performs against `add-allow-policy`'s own stdout before the tool
  ever runs — the policy that would persist is `"echo something"`, not what the caller meant, and `"> somewhere"` never
  reaches the tool at all. Quoting the whole command instead —
  `add-allow-policy --scope user --intent "x" "echo something > somewhere"` — makes it ONE argument, which is what the
  grammar exists to guarantee.

  Every shape other than the one accepted grammar **denies** (never asks) via an `AddAllowPolicyGrammarViolation`
  Reason, rendered by the single renderer like every other reason — never a hand-built string at the policy site. Its
  `violation` field is one of eight controlled-vocabulary codes, each with its own explanation clause in
  `reason_renderer.py`'s `_ADD_ALLOW_POLICY_VIOLATION_EXPLANATIONS`:

  | Code                         | Fires when                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
  | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | `redirect_on_invocation`     | A redirect sits on the invocation itself — the flagship case above.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
  | `shell_touched`              | The invocation is part of a pipeline, a `&&` / `\|\|` / `;` list, backgrounded, or carries a command substitution anywhere in it — detected the same way `bypass_transform` is, via `Statement.as_sole_invoked_program()` plus an explicit `.redirects` check, since `as_sole_invoked_program()` alone does not catch a redirect on the recognized statement. Also fires when the entry (command) argument itself references any variable (`Argument.referenced_variables` non-empty, fixed 2026-09-18) — a bare `ParamExp` (`$HOME`/`${HOME}`) is not a `Statement` subtype and so is invisible to `as_sole_invoked_program()`'s own gate, which only sees `CmdSubst`/`ProcSubst`; without this, `add-allow-policy --scope user --intent "x" "cat $HOME/file"` would classify normally and show the human a narrower entry than `lib/add_allow_write.py` would actually persist (it parses real post-expansion argv). |
  | `missing_scope`              | `--scope` was not given at all.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
  | `duplicate_scope`            | `--scope` was given more than once.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
  | `invalid_scope_value`        | `--scope`'s value is neither `user` nor `project`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
  | `missing_intent`             | `--intent` was not given at all.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
  | `no_command_argument`        | Zero command arguments remain after consuming the flags.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
  | `multiple_command_arguments` | More than one command argument remains — the quoting failure the grammar exists to catch.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

  **Flag ORDER is deliberately not part of the grammar** — only the flag/positional SHAPE is fixed (exactly one valid
  `--scope`, exactly one `--intent`, exactly one remaining command argument); `--intent` may precede `--scope` and
  either may be interleaved with the command argument. This was an unattended judgment call made while reopening this
  leaf with no human available to disambiguate "the ONLY accepted one" against a fixed positional template — see the
  improvement file's Design Decisions for the reasoning and how to override it in one place if a reviewer intended the
  stricter reading.

  **Once the grammar matches, the proposed ENTRY itself is validated too (improvement 20260925-120037), before ever
  building the `ask` diff.** `lib/proposal_validation.py`'s `proposal_problems` builds the entry through
  `AllowedCommand. from_entry` for static problems (an unrecognised filter/parser type, a malformed `programGlob`, ...)
  and — for a `provided`/`command` parser — consults its own describe response too (see the Describe Protocol section).
  Any problem denies with one `AddAllowPolicyProposalInvalid(problem)` Reason per problem — a SEPARATE Reason from the
  eight grammar violation codes above, since this is a defect in the entry's CONTENT, not its SHAPE — so a human
  approving the dialog is never asked to bless an entry that would never vouch for anything once written.
  `lib/add_allow_write.py`'s write side re-runs the same check before writing, as defence in depth.

  **Quoted-argument display, fixed 2026-09-18 (reopened):** `_classify_add_allow_invocation` reads every token via
  `Argument.text` — see [Statement: What Every Policy Actually Reads](#statement-what-every-policy-actually-reads) below
  for what that accessor now does. Before this fix (and before improvement-20260918-205740's later merge into `.text`
  itself, superseding the interim `Argument.literal_text` accessor this leaf originally added), a double-quoted
  `--scope`/`--intent`/command argument read as `""` via `.text`, which was worse than a display bug for `--scope`:
  `add-allow-policy --scope "user" --intent "x" "rg"` was wrongly DENIED outright (`invalid_scope_value`, since `""`
  matches neither `user` nor `project`), rejecting a legitimate, correctly-quoted canonical invocation.
  `_classify_add_allow_invocation` (`lib/escalation_policy.py`) reads every token — the `--scope`/`--intent` flag names
  themselves included — via `.text`, so a single-quoted, unquoted, or double-quoted invocation all classify and display
  identically. `.text` still contributes nothing for a `ParamExp`/`CmdSubst`/`ProcSubst`, matching its own behaviour for
  content neither can statically see. The actual config write was never affected either way — `lib/add_allow_write.py`
  parses real `argv`, never the shfmt AST.

  **Entry-argument `ParamExp` gap, fixed 2026-09-18 (improvement-20260918-205740):** a bare variable reference in the
  entry argument (`add-allow-policy --scope user --intent "x" "cat $HOME/file"`) used to slip past the `shell_touched`
  gate entirely — `as_sole_invoked_program()` only treats `CmdSubst`/`ProcSubst` as shell-touching (they are `Statement`
  subtypes reachable via `sub_statements()`), and a `ParamExp` is not one. The invocation classified normally and the
  `ask` dialog showed a narrower entry (`cat /file`, the partial literal recovery) than `lib/add_allow_write.py` would
  actually persist. `_classify_add_allow_invocation` now also checks the entry argument's own
  `Argument.referenced_ variables` and returns `shell_touched` when it is non-empty — uniform across `$HOME` / `"$HOME"`
  / `${HOME}` since that field already recurses through `DblQuoted` the same way `.text` does, with no new quoting-style
  rule needed.

## The PreToolUse Hook JSON Protocol

`hook_envelopes.pretooluse_bash_response(decision)` / `pretooluse_path_response(decision)` (`lib/hook_envelopes.py`) are
the ONLY place a `PermissionDecision` becomes the JSON a PreToolUse hook actually prints. Both share one private
implementation — the mapping is identical for the Bash and Read/Grep/Glob hooks, since it depends only on
`PermissionDecision.decision`/`.reason`, not on which entrypoint is calling.

- **`passthrough` -> prints nothing (`None`).** Claude Code reads silence as "no opinion" and falls through to its own
  permission rules. This is the ONLY outcome that produces no output at all.
- **Every other outcome ->
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": ..., "permissionDecisionReason": ...}}`.**
  This includes `allow` — an allowed command still gets the envelope, with an empty reason string, rather than joining
  `passthrough` in producing no output. Conflating the two would collapse a positive grant with an abstention, which is
  exactly the distinction the outcome vocabulary exists to preserve.
- **`reason` is either a tuple of `Reason` value objects or an already-rendered string, and the envelope builder handles
  both.** The ordinary pipeline's `deny` carries a `Reason` tuple, rendered here via `reason_renderer.render`; the
  escalation transformers' `ask`/`passthrough` (`escalation_policy.py`) already hand back a finished prose string of
  their own, which passes through unchanged rather than being re-rendered.
- **`bin/command-policy-analyze-bash-command` and `bin/command-policy-analyze-path` are thin subprocess wrappers** over
  this mapping: parse the hook's stdin JSON, extract the command (`tool_input.command`) or path
  (`hook_envelopes.path_from_tool_input(tool_name, tool_input)` — Read's own `file_path` key vs. Grep/Glob's `path`
  key), call `Config.decision_for`/`decision_for_path`, print the envelope or nothing. Malformed stdin JSON is treated
  as passthrough (print nothing) on both entrypoints, matching this package's other hooks
  (`command-policy-lint-config-on-write`) rather than the old engine's "deny with 'Invalid JSON input'" — a
  transport-layer edge case neither entrypoint's own contract pins to a specific reason string.

## What the Engine May Not Conclude From Text It Cannot See

A command substitution's expansion is unknowable at analysis time. The rules below govern what an entry's filters may
still claim in its presence. They are the most-refined part of the model and the easiest to get subtly wrong, because
the naive reading ("a substitution is dangerous, deny it") and the naive implementation ("filters run against the
literal arguments") are both wrong in different directions.

**These rules are about content unknowable IN PRINCIPLE — a substitution's expansion, a variable's runtime value — never
content merely misread due to a bug.** Until improvement-20260918-205740, a purely literal double-quoted word
(`"rm -rf /"`, `"--danger"`, `"/etc/passwd"`) fell into the latter bucket by mistake: `Argument.text`'s naive one-level
`Parts` join misread it as the empty string, even though its content was fully statically knowable (a `DblQuoted` word's
literal content sits one level deeper, in that part's own nested `Parts`, and simply needed to be recursed into). That
misreading let a bare double quote defeat a `bypass-policy` re-evaluation, a block filter, and a path containment check
— not because the content was genuinely unknowable, but because the accessor was blind to nesting it could have read.
The fix (see [Statement: What Every Policy Actually Reads](#statement-what-every-policy-actually-reads) below) corrected
`Argument.text`/`Redirect.target_text` at the source, so the rules below are once again about real unknowability only,
as originally intended.

**The rules below are enforced uniformly for both kinds of unknowable content.** `ArgumentKnowability`
(`lib/argument_knowability.py`) computes, per argument, whether its `.text` is a complete value or only a FRAGMENT — a
`ParamExp` (variable) and a `CmdSubst`/`ProcSubst` (substitution) are unknowable in exactly the same sense, and
`allowed_command_policy.py` threads that one signal into `_filter_passes` and the argument-path containment check
without distinguishing which kind produced it. `onlyTheseVariables` remains a SEPARATE grant: it vouches for WHICH NAMES
may be referenced (the whole-command `_first_disallowed_variable` check), never for the VALUE a filter inspects.
**Declaring a variable is not a grant of filter opacity** — the engine does not read a declared name as license to trust
the fragment it shares a word with.

**Unknowability is a property of the WORD, not of the argument list.** A literal that shares a word with unknowable
content is a FRAGMENT, not a value, and the two questions "is anything unknowable present" and "is the text I am about
to compare complete" have different answers. Reading a fragment as though it were the whole argument is the single
mistake behind every hole in this area.

- **Absence is never provable.** A filter asserting content is ABSENT (`action: "block"`) can never be satisfied next to
  a substitution. `echo $(echo safe)` against an entry forbidding `--forbidden-flag` must DENY, even when the inner
  command is itself allow-listed — nothing static rules out the expansion being exactly that token.
- **Presence is provable only from a SEPARATE, fully-literal word.** Word-splitting can only ADD arguments, never remove
  a literal already in the AST, so `echo --required-flag $(echo safe)` still satisfies an `action: "required"` filter —
  the flag is its own complete word. The rule does NOT extend to a literal sharing a word with the unknowable part:
  `echo safe$(echo x)` proves nothing about an `action: "required"` filter pinning `^safe$`, because the real argument
  is `safe` plus whatever the expansion contributes. A blanket "substitution plus any filter means deny" rule would
  still be wrong, not merely conservative — but so is treating a fragment as the evidence.
- **Position is not provable once something unknowable precedes it.** An expansion of anything other than exactly one
  word shifts every index after it. `echo $(echo one) --required-second-argument` must DENY against a `required` filter
  pinning argument index 1 — the flag is present, but may land at index 0 or index 4. Holds for both `argumentAtIndex`
  (counts all arguments) and `positionalArgAtIndex` (counts only positionals).
- **The shift bites only forward.** An index pinned by a literal AHEAD of the substitution stays provable:
  `echo expected-first $(echo tail)` satisfies a `required` filter on positional index 0 and is ALLOWED. Without this,
  an engine could satisfy the rule above by denying every index filter that merely shares a command with a substitution.
- **An entry restricting no content is unaffected — as far as its FILTERS go.** An entry that permits any arguments is
  not made less true by arguments it cannot see, so no filter of its own objects. Argument-path containment is a
  separate question that such an entry still has to answer; see the containment rule below.
- **`action: "block"` on an index-based filter needs no separate rule** — it is already denied by the absence rule,
  regardless of index.
- **Argument-path containment does not depend on the entry making a claim at all.** It is not a pattern assertion but a
  boundary, and it asks its own question of every entry that has not declared `hasNoPathParameters`: does an argument
  whose value cannot be known occupy a slot this entry's parser treats as a path operand? `cat ./sub$ESC` DENIES, and so
  does `echo $(date)` against a bare entry. See the fuller treatment just below.

**Argument-path containment, in full: whatever cannot be ruled out is a path.** Containment asks two questions, not one.
Every path the parser actually NAMED must resolve inside the project or an allowed prefix — and separately, no argument
whose value is unknowable at analysis time may occupy a slot the entry's own parser treats as a path operand
(`_an_unknowable_argument_occupies_a_path_operand`, `allowed_command_policy.py`). The second question is answered by
re-parsing the invocation with a marker appended to each unknowable argument and seeing whether any resulting path
carries it; matching a fragment's own text against `paths_for_validation` would prove nothing, because that field holds
resolved absolute paths and a fragment is frequently the empty string.

**No knowledge means no exemption, and this is a general rule, not a property of one parser.** The `DefaultParser` knows
no program's argument grammar at all, so it can never rule an argument OUT, and **every** argument it sees is a path
candidate — options included. That closed two forms of one hole that measurement found open: a literal absolute path
riding inside an option word was never examined at all, because dash-prefixed words went to `options` and detection ran
only over `positionals` (`ls --color=/etc` simply allowed); and because "the parser detected no path" was treated as
evidence that no path was there, one allow-listed string-producing program was enough to fill an empty-looking slot at
runtime (`ls $(echo /etc)`, `cat $(echo ~/.ssh/id_rsa)` and `rg -f $(echo /etc/passwd) pattern` all allowed). An absent
literal is evidence about the parser, never about the runtime value.

`StructuredParser` carries the same rule one rung up the knowledge ladder: total candidacy by default, ruled out only by
an explicit per-slot `path: false` declaration. Attaching a `structured` parser used to be measurably WEAKER than
attaching no parser at all — a positional not named in a `pathPositionals` list, or an option's value not named in a
`pathOptions` list, fell back to the same "does this look path-shaped" guess `DefaultParser` had already lost, so
`tool --colors=/etc/passwd` and `tool --colors /etc/passwd` both allowed against a `structured` parser declaring
nothing, while the same commands deny with no parser at all. A config author who declares nothing now gets the same
maximum strictness the default parser always had; every relaxation is an explicit, auditable, falsifiable statement
about the program's real grammar — the same character `hasNoPathParameters` has (see below). The one exception, kept
deliberately narrow: `paths_for_filtering` (the field `PathsFilter`'s `exactly` set-membership reads) still runs the old
shape heuristic over positionals nobody declared at all, because a surplus member there is a wrong member that fails the
filter, not a spare check — widening it the same way validation widened would silently turn a real `FilterRejected`
denial into an ALLOW.

**An entry therefore earns the right to carry unknowable content in exactly three ways, and only three.**

1. `hasNoPathParameters: true` — a factual claim that the program takes no path operands at all, which makes the
   containment question inapplicable rather than waived. This is the flag's real job: it EARNS substitutions by
   asserting something true, and asserting it falsely is a defect of the same kind as a wrong parser, not a shortcut.
   **The rendered `UnknowablePathArgument` denial hint must say so, not invite the opposite reading.** Before
   improvement `20260919-081655`, the hint read "...substitute the real value first, or invoke a program whose entry
   declares `hasNoPathParameters`" — easily misread as "add that flag to THIS entry and the denial goes away," exactly
   the waiver-not-a-factual-claim failure this point warns against. It was live and load-bearing: an audit of the
   operator's own config found the flag declared FALSELY on three entries, one of which measurably let a command
   substitution reach a sensitive path. Reworded to "...or choose a different program that genuinely takes no path
   operands," naming the fix as switching programs, never as decorating the one that was just denied.
2. A parser that knows the grammar well enough to classify the slot as something other than a path.
   `grep $(echo pat) README.md` and `chmod $(echo 755) bin/x` are ALLOWED because those parsers know positional 0 is a
   pattern and a mode respectively, while `cat $(echo README.md)` is DENIED because cat's parser calls every positional
   a file. Parser quality is the explicit currency here — before this rule the same intent got opposite verdicts
   (`head -5 $(echo README.md)` allowed, `cat -n $(echo README.md)` denied) purely by which entry happened to have a
   parser. This route is reachable two ways: CODE-level knowledge, writing a `provided`/`command` parser script that
   classifies the slot, or DECLARED knowledge, a `structured` parser's per-slot `path: false` on the option/positional
   that is not a path. The two sit on one ladder — no parser means every argument is a candidate; a `structured` parser
   means a slot is ruled out exactly when the config says so, in a form checkable against the program's own man page; a
   `provided`/`command` parser means a script decides.

   A worked example classifies one POSITION; a wrapper program's parser can instead classify SPANS.
   `parsers/spawn-claude.py` (`spawn-claude <name> [...claude-args] [-- <prompt>...]`) splits its argv at the first
   literal `--` into three spans, each with its own path-candidacy treatment:
   - **Session name** (argument 0, before any flags) — NOT a path candidate. Positively known: it is a display name
     (prompt box, /resume picker, terminal title) and a zellij pane/stack title, never a filename.
   - **Forwarded-args span** (everything between the session name and the first literal `--`) — TOTAL path candidacy,
     every token. This is the one span the parser has no knowledge of, so it gets no exemption — the same rule the bare
     `DefaultParser` applies to an entry with no parser at all.
   - **Prompt** (everything after the first literal `--`, joined with spaces) — NOT a path candidate. Positively known:
     it is a chat message, never treated as a filename by the wrapper itself. This is load-bearing, not incidental: an
     orchestrator dispatch's seed prompt begins with `/` because it is a slash command, and without this exemption it
     would read as an absolute path and deny outright.

   The forwarded-args span's total candidacy is chosen over enumerating the wrapped program's flags in EITHER direction,
   and that choice is the point, not an afterthought: a block-list of the dangerous flags is unusable because join-based
   filters read the whole invocation's text, including the prompt, so it would fire on prose that merely mentions a
   flag; an allow-list of the path-valued ones is already incomplete the day it is written, and a flag added upstream
   and not added here fails OPEN — the one direction this engine cannot tolerate. Total candidacy has nothing to keep in
   sync with the wrapped program's evolving flag surface. This is the general form for any wrapper whose grammar has a
   positively-known non-path span next to an opaque forwarded span: classify the spans you can prove, and give the rest
   of the invocation no exemption at all.

3. Neither, in which case the invocation denies and the caller restructures or escalates. Restructuring is usually cheap
   and strictly better: `ls $(project-root)` denies, but `project-root` is itself allow-listed, so running it, reading
   the real path, and then running `ls /that/literal/path` is two auto-approved commands, both fully statically
   checkable, with no convenience-shaped hole left behind.

The cost is one extra parse per affected invocation, and for a `provided`/`command` entry that is a second subprocess.
That is deliberate, and it is not in tension with the rule that external-parser entries get no knowable-only re-parse
for a FILTER: a filter can fail closed at no cost, whereas declining the re-parse here would deny every external-parser
entry any substitution at all and so delete route 2 — the one that makes parser quality worth investing in.

The known, accepted residual: an attached short-option value (`-f/etc/passwd`, with no `=` to split on) is resolved by
the default parser as one whole word and so reads as project-relative. Recognising it would need an option vocabulary
that parser by definition does not have; an entry that needs `-f` understood declares a parser that understands it.

**These rules RELAX the old engine, they do not tighten it.** `analyze-bash-command.py` already skips any filtered entry
whose arguments contain a substitution — a blanket rule that reaches the right answer for absence and the wrong one for
the two provable cases above. What changes in the new model is the outcome such a skip lands on (deny+hint rather than
`filterRejectionResponse`'s default passthrough) and the precision of when it fires.

## A Filter Sees Only What the Parser Produced

Filters do not read the command line. They read a `ParsedResult`, and what lands in it is decided by the entry's
`commandParser`. A filter naming something the parser never produced does not fail loudly — it matches nothing, and
"matched nothing" under `action: "block"` means the filter **passes**.

The default parser applies one rule: a token starting with `-` is an option, everything else is a positional. It never
associates a value with an option, so `-m wip` yields an option `-m` with an empty argument list plus a positional
`wip`. Only a `structured` parser told which options consume values — a per-slot `options` declaration, e.g.
`{"option": "-m", "arguments": 1}` — produces an option carrying its value, and only the external-script and bundled
parsers can populate `named` at all.

**That option/positional split governs FILTERS, not path candidacy — do not carry the distinction across.** Path
candidacy for validation ignores it entirely: the default parser cannot rule any argument out as a path operand, so
every argument becomes a candidate, options included (see
[argument-path containment](#what-the-engine-may-not-conclude-from-text-it-cannot-see) above). Reading the split as
though it also decided which arguments get path-checked is precisely the inference that left `ls --color=/etc` allowed.

**This is why an `optionValue` filter is silently inert without a parser that consumes the option's value.** Written
against the default parser, `{"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}` inspects an
empty value, matches nothing, passes, and the entry vouches for precisely the invocation the filter was added to stop.
No typo is involved and both the type and the action are valid, so type/action validation does not catch it. The engine
rejects this combination at load time instead — whether an option consumes a value is knowable from the entry's own
parser config, with no command in hand.

The general form is worth carrying: **before trusting a filter, ask what the entry's parser actually produced.** A
filter whose subject the parser cannot populate is not a weak restriction, it is no restriction.

## Filter and Parser: The Value-Object Split

A `Filter` (`lib/filter.py`) is a `Matcher` bound to an `Action` (`matcher.py`/`action.py`), constructed only via
`Filter.from_definition(definition, path_resolution=None)`. The split follows the one piece of duplication that
mattered: today's nine filter classes each own both "what to extract and compare" and "what to do with the result"
(`block` inverts, `required` passes through), and the second half is identical across eight of them. `Matcher` owns the
first half — it has its own family of concrete classes (regex-against-all-arguments, regex-at-an-index, a named value,
an option's value, an option's presence, ...) — `Action` owns only the inversion, in exactly one place. `PathsFilter`
(`paths_filter.py`) stays entirely outside the Matcher/Action composition (its "exactly"-match-over-a-list semantics has
no block/required concept to share) but IS one of `Filter.from_definition`'s own dispatch targets, alongside
`NestedCommandFilter` — both `paths`/`nestedCommand` handling moved here (improvement 20260925-120037) from
`AllowedCommandPolicy`'s own former string dispatch, so every filter TYPE resolves in one place regardless of shape.
`from_definition` never raises: every defect (unknown type, uncompilable pattern, unrecognised action) degrades to an
`InvalidFilter`, which always fails to match — see
[Load-Time Rejection Superseded by Construction-Time Problems](#load-time-rejection-superseded-by-construction-time-problems)
above for the full construction-time design this section's own `Filter`/`Matcher`/`Action` split still holds underneath.
**Construction happens ONCE, in `AllowedCommand.from_entry`, not per-decision inside `AllowedCommandPolicy` any more** —
`AllowedCommandPolicy` only evaluates the already-built objects it is handed.

**A Matcher's result is three-state, not boolean** (`MatchOutcome` in `match_outcome.py`): `MATCHED` / `NOT_MATCHED` /
`TARGET_ABSENT`. A Matcher whose target does not exist at all — an out-of-bounds index, a missing named value, a missing
option — reports `TARGET_ABSENT`, and `Action.applies_to()` always treats that as "filter fails," regardless of `block`
or `required`. This is not incidental: `action.applies_to(bool(matched))` would invert those matchers' outcome under
`block` (an absent target would read as "did not match" -> "block passes" -> the invocation is vouched for), which is a
fail-open in the direction this engine cannot tolerate. Reasoning about a filter's outcome from `Matcher.match()` alone,
without going through `Action.applies_to()`, reintroduces exactly this bug.

**Parsers split along a purity line, with injected edge-level collaborators standing in for the ambient state a "pure"
parser cannot read.** `DefaultParser`/`StructuredParser` are pure functions of their arguments plus a
`PathResolutionContext` (`path_resolution.py`) supplied at construction, which stands in for the `os.path.exists()` /
`os.path.abspath()` / `os.path.realpath()` reads path detection used to perform directly — `for_process()` is the one
place that context reads real ambient state, everywhere else a test injects a fixed cwd and predicate. `CommandParser`/
`ProvidedParser` are pure config objects with an `interpret(raw_output)` method; neither calls `subprocess` — the only
`subprocess.run` in this family lives in the edge-level `ExternalParserFactory` (`external_parser_factory.py`), which a
caller constructs and injects rather than a value object building ad-hoc. **Every external-parser failure — non-zero
exit, timeout, malformed JSON, a missing or non-executable script, an empty command path — collapses to the same `None`
from the factory.** There is no configurable `fallback` any more; the old engine's `deny|ask|legacy` knob does not exist
in the new schema.

`PathResolutionContext.absolute_path_of` resolves symlinks (via an injected `realpath_predicate`, non-strict
`os.path.realpath` for `for_process()`) on top of its lexical join/expansion — the one seam every path-boundary consumer
shares, obtained from the single `Config._path_resolution()` factory. Redirect validation, `allowedCommands`
argument-path validation, `PathsFilter`, and `decision_for_path` therefore all resolve symlinks uniformly with no
per-consumer logic. `is_contained` resolves the boundary side too — the project root (realpath'd once at construction)
and every `additionalAllowedPathPrefixes` entry (routed through `absolute_path_of`, so it also gets `~`-expansion) — not
only the candidate, so a symlinked project root or a symlinked allowed-prefix entry does not produce a false denial.

`ParsedResult` (`parsed_result.py`) carries two independently-named path fields, `paths_for_validation` and
`paths_for_filtering`, replacing a single shared `paths` list that redirect-path validation and `PathsFilter` both used
to read — populating one no longer silently changes what the other sees.

The two have since genuinely diverged in BOTH pure parsers, which is what that split was for — with different mechanics
reflecting each parser's own knowledge. Validation is conservative and wants every candidate it cannot rule out, so a
surplus entry there only buys an extra containment check: the default parser's validation takes every argument, and the
structured parser's takes every slot not declared `path: false`. Filtering feeds `PathsFilter`'s `exactly`
set-membership semantics, where a surplus entry is not a spare check but a wrong member that fails the filter — so
filtering keeps the shape heuristic (looks path-shaped, or the injected context says it exists) in both parsers: the
default parser runs it over positionals only, and the structured parser runs it over positionals nobody declared at all
(a declared slot, whichever way, skips the guess entirely).

## Statement: What Every Policy Actually Reads

Every policy in the pipeline — `allowedCommands`, `blockedCommands`, `sensitivePaths`, redirect validation, the
bypass/add-allow escape hatches, `nestedCommand` — reasons about a `Statement` (`lib/statement.py`), not a raw shfmt AST
dict. `Statement.from_command(command)` builds a tree mirroring the shell's own nesting — a pipeline's two sides, an
`if`'s condition/then/else, a case item's body — rather than the old engine's `walk_ast`, which flattened everything
into an unordered stream and forced callers to re-derive structure from `Type`/`Redirs`/`Stmts` key inspection.

**Three invariants baked into Statement matter for policy correctness, not just AST fidelity:**

- **`Argument.text` recursively recovers a word's real literal content — there is no separate `.literal_text`
  accessor.** `Argument.text` (`Command.arguments()`'s per-word value object) unwraps a `DblQuoted` word's own nested
  `Parts` as deep as needed via a shared recursive helper (`_recursive_text_of_parts`), so `"user"` reads as `"user"`,
  not `""`. It still contributes `""` for a `ParamExp`/`CmdSubst`/`ProcSubst` — that content is genuinely unknowable,
  not merely nested, and every ordinary policy — `allowedCommands` filters (`allowed_command_policy.py`),
  `nestedCommand` (`nested_command_filter.py`), `bypass_transform`'s own wrapped-text extraction — depends on `.text`
  never claiming to see THAT content. **`.text` still carries no signal that it dropped something** — a word mixing
  literals with an expansion (`safe$HOME`, `--dang$X`) reads as a complete, ordinary short string, and the accessor
  itself has not changed. What changed (improvement-20260919-112214) is who bears the obligation this creates: rather
  than leaving every caller to independently remember to consult `contains_substitution` / `referenced_variables` (and
  risk forgetting to — the whole-command `onlyTheseVariables` gate did, for years), `ArgumentKnowability`
  (`argument_knowability.py`) is now the single place that combines those per-word signals plus `word_safe` into the
  three decisions a caller actually needs: does this defeat absence proof, which arguments are safe to re-parse as
  knowable-only evidence, does this shift a pinned index. Both `contains_substitution` and `referenced_variables` are
  per-word and both already recurse through `DblQuoted`, so `$HOME` / `"$HOME"` / `${HOME}` behave alike, and
  single-quoted `'literal$X'` correctly reports no expansion at all. Read the wider "What the Engine May Not Conclude
  From Text It Cannot See" rules above for why that distinction matters. `Redirect.target_text` (also in `statement.py`)
  applies the identical recursive fix through the same shared helper.

  This merges into `.text`/`.target_text` directly what a short-lived interim design (leaf 20260915-010959, 2026-09-17)
  had instead routed through a separate, additive `Argument.literal_text` accessor with exactly one caller
  (`escalation_policy.py`'s `_classify_add_allow_invocation`) — that leaf's own Interface hand-back said a future caller
  hitting this gap "should follow the same pattern (an additive accessor, not a change to the pinned field) rather than
  re-deriving it." Improvement-20260918-205740 deliberately supersedes that guidance after re-evaluating it live:
  `.text` has exactly three production readers (`escalation_policy.py`'s `bypass_transform`,
  `allowed_command_policy.py`'s `argument_texts` construction, and its own `_substitution_indices` dash-classification),
  and none of the three needed the naive one-level-join behaviour specifically — only the substitution-unknowability
  rules, which the merged accessor preserves identically. Keeping a separate `literal_text` would also have left
  `_substitution_indices` (which reads `.text` directly, not through `argument_texts`) disagreeing with the parser's own
  classification whenever a double-quoted literal sat next to a real substitution — merging into one accessor makes that
  class of site-vs-site inconsistency structurally impossible, since there is only one accessor left to read.

- **The bypass/add-allow recognition asymmetry is load-bearing, not an oversight.**
  `Statement.as_sole_invoked_program()` — the check behind whether a line is "just `bypass-policy` / `add-allow-policy`
  and nothing else" — checks `.is_backgrounded` (excludes) but deliberately does NOT check `.is_negated`.
  `! bypass-policy true` still counts as a sole invocation of the wrapper. Changing this would silently change the
  escape hatch's behaviour, not fix a bug.
- **An unrecognized shfmt node type fails closed, not open.** Any `Cmd.Type` Statement does not model by name (today:
  `ArithmCmd`, `DeclClause`, `LetClause`, `TestClause`) collapses into `UnrecognizedCmd`, which still performs a blind
  recursive scan of its own content for anything Statement-shaped. This is the same "may hide anything" posture the
  `nestedCommand` filter and the unknowable-expansion rules above depend on — a node shape the engine has never seen
  still cannot silently smuggle a command past the allowlist.

`Statement.all_redirect_targets()` is what `sensitivePaths` and redirect-path validation actually walk — it recurses
into `CmdSubst`/`ProcSubst` subtrees, so `echo $(cat < /etc/shadow)` is caught the same way as a top-level redirect.
`RedirectOperator` (`lib/redirect_operator.py`) names the raw integer `Op` field (`>`, `<<`, `&>`, ...); an `Op` outside
its 12 verified values keeps the raw integer rather than being silently dropped, for the same fail-visible reason
`UnrecognizedCmd` does.

## Wrapper Commands and Nested Evaluation

A wrapper hides its real command inside its own arguments. `xargs rm`, `sh -c "..."`, `env FOO=1 rm`, `timeout 5 rm` —
the invoked program is `xargs`/`sh`/`env`/`timeout`, so a program-level allowlist never sees the `rm` at all, and
`blockedCommands: ["rm"]` never fires. Allow-listing a wrapper without handling this allow-lists everything it can run.

The answer is **nested evaluation, expressed as an ordinary filter**:

```json
{ "program": "xargs", "commandParser": {...}, "filters": [{ "type": "nestedCommand" }] }
```

The filter takes each sub-command the entry's parser published, builds a child statement from the parent by
copy-on-write — the child inherits the same config and policies with only the command node replaced — re-runs **the same
pipeline** on it, and requires `allow`. So a wrapped command faces exactly the checks it would have faced on its own:
`blockedCommands`, `sensitivePaths`, path validation, its own filters.

**It is a filter rather than an entry-level key on purpose, and the reason is composition.** Filters already AND-compose
within an entry and OR-compose across entries, so nested evaluation inherits both instead of running a parallel opt-in
mechanism beside them. That makes the common exemption expressible with no new machinery — two entries, one vouching
outright when `--dry-run` is present, one applying the nested check otherwise:

```json
[
  { "program": "xargs", "filters": [{ "type": "optionPresent", "option": "--dry-run", "action": "required" }] },
  { "program": "xargs", "filters": [{ "type": "nestedCommand" }] }
]
```

**It takes no key naming what to read.** Sub-commands arrive on the parser's dedicated sub-command channel, so there is
nothing to point at. (This replaced an earlier entry-level `evaluateNamedValueAsCommand: "<named value key>"` design;
converting old configs belongs to the migration skill, and the engine carries no back-compat shim.)

### The `nestedCommands` Channel

A wrapper parser publishes sub-commands on a dedicated top-level `nestedCommands` key, separate from `named` — it is the
ONLY channel the filter reads:

```json
{ "options": [...], "positionals": [...], "named": {...}, "paths": [],
  "nestedCommands": [{ "text": "rm -rf ./build", "shape": "argv" }] }
```

The path from script to decision crosses four files, which is why no single one of them explains it:
`parsers/<program>.py` prints the key -> `command_parser.py`'s `interpret()` turns each entry into a `NestedCommand`
(`parsed_result.py`), defaulting a missing `shape` to `"shell"` -> `nested_command_filter.py` calls
`evaluate_nested(entry.text, depth + 1)` per entry and requires EVERY entry to decide `allow`.

**A wrapper parser publishes on BOTH `nestedCommands` and `named["command"]`.** Only the first is load-bearing; the
second exists so a config author can point an ordinary `namedValue` filter at the wrapped command and constrain it by
pattern, which the `nestedCommand` filter itself cannot do — it takes no pattern and only asks whether each sub-command
independently decides `allow`. Dropping `named["command"]` would silently remove an expressible restriction, so the
redundancy is deliberate.

**`shape` declares how the text should be read, and is carried explicitly rather than inferred.** `"argv"` means
already-split words re-quoted into one string (`shlex.quote`-joined), so word boundaries survive re-parsing; `"shell"`
means shell syntax to be parsed as-is. The distinction tracks a real difference in what wrappers accept —
`timeout`/`nix -c`/`xargs` hand over trailing argv, whereas `nix-shell --run` takes a single shell STRING.

**Nothing in the engine branches on `shape` today** — the filter forwards only `entry.text`, and
`Config._decision_for_text` always parses via `Statement.from_command`. The two values therefore behave identically at
runtime, because `shlex.quote` output is itself valid shell syntax that re-parses to the same words. Set it honestly
anyway: it is the declared contract, and a future consumer reading it is the whole reason the field is explicit.

**What a parser publishes when there is no wrapped command splits by what is KNOWABLE**, and the asymmetry is deliberate
rather than an inconsistency:

- **Nothing is going to run -> publish nothing.** A bare `nix-shell` (no `--run`/`--command`) enters an interactive
  shell; there is no command the parser could name, so it emits no `nestedCommands` key and the filter fails closed.
  Same for `timeout 10` with no command, and for `nix run`/any `-c`-less `nix` invocation — there the program is named
  by a flake installable the parser cannot resolve to a command word, so claiming ignorance is honest.
- **A known default IS going to run -> publish it.** Bare `xargs` runs `echo`, a documented, statically-known default,
  so it publishes `echo` and that default is evaluated like any other sub-command. A parser that published nothing here
  would be claiming an ignorance it does not have.

**Gotchas:**

- **It fails closed.** A `nestedCommand` filter with nothing to check does not pass, so the entry does not vouch. An
  entry declaring it evaluates a nested command, whose parser extracted none, must not silently approve the wrapper.
  This is why a parser that speaks the wrong protocol denies EVERY invocation rather than failing loudly: an empty
  `nested_commands` list is indistinguishable from "the wrapper wraps nothing".
- **It needs a parser that can publish sub-commands**, which the default and structured parsers cannot. That combination
  is rejected at load time rather than denying every invocation forever. Same shape as the `optionValue` trap above: a
  filter is only as capable as the parser feeding it.
- **It sees only the wrapper's own command text, never stdin-piped operands.** `cat filelist.txt | xargs cat` cannot be
  judged on what is inside `filelist.txt`. The limit is narrower than it first looks, though: a sensitive path written
  literally on the line IS still caught, because `sensitivePaths` scans every literal regardless of which program
  receives it. Only what a command _references_ rather than _contains_ is out of reach.

## Load-Time Rejection Superseded by Construction-Time Problems

**This section describes the CURRENT design (improvement 20260925-120037), which replaces the load-time-raise model this
article originally shipped with.** Nothing in `Config`'s public contract raises `ConfigError` for an `allowedCommands`
defect any more, at load time OR at decision time — the class stays exported (other callers may still raise it for other
reasons), but the rejection mechanism it names is gone. Read this section, not the git history, for what actually
happens today.

**The rule behind which configs qualify is unchanged**: every defect below would otherwise widen the allowlist silently,
or — worse, under the old model — crash the hook outright and fail the surrounding tool call OPEN (no verdict at all).
What changed is the OUTCOME: every one of these is now a construction-time **problem**, not a raised exception, and a
problem entry does not vouch for anything rather than blowing up the process that would have decided it.

**`AllowedCommand.from_entry(entry, path_resolution, source)`** (`lib/allowed_command.py`) builds this entry's
`Filter`/parser value objects ONCE, at config-load time, instead of `AllowedCommandPolicy` rebuilding — and potentially
raising from — them on every decision. `Filter.from_definition` (`lib/filter.py`) now covers all ten filter types
(including `paths`/`nestedCommand`, taken over from `AllowedCommandPolicy`'s own former string dispatch) and never
raises: an unrecognised `type`, an uncompilable `pattern`, or an unrecognised `action` (`Action. from_definition`, still
its own raising contract, caught by `Filter.from_definition`) all degrade to an `InvalidFilter`, which always fails to
match. `lib/parser_factory.py`'s `build_parser` is the parser-side counterpart: an unrecognised `commandParser.type`, a
retired `StructuredParser` key, or an unresolvable `provided` script name all degrade to an `InvalidParser`, which
always fails to interpret an invocation. `AllowedCommand` ALSO applies the cross-object checks neither a `Filter` nor
the parser factory can judge alone — an `optionValue` filter naming an option a STATICALLY-known-pure parser
(`DefaultParser`/`StructuredParser`) never populates a value for, or a `nestedCommand` filter beside one of those same
pure parsers (which can never publish sub-commands) — downgrading the offending filter to an `InvalidFilter` too.

**`AllowedCommand.problems()`** is the public surface for all of this: a tuple of human-readable strings, empty for a
well-formed entry. `Config.from_dict` turns every entry's `problems()` into a layered `Warning`
(`Warning.allowed_command_problem`), so they flow through the ordinary `Config.warnings()` channel — `explain()`,
SessionStart, SubagentStart, the PostToolUse lint hook, `add-allow-policy`'s refusal (below) — exactly like any other
Warning, rather than only surfacing (or crashing) when a command happens to invoke that entry's program.

**`AllowedCommandPolicy`** (`lib/allowed_command_policy.py`) now only EVALUATES the pre-built `entry.parser`/
`entry.built_filters` against a command — it constructs nothing and raises nothing. A `programGlob` entry with a static
problem (a missing field, a `..`/leading-`/` escape, `program` and `programGlob` both set) is marked
`has_valid_program_glob = False` and is checked BEFORE building its fnmatch pattern, so it simply never matches any
invocation rather than crashing on a missing dict key. `_parsed_result_for`'s pure-vs-external dispatch is
`hasattr(parser, "parse")` rather than an `isinstance` check against a fixed tuple — this uniformly covers
`InvalidParser` too (it has a `.parse()` that returns `None`, so a broken parser reads as "pure" and never reaches a
subprocess).

**An out-of-range `commandSubstitutionResponse`** still falls back to the default and produces a structured `Warning`
naming the layer it came from (`defaults` / `user` / `project`) — unaffected by any of the above; see
`lib/warning_value.py`.

**The DESCRIBED half — a problem only an external parser's own `{"describe": true}` response can answer — is a separate,
later-computed set**, covered in its own section below (Describe Protocol), because it needs a subprocess and therefore
must never run on the decision hot path.

## Describe Protocol

A STATIC problem (above) can judge a `DefaultParser`/`StructuredParser` entry's `optionValue`/`nestedCommand` filters
against the parser's own capabilities, because those two parser types' capabilities are knowable from their config
alone, with no invocation in hand. A `provided`/`command` (EXTERNAL) parser has no such config to read — its
capabilities live in the SCRIPT, which the engine can only learn by asking it.

**The describe protocol is that ask**: the same script that answers `{"arguments": [...]}` on stdin (the ordinary parse
channel — see [A Filter Sees Only What the Parser Produced](#a-filter-sees-only-what-the-parser-produced)) must ALSO
answer `{"describe": true}` with
`{"publishesNestedCommands": bool, "namedValues": [string, ...], "optionsWithValues": [string, ...]}`. All 17 bundled
parser scripts (`parsers/*.py`) implement it; `gawk.py` delegates to `awk.py`'s `describe()` the same way it delegates
parsing. **A script that answers incorrectly — non-zero exit, timeout, malformed JSON, or a response missing/mis-shaping
one of the three required keys — is itself a reported problem**, never silently "capability unknown";
`lib/parser_description.py`'s `ParserDescription.from_raw` is what judges the shape.

**`lib/describer.py`'s `Describer`** is the edge-level collaborator that actually asks — the describe-channel
counterpart to `ExternalParserFactory`'s `{"arguments": [...]}` channel, same `subprocess.run`-with-JSON-on-stdin shape.
It memoises per script path WITHIN ITS OWN INSTANCE ONLY, never at module or process-wide scope: the operator's own
copy-on-write concern (a process-wide cache would be a mutable object shared between `Config`'s copy-on-write copies,
since `Config._replace` hands every field to a new instance on every `with_*`/`merged_with`) rules out storing it, or
its cache, on any value object. A `Describer` is therefore constructed FRESH, as a local variable, by each entrypoint
that needs one, and dropped when that entrypoint exits.

**WHEN the describe subprocess runs is the whole design constraint.** Measured: one bundled-parser subprocess start
costs roughly 30ms, so describing the operator's own ~10 `provided`/`command` entries at EVERY config load would add
~300ms to every single hook invocation (every Bash command, every Read/Grep/Glob, every SessionStart/SubagentStart) —
measured too expensive. The decision path does not need the capabilities anyway: an external parser that publishes
nothing for a `nestedCommand` filter already fails closed (an empty list, per the ordinary nested-command-filter gotcha
above), and an `optionValue` filter over a value the script never produces already fails to match. So:

- **`Config.described_problems(describer)`** computes the described half for every entry in a merged config, given an
  injected `Describer`. It skips any entry whose parser is PURE (`hasattr(parser, "parse")` — the same duck-typed signal
  `AllowedCommandPolicy`'s own pure-vs-external dispatch uses, which also correctly skips an already-`Invalid Parser`
  stand-in, since it has a `.parse()` too) and, for a real external parser, either reports the describe contract breach
  or checks its `nestedCommand`/`optionValue`/`namedValue` filters against the description — shared logic factored into
  `lib/described_problems.py` so `config.py` and `escalation_policy.py` don't need to import each other for it
  (`config.py` already imports `escalation_policy.py` at module level).
- **`Config.with_additional_warnings(warnings)`** folds the result back into the ordinary `warnings()` channel,
  copy-on-write.
- **Only REPORTING entrypoints construct a `Describer`**: `command-policy-render-session-start`,
  `command-policy-render-subagent-start`, `explain-policy`, `command-policy-lint-config-on-write`, and — a deliberate,
  narrow exception, not an oversight — `add-allow-policy`'s ask path (`escalation_policy.add_allow_policy_transform`,
  via `lib/proposal_validation.py`'s `proposal_problems`), because refusing an invalid PROPOSAL before ever showing the
  ask dialog is exactly what a human approving that dialog needs. This is reachable from
  `command-policy-analyze-bash-command` (any Bash command goes through the same PreToolUse hook), but only fires when
  the strict `add-allow-policy` grammar is actually recognised — a rare, deliberate, human-initiated escalation, not the
  high-frequency ordinary-command case the 300ms measurement was about. **`command-policy-analyze-bash-command` and
  `command-policy-analyze-path` themselves never construct one** — neither bin file imports `Describer` at all, guarded
  by a test that reads their source rather than merely observing that a particular input happened not to trigger it.
- **`add_allow_write.py`'s write side re-runs the same `proposal_problems` check** before writing, as defence in depth —
  the same "ask-side check plus a write-side re-check" posture `--intent` already has.

## Three Consumers: config (skill), migrate-config (skill), and find-auto-allowed-command (agent)

Improvement `20260915-011123` built the first version of `migrate-config` and `find-auto-allowed-command` — the two the
trunk's re-plan identified but no earlier leaf owned; improvement `20260919-081655` later converted
`find-auto-allowed-command` from a skill into a zero-context agent (see its own section below for why); improvement
`20260925-120037` added the third, `command-policy:config` (`skills/config/SKILL.md`) — the schema reference and
config-change workflow the other two, and every denial's own hint, all assume a session already has access to.
`migrate-config` and `find-auto-allowed-command` sit on `Config.explain()`'s rendered output as their input rather than
reading raw config or re-implementing any decision logic — `migrate-config` via `bin/explain-policy`-shaped reasoning
about the OLD schema, `find-auto-allowed-command` via the same `explain()` text already injected into its context at
dispatch, never by shelling out to `explain-policy` itself. `command-policy:config` is different in kind: it is not a
CONSUMER of a rendered decision, it is the reference a session reaches for BEFORE writing or reasoning about config at
all — `user-invocable: true`, with a description led by the user's own phrasings ("change my command policy config",
"stop asking for X", "always allow X", "block X") rather than the plugin name, which the operator found the old
`shfmt-permissions:config` skill matched poorly on in practice. `Config.explain()`'s own static advisory line
(`_ADD_ALLOW_POLICY_ADVISORY`, next to the decomposition advisory below) names both `add-allow-policy`'s canonical form
and `command-policy:config` unconditionally, in every session's injected rules — not only inside a denial's own hint —
so the skill name is present the moment a session might need it, per the operator's own diagnosis that Claude never
proposed `add-allow-policy` unprompted simply because it was never SHOWN to a session, not because of any no-prompt
rule.

**`Config.explain()` distinguishes "no config file exists at either scope" from "a config file exists but is empty."**
`config_loader.py`'s `_load_layer` used to test `path.exists()` and discard the answer, returning `Config.defaults()`
either way — byte-identical output for an absent user/project file and a present-but-empty one, so a first-time user saw
the same silent, noise-free `explain()` as someone who had deliberately configured nothing. `lib/layer_presence.py`'s
`LayerPresence` (a `LayerSearch` per layer, carrying which path was searched and whether it was found) fixes this:
`_load_layer` attaches one via `Config.with_layer_presence` for every layer it loads — found or not — and `merged_with`
unions them like every other collection, so the final merged `Config` knows what every layer's load actually saw.
`Config.explain()` renders it FIRST, and only when it has something to say: silent whenever at least one layer was found
(the ordinary case gains no noise), and otherwise a line naming both searched paths and pointing at
`command-policy:migrate-config`/`add-allow-policy` as the next step. Like every other value threaded through `Config`,
it is a plain, pre-computed record — `explain()` never touches the filesystem itself, which is what keeps it testable
with no real files on disk (see `config.py`'s module docstring on where I/O is and is not allowed to live).

**`command-policy:migrate-config`** (user-invocable, wrapped by `commands/migrate-config.md` per the "command as a
reliable entry point to a skill" pattern) is the human's upgrade path from
`packages/shfmt-permissions/skills/config/SKILL.md`'s schema to this one. `bin/migrate-config` is dry-run by default —
it reads whichever of the user/project `shfmt-permissions.json` files exist, runs each through the pure
`lib/config_migration.py` (`migrate_shfmt_permissions_config`, no I/O), and prints a JSON report per scope: the migrated
config, a structured warnings list (reusing `lib/warning_value.py`'s `Warning` — the same value object
`Config.warnings()` returns, so every consumer already knows how to render one), the existing `command-policy.json`
target if any, and a diff against it. Nothing is written until the skill has presented the report and the human has
confirmed via `AskUserQuestion`; `--write` then performs it, writing only the scopes whose source file existed. The
**translation is semantic, not textual**:

- The four dead decision knobs (`defaultDecision`, `sensitiveVariableResponse`, `pathValidationResponse`,
  `filterRejectionResponse`) are stripped, and a `dead_decision_knob_removed` warning fires for each one UNCONDITIONALLY
  — even when the source config never set it — because the user is losing that permissive fallback either way:
  deny-by-default is materially stricter than the old shipped default (`defaultDecision: "passthrough"`).
- `commandSubstitutionResponse`'s `ask`/`block` collapse to `deny` (`via-allowed-commands` survives unchanged) — the
  same collapse this article's Outcome Vocabulary section describes for the engine itself.
- Per-entry key renames (`allowedVariables` -> `onlyTheseVariables`, `pluginProgram` -> `programGlob`) and polarity
  inversion (`pathValidation: false` -> `hasNoPathParameters: true`) apply silently, the same way `Config.from_dict`
  itself would read them.
- `propagate` (string or object form) is not renamed — it is REPLACED by an appended `{"type": "nestedCommand", ...}`
  filter (see [Wrapper Commands and Nested Evaluation](#wrapper-commands-and-nested-evaluation) above), and the old
  `namedValue` selector is simply dropped, since the new filter reads whatever the parser publishes on its own
  `nestedCommands` channel instead. This is flagged with a `propagate_reshaped_to_nested_command` warning, which fires
  unconditionally — it is a structural fact about the reshape, not a probe of whether the target parser can actually
  publish. **The warning still matters for a parser the plugin does not bundle:** an entry migrated onto a
  `commandParser: {"type": "command", ...}` script written for the old engine will publish `named["command"]` and
  nothing on `nestedCommands`, so it denies the wrapped command instead of propagating to it. The four bundled wrapper
  parsers already speak the channel.
- `allowedReadPaths` (deprecated) converts into equivalent `allowedPaths` entries (`tools: "read"`) merged with any
  pre-existing ones, with an `allowed_read_paths_migrated` warning noting the conversion.
- A `commandParser.structured` entry is RESHAPED, not renamed: the old parallel keys
  (`options_with_arguments`/`double_dash_stops`/`pathOptions`/`pathPositionals`) collapse into the new engine's one
  per-slot `options`/`positionals` declaration schema, writing `path: true` EXPLICITLY on every option/positional that
  used to sit in `pathOptions`/`pathPositionals`, so the old author's assertion survives as an assertion rather than
  dissolving into a default that merely happens to agree today. This is NOT silent, unlike the plain renames above: a
  `structured_parser_defaults_to_path_active` warning fires UNCONDITIONALLY for every migrated structured parser,
  because every slot the old engine did not name is now a path candidate by default — a slot the old engine guessed was
  not a path may make its command start denying, and the fix is to add `path: false` where that guess was right. A
  second warning, `structured_parser_inert_path_option`, fires when the old config's `pathOptions` named an option
  absent from `options_with_arguments`: that combination consumed nothing under the old engine (the value parsed as a
  stray positional), so it was already a no-op, and the migration will not invent an `arguments` count the source config
  never asserted.

The old `shfmt-permissions.json` file(s) are never modified or deleted by any part of this — the migration is purely
additive, matching the trunk's cutover decision.

**`command-policy:find-auto-allowed-command`** is the AGENT every non-empty deny reason points at by name, dispatched
via the Task tool (`reason_renderer.EQUIVALENCE_POINTER`) — see
[The Reason List and Three Escalation Transformers](#the-reason-list-and-three-escalation-transformers) above for why
that pointer is unconditional. Improvement `20260919-081655` converted it from a same-conversation,
`user-invocable: false` skill into this agent — the shape the trunk's own re-plan had floated as "skill OR agent"
without ever resolving to a Design Decision, until a leaf collapsed it to "skill" on a flat input-plumbing-convenience
assertion that never actually held once examined. The agent starts from EMPTY context (subagents do not inherit skills
or history from the parent conversation), so the caller must pass the denied command and its deny reason in the prompt;
it reasons over the rendered rules the `SubagentStart` hook already injected at its own dispatch — fresher than the main
session's own `SessionStart` copy, since `SubagentStart` renders at every dispatch rather than once per session — and
reasons in prose about what auto-allowed command or shape achieves the SAME GOAL as the denied command (a near-miss
reason answers "how do I make THIS command pass," a different question from "how do I accomplish the task within what is
allowed" — a program allowed only with `--dry-run` may not do what a real run was for). Before it is allowed to conclude
that nothing works, it checks whether the denial DECOMPOSES into two auto-allowed commands — see
[Command Decomposition](#command-decomposition-recovering-from-an-unknowable-argument-denial) below — and only then
states a candidate (a single command, or a decomposed ordered pair) or says plainly that none was found. **When nothing
found works, its terminal fallback (improvement 20260925-120037) names BOTH escalation routes and when to pick each**,
rather than defaulting to only `bypass-policy` (its behaviour before this improvement, and the operator's own measured
cause for why Claude never proposed `add-allow-policy` unprompted — it was simply never named at this, the one place
every denial actually routes to): `bypass-policy` for a one-off, `add-allow-policy` for a command shape that will recur,
proposing the durable entry in its canonical form and pointing at `command-policy:config` for the schema.

**It deliberately never verifies its own candidate against `Config.decision_for` (or any equivalent), even though that
method exists and is fully wired by the time this agent runs.** A wrong suggestion is caught the moment the caller
actually tries it — the engine denies it again, which is the same self-correction loop the whole outcome model already
relies on — so a verification step here would only reintroduce engine logic into what is meant to stay a thin consumer
of the rendered rules. This is now an ENFORCED property of the agent's tool surface, not only an instruction: its
`tools:` frontmatter grants only `Read` (Claude Code refuses to spawn an agent with a fully empty `tools:` list, so
`Read` — which carries no code-execution capability — is the narrowest non-empty grant available), and no `Bash` means
the agent structurally cannot run `explain-policy` or invoke `Config.decision_for` even if it tried.

## Command Decomposition: Recovering From an Unknowable-Argument Denial

A whole class of near-miss denials traces back to a single cause: an argument the engine could not read at analysis
time, most often a command substitution (`$(...)`) or a `$VAR`/`${VAR}` reference. `DefaultParser` treats EVERY argument
as a path candidate (see [A Filter Sees Only What the Parser Produced](#a-filter-sees-only-what-the-parser-produced)),
so an entry with no smarter parser has no way to rule an unknowable value out of a path-shaped slot, and denies. The
recovery is often not a different single command but the SAME command, split in two: run an auto-allowed command that
produces the value, read it, then re-issue the original command with that value written in literally.

**The recognition rule.** All three must hold:

1. The denial is a NEAR-MISS, not categorical — the outer program does appear in the rendered `AUTO-ALLOWED COMMANDS`.
2. The blocking cause is an argument the engine could not read: a `$(...)` substitution, or a `$VAR`/`${VAR}` reference.
3. A command that is itself auto-allowed can produce that value. For a substitution, that command is usually the inner
   command verbatim. For a variable, it is any allow-listed command that prints it (`echo "$VAR"`, when `echo` is
   allowed and permits that variable).

When all three hold, the answer is an ORDERED PAIR of separate invocations — never rejoined into a new substitution,
which would just reintroduce the same unreadable argument: run the producer, read its output, re-issue the original
command with the value written in literally.

**When decomposition does NOT help** — forcing it is worse than not trying it:

- **Categorical denial.** A `blockedCommands`, `sensitivePath`, or `sensitiveVariable` objection holds regardless of
  what any argument expands to; the literal-argument half denies identically. The route is `bypass-policy`.
- **The outer program is not allow-listed at all.** Making an argument literal does not create an entry that vouches for
  the program. The route is a different program, or `add-allow-policy`.
- **The producer is itself denied.** A substitution whose inner command is not allow-listed only moves the denial to the
  first half — check the producer against the rendered rules before proposing the split, rather than proposing an
  unchecked chain.
- **A variable the session cannot obtain.** No allow-listed command can reveal it, or it is itself a sensitive variable,
  where every command naming it denies at both halves.
- **The value must stay genuinely dynamic.** Pinning it to a literal would change the semantics the command relies on,
  rather than preserve them.
- **The output is bulk data, not a value.** Decomposition is for a value that can be read and verified, not for plumbing
  large output through the reasoner.

**Decomposition launders nothing — it RESTORES static checking, it does not evade it.** `rm -rf $(cat x)` split into
`cat x` followed by `rm -rf /literal/path` still meets `blockedCommands`, every filter, and path containment on the
second half — with MORE scrutiny than the original, because the engine can finally SEE the operand it previously could
not. The reason this is the intended recovery path rather than a loophole is exactly this: the substitution was hiding
the operand from every check that exists to look at it, and decomposition is what hands that operand back.

**The prompt-injection caution.** Decomposition moves one screening step from the engine to whoever runs the second
command: they read an intermediate value and build the next command from it. Read the value, confirm it is the KIND of
value expected — a path, a filename list, a commit message, not instructions and not an unexpected blob — then write it
into the second command literally. Never pipe it onward unexamined. This surface is not new (any command substitution
already reads program output), but decomposition increases how often it is exercised deliberately.

**Known limit on how far the recognition rule can be followed from the rendered rules alone.** `Config.explain()`
renders a filtered entry only as `"<program>: must pass N filter(s)"` — it does not name which filters, so for an entry
like `git`, `find`, `sed`, or `awk`, the rendered rules say a producer entry exists and must pass filters without saying
which invocation shapes comply. Checking a producer command "against the rendered rules" (the non-case above) is
therefore sometimes a matter of reasoning from the entry's name and the rendered rules' other context rather than
reading an exact rule; a wrong guess is still caught by the engine denying it again, the same self-correction loop the
rest of this outcome model relies on.

**Do not author a static command-equivalence table for this.** Command shapes and the config that allows them change
constantly; a hand-written mapping would rot like hand-written prose. The two examples below illustrate the recognition
rule — they are not a maintained mapping of denied commands to their replacements.

**Worked example, measured against a live merged config (re-measure before relying on it — the config is a local file
and changes):** `git add $(git ls-files -m)` and `git commit -m "$(echo msg)"` both deny with
`FilterRejected(program='git', filter_type='namedValue')`, because the operator's `git` entry uses a `provided`
(external) parser and a `required` `namedValue` filter — under the settled "unknowable content under an external parser"
rule, any unknowable content anywhere in the invocation defeats a `required` filter, with no knowable-only re-parse.
Both decompose cleanly: `git ls-files -m` and `git commit -m "literal message"` allow on their own, and
`git add <a real literal path>` allows once the first command's output is read and substituted in literally. Re-run via
`Config.decision_for` against the merged config to confirm before citing these as current.

## Session Auditing: audit-session-policy

`bin/audit-session-policy` reports which Bash commands in a past Claude Code session would NOT auto-approve under the
CURRENT merged config — the human-facing tool for deciding what to allow-list next. Claude Code records no
auto-vs-manual permission decision on disk, so the report is not a log lookup: `lib/session_audit.py` resolves the named
session to its transcript, extracts every Bash command it ran (main transcript plus subagent transcripts), and
recomputes each one's decision via `Config.decision_for` fresh, against today's config, not whatever was in effect when
the session actually ran.

**The bucket a command lands in is not what it was under `shfmt-permissions`.** Under the old engine, `deny` was rare
(blocked commands only) and the report's interesting sections were `ask`/`passthrough`. Under this engine's deny+hint
model, almost every non-allowed command decides `deny` — so `deny` is now the report's PRIMARY, actionable section (each
entry carries the same equivalence-search hint a live hook denial would), while `ask`/`passthrough` are reserved for the
two escalation paths (`add-allow-policy`'s forced `ask`, and an unforced `bypass-policy` passthrough). A bypass-wrapped
command is bucketed separately again, under its own section, rather than folded into `deny`/`passthrough` — it is a
priced user intervention (see `bypass-policy`), not an ordinary gap.

## Gotchas

**The specification is authored ahead of the engine, not captured from it.** Its cases were adjudicated case-by-case;
several deliberately assert decisions the old engine does not make — the acceptance gate is explicitly NOT "zero diffs
against the old engine." The old suite's ~371 tests are harvest-as-inspiration for coverage territory only; their
asserted outcomes are not authority. **A collection or import error IS a defect.** Do not "fix" a red case by weakening
it.

**A wrapper spec asserting `deny` can pass for the wrong reason, and the suite cannot tell you.** A missing or broken
parser denies too — via `ParserCouldNotInterpretInvocation` when the script is absent, or `FilterRejected` when it
parses but publishes nothing — which is the same outcome a genuine propagation denial produces. A case that only asserts
`deny` therefore proves nothing about the mechanism it is named after. Two habits defeat this: assert at `result.reason`
level (`decision_for(...)`, then check for the specific `Reason`), and pair every deny case with an ALLOW case whose
wrapped command IS allow-listed — only the pair distinguishes working propagation from a wrapper that denies everything.
The same trap hides confounds inside a case's own config: a deny case whose OUTER program is not allow-listed either
would pass with propagation entirely broken.

**Substring matching in `sensitivePaths` is intentional.** It is catch-everything breadth for a denylist, including the
false-positive direction. Do not narrow it to path-prefix or exact matching without re-adjudicating.

**External-script parsers are a public feature, not an implementation detail.** A config author can point
`commandParser` at their own script; the engine invokes it as a subprocess and trusts its JSON `named` output with no
schema validation. This route must survive the Parser family's rewrite into value objects — it is how users write
parsers for commands the plugin does not bundle. Only the external-script route and the bundled parser that delegates to
it can populate a `named` value at all.

**Plugin `bin/` is APPENDED to PATH**, so a generically-named entrypoint can be shadowed by a system binary. This is why
hook-invoked entrypoints carry a `command-policy-` prefix while user-facing ones do not. See
[plugin-environment-probe.md](plugin-environment-probe.md) — that behaviour is measured, not reasoned about.

**Symlink resolution is not atomic with execution.** `PathResolutionContext` resolves symlinks once, at decision time;
the command runs afterward as a separate step. A symlink created, swapped, or removed in the window between the decision
and the command actually running is not caught by this or any check the engine performs. This closes the STATIC
symlink-escape gap — a symlink already in place, unchanged, at decision time — not a time-of-check-to-time-of-use race,
which no static analysis of a command string could close.

**`sensitivePaths` still does not see through an in-boundary symlink.** `sensitive_paths_policy.py` matches by substring
against raw command text and is never handed a `PathResolutionContext` (unlike redirect/argument-path validation, both
of which now resolve symlinks — see the bullet above), so a symlink sitting inside the project but pointing at a
sensitive path outside it evades Pass 0's substring check entirely. Residual gap from improvement-20260918-185726,
adjudicated as its own scope boundary rather than folded into that leaf or this one — not this article's to fix, tracked
here so it has a durable home rather than only the improvement file's own record of it.

## Glossary

| Concept                                                                             | Home                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Public entrypoint, `ConfigError`                                                    | `lib/config.py`                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Structured `Warning` (layer provenance)                                             | `lib/warning_value.py`                                                                                                                                                                                                                                                                                                                                                                                                            |
| `Statement` AST substrate                                                           | `lib/statement.py`                                                                                                                                                                                                                                                                                                                                                                                                                |
| `RedirectOperator`                                                                  | `lib/redirect_operator.py`                                                                                                                                                                                                                                                                                                                                                                                                        |
| `Filter`, `Action`                                                                  | `lib/filter.py`, `action.py`                                                                                                                                                                                                                                                                                                                                                                                                      |
| `Matcher` family, `MatchOutcome`                                                    | `lib/matcher.py`, `match_outcome.py`                                                                                                                                                                                                                                                                                                                                                                                              |
| `PathsFilter`                                                                       | `lib/paths_filter.py`                                                                                                                                                                                                                                                                                                                                                                                                             |
| `PathResolutionContext`                                                             | `lib/path_resolution.py`                                                                                                                                                                                                                                                                                                                                                                                                          |
| `decision_for_path`, `path_permission.py`                                           | `lib/config.py`, `path_permission.py`                                                                                                                                                                                                                                                                                                                                                                                             |
| PreToolUse hook JSON mapping                                                        | `lib/hook_envelopes.py`                                                                                                                                                                                                                                                                                                                                                                                                           |
| Parser family, `InvalidParser` stand-in                                             | `lib/default_parser.py`, `structured_parser.py`, `command_parser.py`, `provided_parser.py`, `parser_factory.py`                                                                                                                                                                                                                                                                                                                   |
| `ExternalParserFactory`                                                             | `lib/external_parser_factory.py`                                                                                                                                                                                                                                                                                                                                                                                                  |
| Describe protocol: `Describer`, `ParserDescription`, `described_problems_for_entry` | `lib/describer.py`, `parser_description.py`, `described_problems.py`                                                                                                                                                                                                                                                                                                                                                              |
| `InvalidFilter` (generalised `UncompilableFilter`)                                  | `lib/filter.py`                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `AllowedCommand.problems()`, `programGlob` validity                                 | `lib/allowed_command.py`                                                                                                                                                                                                                                                                                                                                                                                                          |
| `ParsedResult`                                                                      | `lib/parsed_result.py`                                                                                                                                                                                                                                                                                                                                                                                                            |
| `Pass`, `Policy`, the six Policy classes                                            | `lib/pass_.py`, `policy.py`, `*_policy.py`                                                                                                                                                                                                                                                                                                                                                                                        |
| `Reason` value objects                                                              | `lib/reason.py`                                                                                                                                                                                                                                                                                                                                                                                                                   |
| The single reason renderer                                                          | `lib/reason_renderer.py`                                                                                                                                                                                                                                                                                                                                                                                                          |
| Escalation transformers (bypass/add-allow)                                          | `lib/escalation_policy.py`                                                                                                                                                                                                                                                                                                                                                                                                        |
| `add-allow-policy` write-side logic                                                 | `lib/add_allow_write.py`, `bin/add-allow-policy`                                                                                                                                                                                                                                                                                                                                                                                  |
| Proposal validation (ask-side refusal + write-side re-check)                        | `lib/proposal_validation.py`                                                                                                                                                                                                                                                                                                                                                                                                      |
| `command-policy:config` skill                                                       | `skills/config/SKILL.md`, `tests/test_skill_drift.py`                                                                                                                                                                                                                                                                                                                                                                             |
| `bypass-policy` runtime (exec's its argv)                                           | `bin/bypass-policy`                                                                                                                                                                                                                                                                                                                                                                                                               |
| Bundled reference parser scripts                                                    | `parsers/` (most are copies of `packages/shfmt-permissions/scripts/parsers/`; the four wrapper parsers — `timeout.py`, `nix.py`, `nix-shell.py`, `xargs.py` — deliberately diverge to speak the `nestedCommands` protocol the old engine does not understand, and must never be re-synced from it; `spawn-claude.py` has no counterpart there at all — the first bundled parser written FOR this engine rather than ported to it) |
| Pure config translation                                                             | `lib/config_migration.py`                                                                                                                                                                                                                                                                                                                                                                                                         |
| `migrate-config` entrypoint + skill                                                 | `bin/migrate-config`, `skills/migrate-config/SKILL.md`                                                                                                                                                                                                                                                                                                                                                                            |
| `find-auto-allowed-command` agent                                                   | `agents/find-auto-allowed-command.md`                                                                                                                                                                                                                                                                                                                                                                                             |
| Per-layer config search/presence record                                             | `lib/layer_presence.py`                                                                                                                                                                                                                                                                                                                                                                                                           |
| `audit-session-policy` + session audit                                              | `bin/audit-session-policy`, `lib/session_audit.py`                                                                                                                                                                                                                                                                                                                                                                                |
| Decision specification                                                              | `tests/test_permission_decisions.py`                                                                                                                                                                                                                                                                                                                                                                                              |
| Bundled parser unit tests                                                           | `tests/test_bundled_parsers.py` (subprocess `run_parser`, ported from `packages/shfmt-permissions/tests/test_new_parsers.py`'s convention, for the four wrapper parsers' own parsing behaviour; `run_parser_describe` covers the describe protocol for all 17 bundled parsers, including a cross-check that each declared `optionsWithValues` member actually produces a non-empty `arguments` list on real output)               |
| cwd-pinning fixture                                                                 | `tests/conftest.py`                                                                                                                                                                                                                                                                                                                                                                                                               |
| Live (old) engine                                                                   | `packages/shfmt-permissions/scripts/analyze-bash-command.py`                                                                                                                                                                                                                                                                                                                                                                      |
| Outcome model rationale                                                             | `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`                                                                                                                                                                                                                                                                                                                                                |
| Unknowable-expansion rules (Flag List G)                                            | `docs/improvements/improvement-20260914-213049-shfmt-golden-corpus-harness.md`                                                                                                                                                                                                                                                                                                                                                    |
