# Improvement 20260919-112214: Per-Argument Knowability for Variables and Substitutions

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-19
- Updated: 2026-09-19
- Plan started: 2026-09-19T11:21:58+02:00
- Plan finished: 2026-09-19T15:09:21+02:00
- Impl started: 2026-09-19T19:12:00+02:00
- Impl finished: 2026-09-19T23:23:24+02:00
- Depends on: 20260918-205740

## This Improvement's Objective

Make command-policy refuse to conclude anything about an argument whose text is only a FRAGMENT of the real runtime
value. Today `lib/allowed_command_policy.py` threads command SUBSTITUTIONS positionally (`_substitution_indices` +
`_substitution_override`) but never threads VARIABLES at all, and the substitution mechanism it does have is itself
incomplete. Three concrete holes, all confirmed by probe against the current engine: (1) a variable-bearing word is
invisible to the unknowability rules entirely, so with the variable declared via `onlyTheseVariables`, `rg safe$HOME`
satisfies a `required ^safe$` filter and `rg --dang$X` slips a `block ^--danger$` filter; (2) the same intra-word
fragment hole exists for SUBSTITUTIONS on the three non-index matchers — with the inner program allow-listed,
`rg safe$(echo x)` ALLOWS against `required ^safe$` for `parameterRegex`, `matchFullParameter` and `positionalArgRegex`,
because the KB's "presence is provable" rule was reasoned about a literal in a SEPARATE word and is unsound when the
literal is only a fragment of the same word; (3) `_substitution_indices` skips any word whose text starts with `-`, so
an option-shaped word carrying unknowable content escapes even the unconditional block rule (`--dang$(echo x)` slips a
block filter). Additionally the index-shift rule is missing for unquoted variables (`rg $X target` keeps a pinned
positional index provable when `$X` may expand to zero or several words), and argument-path containment is checked
against the fragment, so `cat ./sub$ESC`, `cat ./sub/$ESC` and `cat ./a$ESC/b` are all judged contained in the project
when the real path can escape it. The fix replaces the substitution-specific helper pair with one per-argument
KNOWABILITY concept covering variables and substitutions uniformly, decided per matcher type, and extends it to
argument-path containment as a security boundary that must fail closed when containment cannot be proven.

## Context / Why This Exists

**Origin / trigger:** Recommended as a follow-up by the independent review of improvement 20260918-205740. The
reviewer's own words: this is "not a new bug, but it is the ground a future exploit would be built on". It is
pre-existing and syntax-independent — the unquoted forms behaved this way before 20260918-205740 and are untouched by
it.

**Consumer(s) of the output:** The operator's live Bash permission decisions. `command-policy` is ENABLED and deciding
for real on this machine via the PreToolUse hook, so both a false ALLOW and a false DENY land in daily work immediately.

**Adjacent systems already covering part of the need:** `lib/sensitive_paths_policy.py` catches a literal sensitive path
wherever it appears by raw-text substring scan — deliberately out of scope here, it carries its own separate documented
residual gap. `lib/path_resolution.py`'s realpath seam (improvement 20260918-185726) closes the static symlink-escape
gap on the same containment check this improvement makes fail closed; the two compose and neither replaces the other.
`packages/shfmt-permissions/` is the deprecated old engine and must stay behaviourally untouched.

## Proposed Approach

Replace the substitution-specific helper pair (`_substitution_indices` / `_substitution_override` in
`lib/allowed_command_policy.py`) with a single per-argument **knowability** concept that covers variables and
substitutions uniformly, then consume it per matcher type and at the argument-path boundary.

**The invariant being restored:** a matcher compares a pattern against a string it assumes is the COMPLETE argument.
When a word carries content that is unknowable at analysis time — a `ParamExp` or a `CmdSubst`/`ProcSubst` —
`Argument.text` yields only a FRAGMENT of the real runtime value, and any conclusion drawn from that fragment is unsound
in both directions (a `required` filter can be satisfied by a fragment the real value would not match; a `block` filter
can be cleared by a fragment the real value would match). The engine must decline to conclude, not guess.

**Per outcome, the rule is asymmetric — and only "cannot conclude" is added, never "must deny outright":**

- **`block`, any matcher type:** unknowable content anywhere in the invocation defeats the filter. Absence is never
  provable. This generalises today's rule, which already says exactly this but misses option-shaped words.
- **`required`, non-index matchers** (`parameterRegex`, `matchFullParameter`, `positionalArgRegex`, `optionPresent`,
  `optionValue`, `namedValue`): evaluate the matcher against the KNOWABLE arguments only. If the pattern still matches
  using literal evidence alone, presence is genuinely proven and the filter passes — this is what keeps the
  knowledgebase's "presence is provable" rule alive for its real case, a literal in a SEPARATE word
  (`echo --required-flag $(echo safe)`). If the only evidence was a fragment, the filter fails.
- **`required`, index matchers** (`argumentAtIndex`, `positionalArgAtIndex`): keep today's at-or-after shift rule, but
  compute the first unknowable position over variables AND substitutions, and over option-shaped words too. An index
  strictly ahead of the first unknowable stays provable. **Only a word that can change the word COUNT shifts an index**
  — a double-quoted expansion always yields exactly one word, so it does not shift (see the Design Decisions entry on
  word-splitting precision, and the `"$@"` exception in Implementation Notes). A word whose expansion is quoted is still
  a FRAGMENT for the comparison rules above; word-safety and knowability are two independent properties of the same word
  and must not be conflated.
- **External-parser-backed entries** (`commandParser` type `provided`/`command`): no knowable-only re-parse is
  attempted; unknowable content simply defeats a `required` filter for those entries. The re-parse is a second
  subprocess invocation there, and these are the wrapper entries (`nix-shell`, `nix`, `timeout`) where declining to
  conclude is the right default anyway.
- **Argument-path containment** (`_first_path_outside_allowed_prefixes`, gated by `hasNoPathParameters`): an entry
  performing path validation cannot prove containment for an invocation carrying unknowable content, so it does not
  vouch. Treated as a security boundary rather than a pattern assertion — see the Design Decisions entry for why this is
  deliberately the blunt "any unknowable argument" rule rather than a per-path one.
- **`nestedCommand`:** the nested command text is itself reconstructed from fragment texts, so unknowable content makes
  the nested invocation unverifiable and the filter fails closed — consistent with that filter's existing
  fails-closed-with-nothing-to-check posture.
- **An entry restricting no content is still unaffected.** No filters and `hasNoPathParameters` means there is no claim
  to invalidate, so a variable-bearing or substitution-bearing invocation stays ALLOW. This is the knowledgebase rule
  that keeps the change from collapsing into "any variable denies".

**What this does NOT change:** deny stays routing, not prevention. Every newly-denied invocation gets the ordinary
deny+hint and the unconditional `command-policy:find-auto-allowed-command` pointer, with `bypass-policy` as the
deliberate escalation. No new config knob is introduced — the decision model says the config expresses what IS allowed
and can no longer express leniency, so "I accept that filters cannot see through this variable" is deliberately NOT made
configurable.

## Affected Components

**Files:**

- `packages/command-policy/lib/allowed_command_policy.py` — `_substitution_indices` (line ~363) and
  `_substitution_override` (line ~385) are replaced by the knowability concept; `_entry_rejection_reason` (line ~152),
  `_filter_passes` (line ~272) and `_first_path_outside_allowed_prefixes` (line ~187) are its consumers.
- `packages/command-policy/lib/` — one NEW small module for the knowability value object (name to be settled during
  implementation; it is a value object in the same style as `match_outcome.py` / `reason.py`, not a helper bag).
- `packages/command-policy/tests/test_permission_decisions.py` — the decision specification; new cases for both
  directions.
- `packages/command-policy/tests/test_allowed_command_policy.py` — unit-level coverage of the new value object and its
  per-matcher-type consumption.
- `docs/knowledgebase/command-policy-decision-model.md` — the "What the Engine May Not Conclude From Text It Cannot See"
  section states the rules being corrected and must be updated in the same change.

**Classes/Functions:**

- `AllowedCommandPolicy._entry_rejection_reason`
- `AllowedCommandPolicy._filter_passes`
- `AllowedCommandPolicy._first_path_outside_allowed_prefixes`
- `_substitution_indices` / `_substitution_override` (both removed, superseded)
- `Argument` (`lib/statement.py`) — read-only consumer of its existing `referenced_variables` / `contains_substitution`
  fields; **no change to `Argument.text` and no new `literal_text` accessor**

**Modules:**

- `packages/command-policy`

## Implementation Notes

**The information already exists per-argument; nothing new needs parsing.** `Argument` (`lib/statement.py:223`) already
carries both `contains_substitution` (bool) and `referenced_variables` (frozenset of names), populated per word by
`Argument.from_word`, and both already recurse through `DblQuoted` so `$HOME` / `"$HOME"` / `${HOME}` behave
identically. `_first_disallowed_variable` currently unions `referenced_variables` across all arguments and then discards
the positional information. The whole defect is that this per-argument signal is never consumed per-argument.

**Why `onlyTheseVariables` is not the grant that covers this.** Declaring a variable vouches for WHICH names may be
referenced. It says nothing about the VALUE, which is what a filter actually inspects. The two are separate grants, and
this improvement keeps them separate — see the Design Decisions entry.

**The parser boundary is where the positional link is lost, and this constrains the design.**
`DefaultParser.parse(arguments)` (`lib/default_parser.py:30`) receives plain STRINGS —
`argument_texts = [argument.text for argument in arguments]`, built in `_entry_rejection_reason` — so by the time
`ParsedResult.paths_for_validation` exists, every tie back to the originating `Argument` is gone. The implementation
must therefore compute knowability from `arguments` in `_entry_rejection_reason` (where both forms are still in hand)
and pass it down, exactly as `substitution_indices` is passed into `_filter_passes` today. **Do not try to correlate
knowability back to a parsed path by string matching** — `paths_for_validation` holds resolved absolute paths, not the
original argument text.

**The dash-skip is a real second bug in the existing substitution rule, not a stylistic detail.**
`_substitution_indices` does `if argument.text.startswith("-"): continue`, so a word like `--dang$(echo x)` (text
`--dang`) is never considered, `(None, None)` is returned, no override applies, and even the unconditional `block` rule
is skipped. Probe-confirmed: `--dang$(echo x)` currently slips a `block` filter. The replacement must consider every
argument for the "is anything unknowable present" question, while still using the dash heuristic only for the two INDEX
schemes (where option-vs-positional counting genuinely matters).

**An unquoted expansion can yield zero, one, or many words — including when it has a literal prefix.** `safe$HOME` with
`HOME="a b"` splits into two words. So a literal prefix does NOT make a word shift-safe; only quoting does. See the
Design Decisions entry for how far this improvement goes on quoting fidelity.

**Running the tests: `nix-shell` is itself denied by command-policy right now.**
`cd packages/command-policy/tests && nix-shell --run pytest` — the command the project CLAUDE.md documents — is DENIED,
because the entry carries a `nestedCommand` filter and the bundled `parsers/nix-shell.py` does not populate the
`nestedCommands` channel (the gap the knowledgebase already tracks for the migrated reference parsers).
`python3 -m pytest` does not work either (pytest is not on the bare interpreter's path). The working route is the
deliberate escalation: `cd packages/command-policy/tests && bypass-policy nix-shell --run "pytest -q"`. This is an
environment fact the implementer will hit in the first minute; it is not caused by this improvement and must not be
"fixed" as part of it.

**Verify engine changes by driving this working tree's `lib/` directly — NEVER by seeing whether your own Bash call was
approved.** The PreToolUse hook deciding this session's commands runs from the INSTALLED PLUGIN CACHE
(`~/.claude/plugins/cache/vonaffenfels-dev-tools/command-policy/<version>/`), which only refreshes on a plugin reinstall
keyed to a `marketplace.json` version bump. Editing `packages/command-policy/` therefore changes nothing about what the
live hook allows, and a landed, fully-tested fix can appear not to work purely because the cache still serves the
pre-fix version. The planning probes under `docs/improvements/experiments/variable-positional-threading/` already do
this correctly — `sys.path.insert` on `packages/command-policy/lib`, then `Config.from_dict(...).decision_for(command)`
— so every measurement in this file is of the working tree, not the cache. Keep that method.

**Verified baselines, measured 2026-09-19 — the brief's stated baseline is stale.** `packages/command-policy/tests` is
**663 passed, 0 failed**, NOT "634 passed with exactly two pre-existing failures". The two xargs-parser failures the
brief said must stay red (`test_a_nested_command_filter_composes_with_other_filters_across_entries`,
`test_propagation_does_not_see_operands_arriving_on_stdin`) are already green. **Therefore ANY failure at all is this
improvement's** — the allowance the brief granted no longer applies. `packages/shfmt-permissions/tests` is **751
passed**, matching the brief, and must stay untouched.

**Out of scope, settled, do not re-open:** `Argument.text`'s literal-text recovery merge (operator decision from
20260918-205740 — do NOT reintroduce a separate `literal_text` accessor); `lib/sensitive_paths_policy.py` and its
documented substring residual gap; the realpath symlink seam in `lib/path_resolution.py` from 20260918-185726. No new
config knob is added — the decision model forbids expressing leniency in config.

**Quotedness is recoverable from the AST, but `Argument` does not expose it yet.** Probe-confirmed: `Argument`'s only
fields today are `text`, `contains_substitution`, `referenced_variables` — there is no quotedness and no access to the
raw `Parts`. The signal must therefore be computed in `Argument.from_word` and carried as a NEW field, exactly the way
`contains_substitution` already is. The correct test is per-PART nesting, not the word's outermost shape: an expansion
counts as word-safe only when a `DblQuoted` ancestor encloses THAT part. Probe results — `safe"$X"` word-safe, `"a b"$X`
NOT word-safe, `"safe$X"` word-safe, `safe$X` NOT word-safe. Single-quoted content (`'literal$X'`) produces no expansion
part at all and is fully knowable, which `referenced_variables` already gets right.

**The `"$@"` exception — quoted does NOT always mean one word.** `"$@"` and `"${arr[@]}"` expand to MULTIPLE words
despite being double-quoted, so the naive nesting rule would wrongly call them word-safe (probe-confirmed: it does). The
implementation must exclude them. The distinguishing AST fields, measured: `$@` is a `ParamExp` with
`Param.Value == "@"`; `${arr[@]}` is a `ParamExp` with `Param.Value == "arr"` and an `Index` node whose literal value is
`@`. `"$*"` (`Param.Value == "*"`) genuinely IS one word and stays word-safe. Getting this wrong RELAXES the engine, so
it needs its own test.

**The knowable-only rule also REMOVES an existing class of false denial, which is a second reason to prefer it over a
blunt "any unknowable defeats the filter".** Today an unknowable word contributes the empty string to the joined text
the `parameterRegex` / `positionalArgRegex` matchers search, so `rg safe $HOME` against `required ^safe$` joins to
`"safe "` and DENIES even though the literal `safe` is present and provable in its own word (probe-confirmed,
`probe_narrow_vs_broad.py` section 2). Dropping unknowable arguments before the match — rather than letting them
contribute `""` — makes that case correctly ALLOW. Add a test for it, since it is a behaviour change in the permissive
direction and must be deliberate rather than incidental.

**One newly-ALLOWED shape, and it is sound.** Because the shift rule becomes word-count-aware, a double-quoted
substitution (`echo "$(echo one)" expected-second` against a pinned index) would now be allowed where today every
substitution shifts. That is correct shell semantics, not a regression — but it is the one place this improvement
relaxes rather than tightens, so it deserves an explicit test saying so. No existing test covers it (every current
substitution-shift case uses an unquoted `$(...)`), so nothing in the suite changes meaning silently.

**Testing Strategy:** TDD (Red-Green-Refactor), as required by the global project conventions, with the additional
NON-VACUOUS bar the brief sets: every new test must be run against pre-fix code and observed to FAIL for the right
reason before the fix lands. Record the red counts.

### Observed during exploration

Recorded so they are not silently lost. **Default action for each is to leave it alone** — none is in this improvement's
scope, and none should be folded in.

- **`explain-policy` is not allow-listed, which makes the `find-auto-allowed-command` skill circular.** Every non-empty
  deny reason ends with an unconditional pointer to `command-policy:find-auto-allowed-command`, whose entire documented
  procedure is "run `bin/explain-policy` to read the live rendered config". But `explain-policy` is itself denied by the
  live config (`no allowedCommands entry vouches for: explain-policy`), so following the hint produces a second denial
  and the caller has nowhere to go but `bypass-policy`. The same is true of the other user-facing entrypoints
  (`bypass-policy` aside, which works because it is recognised by the escalation transformer rather than by an
  allowedCommands entry). Hit twice in this session.
- **`nix-shell` cannot run at all under the live config.** Its entry carries a `nestedCommand` filter while the bundled
  `parsers/nix-shell.py` publishes nothing on the `nestedCommands` channel, so the filter fails closed on every
  invocation. The knowledgebase already tracks this as a known migration gap for the bundled reference parsers; what is
  new is that it now blocks the project's own documented test command.
- **`improvement-plan-context` is not allow-listed either**, so `/improvement:plan`'s own Step 0 helper is denied on
  first use and has to be run as `python3 packages/improvement/bin/improvement-plan-context`.
- **`resolve_improvement_file` crashes on a long argument** (`packages/improvement/lib/improvements.py:74`) — a bare
  `Path(arg).exists()` raises `OSError: [Errno 36] File name too long` instead of returning False. Now owned by the
  separate plan-skill argument-handling improvement, recorded here only because this session is where it surfaced.

**Pattern-enforcement passes (Step 2.5/2.5b) were not run:** every affected file is Python, and the available enforcers
(`patterns:anti-pattern-detector`, `patterns:pattern-enforcer`, `patterns:react-anti-pattern-detector`) cover PHP and
React only. Recorded rather than silently skipped.

## Implementation Notes (added during implementation)

**The crux, decided:** `onlyTheseVariables` and filter soundness are two separate grants, exactly as planned. No new
config knob was added. `ArgumentKnowability` (new module, `lib/argument_knowability.py`) is the single place that
combines `Argument.contains_substitution` / `.referenced_variables` / the new `.word_safe` field into three decisions:
`defeats_absence_proof()` (the `block` rule, every argument, dash-prefixed included), `knowable_texts()` (the
`required`-non-index rule, a second pure re-parse over only the fully-knowable arguments), and
`first_shifting_position(scheme: IndexScheme)` (the `required`-index rule, keeping the dash heuristic for
option-vs-positional counting exactly as `_substitution_indices` did).

**False-denial impact, measured:** zero against the operator's live `~/.claude/command-policy.json` (59 entries, none
declaring `onlyTheseVariables`, confirmed both at planning time and again by re-running the probes post-fix). Inside the
test suite itself the impact was real and had to be handled deliberately: argument-path containment now fails closed for
ANY entry without `hasNoPathParameters` whenever the invocation carries unknowable content — the design explicitly
rejected a narrower per-detected-path refinement (unsound: a fragment that doesn't look like a path can still be one at
runtime, e.g. bare `$ESC`), so this is deliberately the blunt per-command rule. That widening broke several existing
spec/unit tests that used a bare variable- or substitution-bearing entry without `hasNoPathParameters` and expected
ALLOW (their real subject was a filter or the substitution-recursion mechanism, not path containment) — each was updated
to add `hasNoPathParameters: True`, with an inline note explaining why, so the test again exercises the mechanism it is
named after rather than accidentally denying via the newly-tightened path check.

**RED counts, by batch (all against pre-fix `lib/`, verified via `sys.path`-injected `Config.from_dict`, never via the
installed plugin cache):**

- `Argument.word_safe` (`TestArgumentWordSafety`, `tests/test_statement.py`): 17 of 17 failed with `AttributeError`
  before the field existed.
- `ArgumentKnowability` (`tests/test_argument_knowability.py`): the whole module failed to import
  (`ModuleNotFoundError`) before `lib/argument_knowability.py` existed — the correct RED state for a not-yet-created
  module; once created, all 15 unit tests passed immediately (pure combination logic over hand-built `Argument`
  fixtures, no engine wiring needed).
- Decision-spec cases (`tests/test_permission_decisions.py`, the new "Per-argument knowability" section): 26 of 28
  failed pre-wiring; the 2 that already passed are legitimate already-correct guards (`hasNoPathParameters` with no
  filters stays ALLOW; single-quoted `'literal$X'` stays fully knowable) — pinned as regressions, not new behaviour. One
  test ("the one newly-ALLOWED shape", a double-quoted substitution not shifting a pinned index) initially passed
  vacuously pre-fix due to a test-construction bug: a redundant second `"echo"` allowedCommands entry double-vouched for
  the outer invocation regardless of what the entry-under-test's own filter concluded. Caught by re-checking why a
  "must-change" case was green pre-fix, fixed by removing the redundant entry, then confirmed genuinely RED.
- `test_an_external_parser_is_not_re_invoked_for_a_knowable_only_reparse` (`tests/test_allowed_command_policy.py`):
  confirmed RED pre-fix by temporarily swapping in the pre-wiring `allowed_command_policy.py` from git history
  (`ad6a8fd^`) and re-running just this test — failed on the decision assertion (`matches()` was `False`/ALLOW instead
  of the correct `True`/DENY), since the old engine had no knowable-only re-parse mechanism for ANY filter type and so
  never defeated this fragment at all.

**Final state:** `packages/command-policy/tests` 724 passed, 0 failed (663 baseline + 61 new/updated).
`packages/shfmt-permissions/tests` unchanged at 751 passed.

## Reopened 2026-09-19: independent review failed the path-containment widening

**The defect.** `_first_path_outside_allowed_prefixes` failed closed on ANY entry lacking `hasNoPathParameters` whenever
ANY argument anywhere in the invocation was unknowable — even when `parsed.paths_for_validation` was completely EMPTY,
i.e. the entry's own parser found no path candidate at all to protect. The "zero false-denial cost" measurement recorded
above only covered the VARIABLE axis (the operator's live config has zero `onlyTheseVariables` entries); it never
covered the SUBSTITUTION axis, where the live config sets `commandSubstitutionResponse: "via-allowed-commands"` (the
ordinary, everyday shape) and carries `hasNoPathParameters` on only 3 of 60 entries. Measured regression against the
real merged config (`~/.claude/command-policy.json` + `.claude/command-policy.json`), reproduced with a
`sys.path`-injected `Config.from_dict` against the working tree before this fix (never against the installed 0.3.0
plugin cache, which predates this whole improvement): all eleven of `cd $(git rev-parse --show-toplevel)`,
`ls $(project-root)`, `rg foo $(project-root)`, `echo $(date)`, `echo $(git rev-parse --show-toplevel)`,
`git add $(git ls-files -m)`, `git commit -m "$(echo msg)"`, `head -20 $(list-improvements ready-to-implement)`,
`improvement-timings $(project-name-slug)`, `wc -l $(rg -l foo)`, and `cleanup-claude $(project-name-slug)` denied via
`ArgumentPathOutsideAllowedPaths(path='<unresolvable>')`, even though none of their allowedCommands entries carry a
`paths`/`positionalArgAtIndex`/etc. path-relevant filter that the substitution could have defeated.

**The fix, adjudicated by the operator (see the revised "Argument-path containment next to unknowable content" Design
Decision above):** narrow the fail-closed gate to require an actual path candidate (`parsed.paths_for_validation`
non-empty), not merely "some argument somewhere is unknowable." Implemented as a single early-return in
`_first_path_outside_allowed_prefixes` (`allowed_command_policy.py`) — see that method's own updated docstring for the
full reasoning, including why "a path candidate exists" and "an argument occupies a path position" collapse into the
same fact for every parser this engine has (Default, Structured, the bundled `git` parser: all three require a non-empty
literal value before adding anything to `paths_for_validation`).

**Re-measured against the real merged config, all eleven, post-fix:**

| Command                                            | Result   | Reason                                                            |
| -------------------------------------------------- | -------- | ----------------------------------------------------------------- |
| `cd $(git rev-parse --show-toplevel)`              | ALLOW    | —                                                                 |
| `ls $(project-root)`                               | ALLOW    | —                                                                 |
| `rg foo $(project-root)`                           | ALLOW    | —                                                                 |
| `echo $(date)`                                     | ALLOW    | —                                                                 |
| `echo $(git rev-parse --show-toplevel)`            | ALLOW    | —                                                                 |
| `git add $(git ls-files -m)`                       | **DENY** | `FilterRejected(git, namedValue)` — unrelated to path containment |
| `git commit -m "$(echo msg)"`                      | **DENY** | `FilterRejected(git, namedValue)` — unrelated to path containment |
| `head -20 $(list-improvements ready-to-implement)` | ALLOW    | —                                                                 |
| `improvement-timings $(project-name-slug)`         | ALLOW    | —                                                                 |
| `wc -l $(rg -l foo)`                               | ALLOW    | —                                                                 |
| `cleanup-claude $(project-name-slug)`              | ALLOW    | —                                                                 |

**CORRECTION (second fix round): the two git denials below are labelled as pre-existing and unrelated. They are
neither.** Measured by materialising `lib/` at each ref and deciding against the real merged config:
`git add $(git ls-files -m)`, `git commit -m "$(echo msg)"` and `git add $(echo README.md)` (the third regresses
identically and went unrecorded) all decided **ALLOW** at `96204f3` and still ALLOW at `ad6a8fd^`; all three deny from
`ad6a8fd` onward — this improvement's own commit. The denying rule, `AllowedCommandPolicy._required_filter_passes`'s
`if not isinstance(parser, _PURE_PARSER_TYPES): return False` external-parser branch, was introduced by that commit. The
rule is sanctioned and stays; only the label was wrong. Worth noting that the MECHANISM also moved: at `ad6a8fd` these
denied via `ArgumentPathOutsideAllowedPaths(path='<unresolvable>')`, i.e. the path-containment widening, and they deny
today via `FilterRejected(git, namedValue)`. Both were introduced by this improvement, so "pre-existing" was never true
of either.

Nine of eleven now allow. The two that still deny do so for a reason **this fix deliberately does not touch**: `git`
uses a `provided` (external) parser, and the "Unknowable content under an external parser" Design Decision (unchanged,
still correct, still in scope-fence) says such entries get no knowable-only re-parse for a `required` filter — ANY
unknowable content anywhere in the invocation defeats git's `namedValue` subcommand filter outright, regardless of
whether that content occupies a path position. This is filter-side behaviour explicitly protected by "ALL FILTER-SIDE
TIGHTENING STAYS," not a path-containment question, so it is correctly untouched. **The operator's own guessed split
(cd/ls/head/wc/git-add deny, the rest allow) was wrong for `git add` and right for the other four** — verified rather
than assumed, per the reopening brief's own instruction.

**CORRECTION (second fix round): the Task-2 paragraph below is inaccurate on both of its headline claims.** There were
**thirteen** bent fixtures, not nine — four more survived in `tests/test_allowed_command_policy.py`
(`test_every_rejecting_entry_contributes_its_own_reason_when_none_vouches`,
`test_an_entry_vouches_for_a_declared_variable_reference`,
`test_a_block_filter_is_defeated_by_any_substitution_present`,
`test_a_non_index_required_filter_is_not_defeated_by_a_substitution`), and two of those carried docstrings describing
the by-then-superseded too-broad rule as current. And "no test needs a false claim to pass" was true only of the rule in
force at the time; see the second fix round's own Task-2 treatment below, where it stops being true and is resolved on a
different principle rather than by restoring flags.

**Test restoration (Task 2).** All nine pre-existing tests that had `hasNoPathParameters: True` bolted on by the
original leaf turned out to be restorable to their true bare-entry form once the fix landed — not just the three named
explicitly in the reopening brief. Traced by hand and confirmed by the suite: every one of the nine uses either a pure
content-free substitution (`$(echo safe)`, `$(echo one)`, `$(echo tail)`, `$(echo just-one-argument)`) or a content-free
variable (`$HOME`) as its ONLY unknowable argument, and none of their other literal arguments (`expected-first`,
`--required-flag`, `"--json"`, `expected`) look path-shaped or happen to exist as files in the test cwd — so
`paths_for_validation` is empty for all nine regardless of the fix, and `hasNoPathParameters` was never actually a true
factual claim these tests needed. All nine restored;
`test_a_double_quoted_flag_ahead_of_a_substitution_ does_not_miscount_positions` (improvement-20260918-205740's own
acceptance test for Finding 4) now passes again under its ORIGINAL fixture with no `hasNoPathParameters`, confirming the
narrowed rule is not still too broad.

**New test coverage added for the previously-blind substitution axis:**
`test_argument_path_containment_fails_closed_next_to_a_substitution_fragment_in_a_path_operand` (`cat ./sub$(echo x)`,
must still deny — the substitution mirror of `PATH_CONTAINMENT_FRAGMENT_CASES`) and
`test_argument_path_containment_allows_a_substitution_that_is_not_a_path_operand` (`echo $(date)`, must allow — this
fix's own acceptance case, the exact live-config shape). Both confirmed RED pre-fix (the "allow" case failing with
`ArgumentPathOutsideAllowedPaths`, the "deny" case already passing pre-fix since the old blunt rule over-denied it too)
and GREEN post-fix. **The second `allow` case no longer exists:** the second fix round replaced it with
`test_a_substitution_into_a_default_parser_slot_is_a_path_operand`, which asserts the opposite verdict for the same
command. The first case survives unchanged and still denies.

**Task 3, hasNoPathParameters adjudicated: stays a FACTUAL CLAIM, not a waiver — no code or schema change needed.**
`entry.has_no_path_parameters` still means exactly what it meant before this whole improvement: "this entry's own
argument-path containment check should be skipped entirely," unconditionally, because the entry never takes a
path-shaped argument at all. That flag's own gate in `_entry_rejection_reason`
(`if not entry.has_no_path_parameters: ...`) is untouched by this fix. What changed is that the ORIGINAL widening made
asserting it look like it was ALSO functioning as an unknowability waiver, because with the too-broad rule,
`hasNoPathParameters: True` was the only way to stop an unrelated unknowable argument from tanking an unrelated
filter-under-test via a path-containment side effect. That was never a real second meaning of the flag — it was a
symptom of the bug, and the nine bolted-on `hasNoPathParameters: True` annotations were quietly-false factual claims (a
bare `echo`/`rg`/`cat` entry does not really claim to take no path parameters) that happened to be harmless only because
the over-broad rule made them functionally irrelevant to path candidates that never existed. With the narrow fix, no
test needs a false claim to pass, so all nine are restored to a claim-free (bare) form. The NEW tests this improvement
adds for filter-mechanism isolation (`VARIABLE_FRAGMENT_REQUIRED_CASES` and siblings, all still carrying
`hasNoPathParameters: True`) are a DIFFERENT, legitimate use of the same flag: those entries genuinely want to test one
filter mechanism in isolation from path containment, and the flag's documented, honest meaning ("skip path containment
for this entry") is exactly the tool for that — left untouched, this is not scope creep, it is Task 2's own fixture
review correctly finding those fixtures fit for purpose.

**Task 4, the deny reason, resolved by deletion rather than rewording.**
`ArgumentPathOutsideAllowedPaths(path= '<unresolvable>')` and its `ArgumentKnowability.first_unknowable_text()` support
are now UNREACHABLE: the narrowed `_first_path_outside_allowed_prefixes` returns `None` (no denial at all) the instant
`paths_for_validation` is empty, so the branch that used to manufacture `'<unresolvable>'` as a reason can no longer be
reached — there is no longer a "denies but can't name a path" state to word better. Removed the dead branch, the
now-unused `first_unknowable_text()` accessor, and its two unit tests (`TestFirstUnknowableText` in
`tests/test_argument_knowability.py`) rather than leaving speculative dead code the way
`_substitution_indices`/`_substitution_override` were NOT left behind when this improvement first superseded them.

**Task 5, version bump:** `packages/command-policy/.claude-plugin/plugin.json` and the root
`.claude-plugin/ marketplace.json` entry both bumped `0.3.1` -> `0.3.2` in this same change, so the operator's plugin
cache refresh picks up the fix (the operator was deliberately holding at 0.3.0 until this landed).

**Baseline re-confirmed 2026-09-19 (reopening):** `packages/command-policy/tests` was 724 passed, 0 failed before this
reopening's edits (matching the prior completion's final state exactly), and is 724 passed, 0 failed again after (2
tests removed - `TestFirstUnknowableText`'s pair - and 2 added - the substitution-axis pinning cases - net zero;
`packages/shfmt-permissions/tests` re-confirmed unchanged at 751 passed.

## Reopened 2026-09-19 (second fix round): whatever cannot be ruled out is a path

An independent review failed the first fix round. Rather than patch it again, the operator replaced the rule: **the
default parser treats EVERYTHING as a path candidate. If the engine cannot rule out that an argument is a path, it IS a
path candidate. No knowledge means no exemption.**

**Step 0, measured before any code changed, because it decided the size of the change.** The question was whether the
default parser already made every non-empty literal a path candidate. It did not: `_detect_paths` admitted only
positionals that looked path-shaped (start with `/`, `~`, `.`, or contain `/`) or that the injected context said
existed, and dash-prefixed words never reached it at all — `DefaultParser.parse` routed them to `options`, and detection
ran only over `positionals`. So this was the larger blast radius, requiring the PARSER to change rather than the
unknowability layer to be extended, and the operator accepted that knowingly before implementation began.

**The literal twin, measured on the orchestrator's challenge and confirmed.** If dash-prefixed words never reach path
detection, a literal path escape must already exist with no substitution involved. It did: `ls --color=/etc`,
`ls --color=/etc/passwd` and `rg --file=/etc/passwd pattern` all **ALLOWED** against the real merged config at
`96204f3`..HEAD-before-this-round. So the four substitution cases the operator wanted closed were the flavoured form of
a hole that was already open to a plain literal, and this round closes a class rather than a trick.
(`ls --color=/etc/shadow` denied, but only via the separate `sensitivePaths` substring policy — not via containment.)

**Why the previous round's security rationale was false, stated plainly.** It held that denying a pure substitution
"protects nothing" because a substitution contributing no literal text can produce no path candidate. That conflates "no
path is visible to the parser" with "no path is there". `echo` is allow-listed and produces arbitrary strings, so one
allow-listed string-producer was enough to hand any path-taking entry an absolute path at runtime. Its supporting claim
— that every parser requires a non-empty literal before adding to `paths_for_validation` — was also simply untrue:
`parsers/cat.py` and `parsers/chmod.py` call `resolve_path("")`, which returns the cwd, so they emit a candidate for an
EMPTY argument. That is exactly why the first fix's non-emptiness gate gated nothing for those entries. Both passages
are corrected in place above, in the code docstrings, and in the knowledgebase.

**What was built.** Two changes, one concept.

- `lib/default_parser.py` — `paths_for_validation` now carries EVERY argument, options included. For an option-shaped
  `--name=value` word the candidate is `value` alone: resolving the whole word would bury an absolute value under the
  project root and read as contained (`--color=/etc` → `<project>/--color=/etc`), which is precisely how the literal
  form of the hole stayed open. `paths_for_filtering` deliberately does NOT follow — it feeds `PathsFilter`'s `exactly`
  set-membership semantics, where a surplus entry is a wrong member rather than a spare check. That is the per-consumer
  divergence `ParsedResult` split the two fields for, now actually exercised.
- `lib/allowed_command_policy.py` — containment asks two questions instead of one:
  `_first_path_outside_allowed_prefixes` (every NAMED path must be contained) and
  `_an_unknowable_argument_occupies_a_path_operand` (no unknowable value may sit in a slot the entry's parser calls a
  path). The second re-parses with a marker appended to each unknowable argument
  (`ArgumentKnowability.texts_with_unknowable_marked`) and asks whether any resulting path carries it.

**Why a marker probe rather than correlating text.** This file's own Implementation Notes forbid correlating knowability
back to a parsed path by string matching, and that constraint is honoured: the marker is injected by the engine and
never read from the invocation. Matching a fragment's own text would prove nothing, since `paths_for_ validation` holds
resolved absolute paths and a fragment is frequently the empty string — which resolves to the cwd and is
indistinguishable from a real argument naming `.`. The marker is APPENDED rather than substituted so the word keeps the
shape the parser reasons about (`--color=$(...)` stays option-shaped, `./sub$ESC` keeps its relative prefix). Position
within the word is deliberately not modelled: the question is only whether the SLOT is a path operand, never where
inside it the unknown sits.

**A per-slot mechanism was required, not chosen for elegance.** The blunt "any unknowable argument denies once a
candidate exists" rule cannot deliver the operator's other-direction requirement: `chmod $(echo 755) bin/x` produces a
real path candidate (`bin/x`), so the blunt rule denies it, while the operator requires ALLOW because chmod's parser
knows slot 0 is a mode. Correlation is the only way to tell those apart.

**A new Reason, `UnknowablePathArgument(program)`.** `ArgumentPathOutsideAllowedPaths` would claim a path was resolved
and found outside the boundary; here no path can be named at all. Different fact, different fix, so a distinct reason
rather than the placeholder path (`'<unresolvable>'`) the first round rightly deleted. Carrying only the program is
deliberate — naming the fragment would imply the engine knows more about the argument than it does.

**Measured outcomes against the real merged config (never the installed 0.3.0 plugin cache).**

Closed, all four ALLOW before and DENY after: `ls $(echo /etc)`, `cat $(echo ~/.ssh/id_rsa)`,
`rg -f $(echo /etc/passwd) pattern`, `ls --color=$(echo /etc)`. Plus the literal twin: `ls --color=/etc`,
`ls --color=/etc/passwd`, `rg --file=/etc/passwd pattern`.

Fixed in the permissive direction, DENY before and ALLOW after: `grep $(echo mypattern) README.md` (pattern slot) and
`chmod $(echo 755) bin/x` (mode slot). The incoherence this removes — `head -5 $(echo README.md)` allowing while
`cat -n $(echo README.md)` denied, same intent, opposite verdicts by accident of which entry had a parser — is gone;
both now deny, and the verdict follows the parser's actual knowledge rather than its mere presence.

All eleven previously-regressed commands, verified rather than assumed, all **DENY**: `ls $(project-root)`,
`cd $(git rev-parse --show-toplevel)`, `rg foo $(project-root)`, `head -20 $(list-improvements ...)`,
`wc -l $(rg -l foo)`, `cat $(echo README.md)`, `echo $(date)`, `echo $(git rev-parse --show-toplevel)`,
`improvement-timings $(project-name-slug)` and `cleanup-claude $(project-name-slug)` via `UnknowablePathArgument`;
`git add $(git ls-files -m)` and `git commit -m "$(echo msg)"` via the unrelated `FilterRejected(git, namedValue)` rule.
None of the operator's live entries declares `hasNoPathParameters`, and their config was NOT edited — the denials are
the rule working as decided. The usability answer the operator recorded: `project-root` is itself allow-listed, so the
caller runs it, reads the real path, and runs `ls /that/literal/path` — two auto-approved commands, both fully
statically checkable, no convenience-shaped hole.

**Literal-side regression sweep: zero.** Fifty-eight everyday literal invocations drawn from the live config (reads,
greps, git, npm/composer, the project's own bin helpers, python/pytest) were decided before and after. One denied —
`git rev-parse --show-toplevel`, `FilterRejected(git, namedValue)` — and it was confirmed to deny identically at HEAD by
materialising a pristine `lib/` from git and re-running, so it predates this round. Most non-path-shaped literals become
candidates that resolve project-relative, stay contained, and still allow, exactly as predicted.

**Task 2 under the new rule: the four surviving bent fixtures could NOT simply be restored, and that is the rule working
rather than failing.** The reviewer stripped the flag from all four and saw 29 passed — true under the rule in force
then, and no longer true. Under the new rule an `echo` entry with a substitution has that substitution sitting in a path
operand, so all four need `hasNoPathParameters`. The distinction that resolves this is the operator's own: the flag must
be a TRUE factual claim, never a waiver. All four are `echo` entries, and `echo` genuinely takes no path operands, so
the claim is factual and is now load-bearing and honest rather than decorative. All four docstrings were rewritten,
including the two describing the superseded rule as current.

A single principle was then applied to every `hasNoPathParameters` in the suite, since scattering false claims would
undermine the very meaning this round restores:

- Where the flag is what MAKES a case ALLOW, the program must genuinely take no path operands. Three allow-expecting
  fixtures declared it on `rg`, which does take paths; those moved to `echo` (`echo safe $HOME`, `echo anything` /
  `echo safe$HOME`, `echo 'safe$X'`). Same mechanism, same parser, claim now true.
- Where a case asserts a DENY, the flag only isolates which objection fires first and cannot manufacture the verdict.
  Those keep `rg`, and the operator's named must-still-deny shapes (`rg safe$HOME`, `rg "safe$HOME"`, `rg --dang$X`,
  `rg safe$(echo x)`, `rg --dang$(echo x)`) are left verbatim.

**Existing tests that legitimately changed meaning, adjudicated rather than flagged into submission (8 failures, each
resolved on its merits):**

- `test_a_bare_word_positional_is_a_path_only_when_the_injected_context_says_it_exists` — asserted the exact heuristic
  the new rule removes. Rewritten as
  `test_a_bare_word_is_a_validation_candidate_whether_or_not_the_context_says_it_exists`, now pinning BOTH fields so the
  validation/filtering divergence is explicit. Its neighbour was re-pointed at `paths_for_filtering`, because asserting
  the injected predicate against `paths_for_validation` would now pass regardless of what the predicate returned — it
  would have kept its name while proving nothing.
- Five `echo` spec cases whose subject is a filter or the substitution knob — given the honest flag, with docstrings
  saying why the claim is true.
- `test_a_double_quoted_flag_ahead_of_a_substitution_does_not_miscount_positions` (20260918-205740's own acceptance test
  for Finding 4) — its PROGRAM moved from `rg` to `echo`. The mechanism under test is the parser's dash-classification
  of a double-quoted word and the index counting that follows, which is program-independent; but the fixture also needs
  an entry that may legitimately carry a substitution, and `hasNoPathParameters` on an `rg` entry would have been a
  false claim written to keep a test green. The `rg` shape's real verdict is now pinned alongside it by
  `test_the_same_shape_denies_for_a_program_that_really_does_take_paths`, so the trade is visible.
- `test_argument_path_containment_allows_a_substitution_that_is_not_a_path_operand` — the first fix round's own
  acceptance case, asserting the opposite of what is now correct. Replaced by
  `test_a_substitution_into_a_default_parser_slot_is_a_path_operand`, whose docstring records what was refuted and why.

**New coverage.** `SUBSTITUTION_REACHING_A_PATH_OPERAND_CASES` (the four closed leaks),
`LITERAL_PATH_INSIDE_AN_OPTION_CASES` (the literal twin), the three sanctioned routes
(`test_an_honest_has_no_path_parameters_earns_a_substitution`,
`test_a_parser_that_classifies_the_slot_as_a_mode_earns_a_substitution`,
`test_a_pattern_slot_is_not_a_path_operand_even_when_its_value_is_unknowable`), the guard that a classifying parser
still denies its REAL path slot (`test_the_same_parser_still_denies_a_substitution_in_its_real_path_slot` —
`chmod 755 $(echo bin/x)`), and `test_an_unknowable_path_operand_is_reported_as_its_own_fact` pinning the new Reason.
Four `MATCHING_BRANCH_COVERAGE` entries added; both manifest guard tests stay green.

**Suites:** `packages/command-policy/tests` 737 passed, 0 failed (724 baseline + 13 net).
`packages/shfmt-permissions/tests` unchanged at 751 passed.

### Observed during implementation (second fix round)

Recorded, deliberately NOT acted on.

- **`StructuredParser` keeps the same hole the default parser just lost.** Its `_detect_path_heuristic` fallback for
  positionals not named in `pathPositionals` is the identical "does it look path-shaped" guess, so an unknowable value
  in an undeclared slot is exempted there exactly as it used to be everywhere. Left alone on scope discipline: the
  operator's rule names the DEFAULT parser, and the live config uses zero structured parsers, so there is no live
  exposure. Worth its own decision — the honest reading is that `pathPositionals` declares which positionals ARE paths
  and rules nothing out, which is why the heuristic fallback exists at all.
- **`echo "some message mentioning /tmp/foo"` still allows, and the reason is unrelated to this round.** The "contains a
  slash" heuristic does fire on it, but the whole string is then resolved as a RELATIVE path, becoming
  `<project>/some message mentioning /tmp/foo` — trivially contained. Explicitly out of scope per the orchestrator;
  behaviour is unchanged by this round.
- **An attached short-option value (`-f/etc/passwd`, no `=`) is still read as one project-relative word.** Accepted
  residual, recorded in `default_parser.py`'s own docstring: splitting it needs an option vocabulary the default parser
  by definition does not have.

## Test Architecture

**Existing helpers to reuse:**

- `tests/test_permission_decisions.py:101` — `assert_decision(command, config, expected_decision)`, the decision-spec
  workhorse; returns the result for further reason inspection
- `tests/test_permission_decisions.py:115` / `:127` — `assert_reason_includes` / `assert_primary_reason`, structural
  assertions over `Reason` value objects rather than substring matching on rendered prose
- `tests/test_permission_decisions.py:77` — `assert_config_is_reachable`, which fails a case whose config no real
  `command-policy.json` could produce; every new case inherits this guard through `decision_for`
- `tests/test_allowed_command_policy.py` — the
  `_policy(allowed_commands, command, path_resolution=None, allowed_prefixes=(), recurse=False)` factory, for unit-level
  cases that should not go through full `Config`
- `tests/conftest.py` — `cwd_pinned_inside_project(tmp_path)` for the argument-path containment cases (it pins both
  process cwd and `CLAUDE_PROJECT_DIR`, which the path cases depend on), and `ast_of()` for raw-AST assertions about the
  new word-safety field

**New helpers to create:**

- A table-driven matrix over the eight matcher types — why_needed: the success criteria require every matcher type to
  have its OWN adjudicated outcome for `required` and `block` next to unknowable content, and a hand-written case per
  cell invites silent gaps and copy-paste drift. The table makes "which cell is missing" visible.

**Fantasy callsites (test-facing API sketches):**

- `ArgumentKnowability.of(arguments).defeats_absence_proof()` — the `block` rule, true when anything is unknowable
- `ArgumentKnowability.of(arguments).first_shifting_position(scheme)` — the index rule, counting only word-count-
  changing expansions, in the combined or positional scheme
- `ArgumentKnowability.of(arguments).knowable_texts()` — the `required` presence proof, feeding a second pure parse

**Testability-driven production decisions:**

- Knowability is computed once in `_entry_rejection_reason`, where both `arguments` and `argument_texts` are still in
  hand, and passed explicitly down to `_filter_passes` and the path check — never re-derived and never read ambiently,
  mirroring how `substitution_indices` is threaded today
- Word-safety becomes a new field on `Argument`, computed in `Argument.from_word` at parse time alongside
  `contains_substitution`, so tests can assert it directly from `Statement.from_command(...)` without reaching into raw
  AST dicts

## Assumptions

- **`Argument` already carries `referenced_variables` and `contains_substitution` per word, so no new parsing is needed
  to know which argument is unknowable** — confirmed (read `lib/statement.py:223-254`; `Argument.from_word` populates
  both per word and recurses through `DblQuoted`)
- **With a variable declared via `onlyTheseVariables`, a literal fragment sharing a word with the variable satisfies a
  `required` filter and clears a `block` filter** — confirmed (probe
  `docs/improvements/experiments/variable-positional-threading/probe_variables.py`: `rg safe$HOME` ALLOWs against
  `required ^safe$`, `rg --dang$X` ALLOWs against `block ^--danger$`)
- **The same intra-word fragment hole affects SUBSTITUTIONS too, so the brief's claim that the substitution path fails
  closed is an artifact of its own probe not allow-listing the inner program** — confirmed (probe
  `probe_narrow_vs_broad.py` section 1: with `echo` allow-listed, `rg safe$(echo x)` ALLOWs against `required ^safe$`
  for `parameterRegex`, `matchFullParameter` and `positionalArgRegex`)
- **`_substitution_indices`'s dash-prefix skip lets an option-shaped word carrying a substitution escape even the
  unconditional block rule** — confirmed (probe `probe_narrow_vs_broad.py` section 3: `rg --dang$(echo x)` ALLOWs
  against an `optionPresent --danger` block filter)
- **Argument-path containment is judged on the fragment, so a variable appended to an in-project path escapes the
  boundary** — confirmed (probe `probe_variables.py` section D: `cat ./sub$ESC`, `cat ./sub/$ESC`, `cat ./a$ESC/b` and
  `cat "./sub$ESC"` all ALLOW, while the mirror case `cat $ESC/sub` already false-DENIES because the fragment reads as
  the absolute path `/sub`)
- **The operator's live config declares `onlyTheseVariables` on zero entries, so this tightening has no false-denial
  cost against today's real config** — confirmed (read `~/.claude/command-policy.json`: 59 entries, none carrying
  `onlyTheseVariables`; probe section E shows every variable-bearing everyday command already DENIES today)
- **The existing "presence is provable" tests pin a literal in a SEPARATE word, so the knowable-only rule keeps them
  green** — confirmed (read `tests/test_permission_decisions.py:281-391`: the two cases are
  `echo --required-flag $(echo safe)` and `echo expected-first $(echo tail)`)
- **Quotedness is recoverable per expansion part from the shfmt AST, though `Argument` exposes no such field today** —
  confirmed (probe `probe_quotedness_ast.py`: per-part `DblQuoted` nesting correctly separates word-safe `safe"$X"` /
  `"safe$X"` from splitting `"a b"$X` / `safe$X`, and `Argument`'s only fields are `text`, `contains_substitution`,
  `referenced_variables`)
- **`"$@"` and `"${arr[@]}"` expand to multiple words despite being double-quoted, so a naive word-safe rule would
  wrongly relax the index-shift rule for them** — confirmed (probe `probe_at_expansion.py`: `$@` is a `ParamExp` with
  `Param.Value == "@"`, `${arr[@]}` has `Param.Value == "arr"` plus an `Index` node containing `@`, while `"$*"` is
  genuinely one word)
- **The brief's stated test baseline of 634 passed with two permitted pre-existing xargs failures** — refuted (measured
  2026-09-19: `packages/command-policy/tests` is 663 passed, 0 failed, and both named xargs cases are already green, so
  the allowance no longer applies and ANY failure belongs to this improvement; `packages/shfmt-permissions/tests` is 751
  passed, matching the brief)
- **`nix-shell --run pytest`, the test command the project CLAUDE.md documents, is itself denied by command-policy** —
  confirmed (measured: the `nix-shell` entry's `nestedCommand` filter rejects every invocation because the bundled
  `parsers/nix-shell.py` publishes no nested commands; the working route is `bypass-policy nix-shell --run "pytest -q"`)

## Design Decisions

### Scope of the unknowability fix

- **Chosen:** One unified per-argument knowability rule covering variables AND substitutions, rather than the briefed
  variables-only mirror of `_substitution_indices`
- **Rationale:** One defect, one fix — the three holes are the same underlying mistake, comparing a fragment as if it
  were the whole argument, so splitting them into separate improvements would leave the codebase half-correct between
  them and make each one harder to reason about
- **Rejected alternatives:** Variables only, exactly as briefed (leaves the substitution intra-word hole and the
  dash-prefixed block hole open, both reachable with NO `onlyTheseVariables` declaration and therefore strictly more
  exposed than the variable hole); narrowest index-shift-only fix (leaves every fragment-comparison hole open for both)
- **Date:** 2026-09-19

### Whether `onlyTheseVariables` also grants filter opacity

- **Chosen:** Separate grants — declaring a variable acceptable does NOT mean accepting that filters cannot see through
  it, and no new config knob is added to express the latter
- **Rationale:** `onlyTheseVariables` vouches for WHICH names may be referenced; a filter inspects the VALUE, which the
  declaration says nothing about. The decision model also forbids new leniency knobs — the config expresses what IS
  allowed and cannot express leniency — and deny is routing, so a false denial keeps `find-auto-allowed-command` and
  `bypass-policy` as the documented ways forward
- **Rejected alternatives:** Treat a declared variable as also waiving filter soundness for that entry (would make the
  fragment attack reachable by design); add an explicit per-entry opt-out knob (contradicts the deny+hint outcome model)
- **Date:** 2026-09-19

### Argument-path containment next to unknowable content

- **Chosen (revised 2026-09-19, after independent review failed the first version — see "Reopened" below):** Fail closed
  only when the entry's own parser actually produced a path candidate for this invocation
  (`ParsedResult.paths_for_validation` non-empty) — an entry performing argument-path validation does not vouch when
  unknowable content is present AND there is a real path candidate to fail closed on. Still the blunt "any unknowable
  argument defeats the WHOLE entry" rule once that gate is open, not a per-path refinement.
- **Rationale:** Path containment is a security boundary, not a pattern assertion, and a per-path refinement would
  itself be unsound: path DETECTION runs on the fragment, so a word that does not look like a path as a fragment
  (`foo$X`) can still be one at runtime (`foo/../../etc`) — this half of the original rationale is unchanged. What was
  wrong in the first version was applying that fail-closed posture even when NO path candidate existed at all: every
  parser in this codebase (Default, Structured, the bundled `git` parser) requires a non-empty literal value before it
  ever adds anything to `paths_for_validation`, so a PURE substitution (`$(date)`, contributing empty text) can never
  produce a candidate regardless of what it resolves to at runtime — denying on it protects nothing and simply
  neutralises `commandSubstitutionResponse: "via-allowed-commands"` for the ordinary case. "The entry produced no path
  candidate" and "nothing here occupies a path position" turned out to be the same fact under every parser this engine
  has, not two conditions needing separate handling, so the fix is a single non-emptiness gate, not a new per-position
  concept.
- **Rejected alternatives:** Leave path containment unchanged and record it as a residual gap the way
  `sensitive_paths_policy.py`'s substring gap is recorded; refine per detected path (unsound, as above); correlate a
  specific unknowable argument to a specific parsed path by string matching (rejected per this file's own Implementation
  Notes — `paths_for_validation` holds resolved absolute paths, not original argument text, so there is nothing sound to
  correlate against)
- **SUPERSEDED 2026-09-19 by the second fix round** — see "Reopened (second fix round)" below. Both this entry's chosen
  rule and its stated residual were wrong, and the residual was wrong in a way measurement refuted rather than merely
  under-stated: "denying a pure substitution protects nothing" assumed a substitution that produces no literal text also
  produces no path at runtime. It produces no VISIBLE path, which is not the same claim. With `echo` allow-listed,
  `ls $(echo /etc)`, `cat $(echo ~/.ssh/id_rsa)`, `rg -f $(echo /etc/passwd) pattern` and `ls --color=$(echo /etc)` all
  ALLOWED under this rule. The reasoning "every parser requires a non-empty literal value before adding to
  `paths_for_validation`, so no candidate means nothing occupies a path position" was also factually false:
  `parsers/cat.py` and `parsers/chmod.py` call `resolve_path("")`, which yields the cwd, so they emit a candidate for an
  EMPTY argument — which is precisely why the gate this entry introduced gated nothing for those entries.
- **Date:** 2026-09-19; revised 2026-09-19 (same day, after review); superseded 2026-09-19 (second fix round)

### Precision of the index-shift rule

- **Chosen:** Precise — a double-quoted expansion yields exactly one word and therefore does not shift a pinned index,
  which requires a new word-safety field on `Argument`
- **Rationale:** rationale not captured
- **Rejected alternatives:** Conservative treatment where any unknowable shifts regardless of quoting, matching how
  substitutions are handled today and needing no new field on `Argument` (measured false-denial cost of the conservative
  option was zero against the live config, since its only index filters are on `improvement-marker` and
  `estimate-learn`, both always invoked with literal subcommands)
- **Date:** 2026-09-19

### Unknowable content under an external parser

- **Chosen:** Fail closed with no knowable-only re-parse for `provided`/`command` parser entries — unknowable content
  simply defeats a `required` filter there
- **Rationale:** rationale not captured
- **Scope correction (2026-09-19, second fix round).** The Proposed Approach above describes the affected entries as
  "the wrapper entries (`nix-shell`, `nix`, `timeout`) where declining to conclude is the right default anyway". That is
  wrong about the operator's live config, and the error mattered because it made the blast radius look negligible. The
  external-parser set there is `git`, `cat`, `grep`, `find`, `chmod`, `composer`, `npm`, `awk`, `gawk` and `sed` in
  addition to the three wrappers — thirteen of the config's entries, including the most-used commands in daily work, not
  three niche ones. The decision itself stands; only its stated reach was understated.
- **Deliberately NOT extended to argument-path containment (second fix round).** Containment's own unknowable-operand
  question DOES re-invoke an external parser once, and that is not an inconsistency with this entry. A `required` filter
  can decline to conclude at no cost — failing closed is a complete, safe answer. Containment cannot: declining there
  would deny every external-parser entry any substitution whatsoever, which would delete the entire "a parser that
  classifies the slot as not-a-path" route and with it the reason to write a good parser at all. The two questions
  differ in what a refusal costs, so they differ in whether the second invocation is worth paying for.
- **Rejected alternatives:** Run the knowable-only re-evaluation uniformly for every parser type, accepting a second
  subprocess invocation per affected filter in exchange for a rule with no parser-type special case
- **Date:** 2026-09-19; reach corrected and containment carve-out added 2026-09-19 (second fix round)

## Success Criteria

- [x] With a variable declared via `onlyTheseVariables`, `rg safe$HOME` and `rg "safe$HOME"` DENY against a
      `required ^safe$` filter, and `rg --dang$X` DENIES against a `block ^--danger$` filter
- [x] With the inner program allow-listed, `rg safe$(echo x)` DENIES against a `required ^safe$` filter for
      `parameterRegex`, `matchFullParameter` and `positionalArgRegex`
- [x] `rg --dang$(echo x)` DENIES against an `optionPresent --danger` block filter (the dash-prefix skip is gone)
- [x] Every one of the eight matcher types has an adjudicated, tested outcome for both `required` and `block` next to
      unknowable content — no type reaches its verdict by generalisation from another
- [x] `cat ./sub$ESC`, `cat ./sub/$ESC`, `cat ./a$ESC/b` and `cat "./sub$ESC"` all DENY on argument-path containment
- [x] `echo --required-flag $(echo safe)` and `echo expected-first $(echo tail)` still ALLOW — presence proven by a
      literal in a separate word is unaffected
- [x] An entry with no filters and `hasNoPathParameters` still ALLOWs a variable-bearing invocation
- [x] `"$@"` and `"${arr[@]}"` are NOT treated as word-safe, while `"$X"` and `"$*"` are
- [x] Single-quoted `'literal$X'` remains fully knowable and is not treated as unknowable
- [x] Every new test was run against pre-fix code and observed to FAIL for the right reason; the red counts are recorded
      in the implementation notes
- [x] `packages/command-policy/tests` is green with ZERO failures (baseline 663 passed), and
      `packages/shfmt-permissions/tests` is unchanged at 751 passed
- [x] `docs/knowledgebase/command-policy-decision-model.md` states the corrected rules, including that the "presence is
      provable" rule applies only to a literal in a separate word

## Implementation TODO

- [x] Update status to in-progress
- [x] Confirm the starting baseline: `cd packages/command-policy/tests && bypass-policy nix-shell --run "pytest -q"`
      reports 663 passed, 0 failed (plain `nix-shell` is denied by command-policy; see Implementation Notes)
- [x] RED: add the decision-spec cases for variable-bearing fragments — `rg safe$HOME`, `rg "safe$HOME"`,
      `rg ${HOME}safe` against `required ^safe$`, and `rg --dang$X` against `block ^--danger$` — and run them against
      unmodified code, recording how many fail and confirming each fails for the fragment reason
- [x] RED: add the substitution-parity cases with the inner program allow-listed — `rg safe$(echo x)` against
      `required ^safe$` for `parameterRegex`, `matchFullParameter`, `positionalArgRegex` — and the dash-prefixed case
      `rg --dang$(echo x)` against an `optionPresent --danger` block filter; confirm all fail pre-fix
- [x] RED: add the argument-path containment cases (`cat ./sub$ESC`, `cat ./sub/$ESC`, `cat ./a$ESC/b`,
      `cat "./sub$ESC"`) using `cwd_pinned_inside_project`; confirm all fail pre-fix
- [x] RED: add the regression cases that must STAY green — `echo --required-flag $(echo safe)`,
      `echo expected-first $(echo tail)`, an entry with no filters and `hasNoPathParameters`, and single-quoted
      `'literal$X'`; confirm these already pass pre-fix so they are genuine guards, not new behaviour
- [x] Add the word-safety field to `Argument.from_word` in `lib/statement.py`, computed per expansion PART via
      `DblQuoted` nesting, excluding `$@` (`Param.Value == "@"`) and `${arr[@]}` (an `Index` node containing `@`) while
      keeping `"$*"` word-safe; unit-test it directly against `Statement.from_command`
- [x] Introduce the knowability value object in its own `lib/` module, with the three behaviours sketched in Test
      Architecture, and unit-test it in isolation
- [x] GREEN: consume it in `_entry_rejection_reason` / `_filter_passes` — `block` defeated by any unknowable content;
      `required` non-index matchers proven against knowable arguments only; `required` index matchers using the
      word-count-aware at-or-after rule
- [x] GREEN: consume it in `_first_path_outside_allowed_prefixes` so an entry doing path validation does not vouch next
      to unknowable content
- [x] GREEN: make `nestedCommand` fail closed when the invocation carries unknowable content
- [x] Make external-parser entries (`provided`/`command`) fail closed without a knowable-only re-parse, and test that no
      second subprocess parse happens for them
- [x] Delete `_substitution_indices` and `_substitution_override` — they are fully superseded; no compatibility shim
- [x] REFACTOR: review the new module and its callers against the Yes/No clarity test, and fold the module docstring's
      rationale into names wherever a name can carry it
- [x] Add `MATCHING_BRANCH_COVERAGE` manifest entries in `tests/test_permission_decisions.py` for every new branch, and
      confirm the two guard tests (`test_every_matching_branch_has_at_least_one_specification_case`,
      `test_every_case_named_in_the_coverage_manifest_exists`) stay green
- [x] Add the explicit test for the one newly-ALLOWED shape — a double-quoted substitution no longer shifting a pinned
      index — so the single relaxation in this change is pinned rather than incidental
- [x] Run both suites: `packages/command-policy/tests` green with ZERO failures, `packages/shfmt-permissions/tests`
      unchanged at 751 passed
- [x] Re-run the planning probes under `docs/improvements/experiments/variable-positional-threading/` and confirm the
      previously-ALLOWing cases now DENY, then delete the probe directory (its findings are recorded in this file)
- [x] Update `docs/knowledgebase/command-policy-decision-model.md` by CONVERTING three passages that now describe the
      pre-fix gap, not by appending to them: (a) the "rules and their ENFORCEMENT are two different things" paragraph in
      "What the Engine May Not Conclude From Text It Cannot See" — the asymmetry it names is gone once variables are
      threaded, so it becomes a plain statement that both kinds of unknowable content are enforced alike; (b) the
      "`.text` carries no signal that it dropped something" note under "Statement: What Every Policy Actually Reads" —
      still true of the accessor, but the caller obligation it describes is now discharged centrally rather than left to
      each policy; (c) the argument-path containment Gotcha, which must be REMOVED once containment fails closed, since
      it names this improvement as its tracker. Keep the "presence is provable only from a SEPARATE word" bullet — that
      one states the corrected rule and stays
- [x] Confirm the updated article reads timelessly once converted — it should describe an engine where both kinds of
      unknowable content are enforced alike, with no trace of "currently only substitutions" framing and no reference to
      this improvement as a tracker
- [x] Update status to completed

### Reopened 2026-09-19: fix the too-broad path-containment widening (independent review failure)

- [x] Update status to in-progress
- [x] Confirm the starting baseline: `packages/command-policy/tests` 724 passed 0 failed,
      `packages/shfmt-permissions/tests` 751 passed, matching the prior completion's final state exactly
- [x] Measure all eleven regressed commands against the real merged config (`~/.claude/command-policy.json` +
      `.claude/command-policy.json`) via a `sys.path`-injected `Config.from_dict`, confirming each denies pre-fix via
      `ArgumentPathOutsideAllowedPaths(path='<unresolvable>')`
- [x] RED: restore the three named bent fixtures (`test_command_substitution_response_defaults_to_via_allowed_commands`,
      `test_command_substitution_response_via_allowed_commands_allows_an_allow_listed_inner_command`,
      `test_a_double_quoted_flag_ahead_of_a_substitution_does_not_miscount_positions`) to their bare-entry form and
      confirm each fails pre-fix
- [x] Review the other six bent fixtures by hand; found all six also realistic and restorable; RED-confirmed all six
      (three deny-expecting ones already passed pre-fix since they deny via the filter mechanism regardless — not
      vacuous, just unaffected by path containment either way)
- [x] RED: add the two new substitution-axis path-containment tests (a substitution IN a path operand still denies, a
      substitution NOT in a path operand allows) and confirm the "allow" one fails pre-fix, the "deny" one already
      passes pre-fix (the old blunt rule over-denied it too)
- [x] GREEN: narrow `_first_path_outside_allowed_prefixes` to fail closed only when `parsed.paths_for_validation` is
      non-empty; remove the now-dead `<unresolvable>` branch and `ArgumentKnowability.first_unknowable_text()` plus its
      two unit tests
- [x] Re-run all nine restored fixtures plus the two new tests; confirm GREEN
- [x] Re-measure all eleven commands against the real merged config post-fix; record the actual per-command outcome
      (nine allow; `git add`/`git commit -m` still deny, for the pre-existing, unrelated, correctly-untouched
      external-parser `namedValue` rule)
- [x] Task 3: adjudicate `hasNoPathParameters` as a factual claim (not a waiver); no code/schema change needed; recorded
      in Implementation Notes and the Design Decisions entry
- [x] Task 4: confirm `<unresolvable>` is unreachable post-fix and remove it rather than reword it
- [x] Task 5: bump `packages/command-policy/.claude-plugin/plugin.json` and the root `.claude-plugin/marketplace.json`
      entry `0.3.1` -> `0.3.2` in lockstep
- [x] Add `MATCHING_BRANCH_COVERAGE` manifest entries for the two new tests; confirm the two guard tests stay green
- [x] Run both suites again: `packages/command-policy/tests` 724 passed 0 failed, `packages/shfmt-permissions/tests` 751
      passed, unchanged
- [x] Delete the probe scratch directory (`docs/improvements/experiments/per-argument-knowability-fix/`) after recording
      its findings in this file
- [x] Update the knowledgebase article's argument-path-containment passage to describe the narrowed rule and its
      accepted residual
- [x] Update status to completed

### Reopened 2026-09-19 (second fix round): whatever cannot be ruled out is a path

- [x] Update status to in-progress
- [x] Confirm the starting baseline: `packages/command-policy/tests` 724 passed 0 failed,
      `packages/shfmt-permissions/tests` 751 passed
- [x] STEP 0: measure whether the default parser already makes every non-empty literal a path candidate, decide the six
      named commands against the real merged config, and report to the orchestrator before writing any code
- [x] Measure the LITERAL twin (`ls --color=/etc`, `ls --color=/etc/passwd`, `rg --file=/etc/passwd pattern`) at the
      pre-change working tree and record whether a literal path escape already existed
- [x] Make `DefaultParser.paths_for_validation` carry every argument, options included, splitting `--name=value` so the
      value is the candidate; leave `paths_for_filtering` on the shape heuristic
- [x] Add `ArgumentKnowability.texts_with_unknowable_marked` and consume it from a new
      `_an_unknowable_argument_occupies_a_path_operand`, so an unknowable value denies only when it occupies a slot the
      entry's own parser treats as a path
- [x] Add the `UnknowablePathArgument` Reason plus its renderer clause, rather than reporting a placeholder path
- [x] Verify the four closed leaks now DENY and the two other-direction cases now ALLOW
- [x] Verify every earlier-round denial still denies and `echo --required-flag $(echo safe)` still allows
- [x] Sweep everyday LITERAL invocations for allow->deny regressions; attribute any denial by re-running against a
      pristine `lib/` materialised from git rather than assuming it is pre-existing
- [x] Adjudicate in writing every existing test that legitimately changed meaning; add no flag merely to make one pass
- [x] Task 2: restore/repair the four surviving bent fixtures in `tests/test_allowed_command_policy.py`, rewrite the two
      stale docstrings, and correct the "all nine"/"no test needs a false claim" record
- [x] Apply one truthfulness rule to every `hasNoPathParameters` in the spec suite: factual where it creates an ALLOW,
      left verbatim where it only isolates a DENY
- [x] Task 3: correct the "pre-existing" label on the two git denials (verified at `96204f3`, `ad6a8fd^`, `ad6a8fd`) and
      record `git add $(echo README.md)`; correct the external-parser rationale's claim that only three wrappers are
      affected
- [x] Task 4: rewrite the security passages in the improvement file, the code docstrings and the knowledgebase to
      describe the rule that now exists, and remove the false "every parser requires a non-empty literal value" claim
- [x] Add `MATCHING_BRANCH_COVERAGE` entries for the new cases; confirm both manifest guard tests stay green
- [x] Run both suites: `packages/command-policy/tests` green with ZERO failures, `packages/shfmt-permissions/tests`
      unchanged at 751 passed
- [x] Bump `packages/command-policy/.claude-plugin/plugin.json` and the root `.claude-plugin/marketplace.json` entry in
      lockstep
- [x] Delete the probe scratch directory after recording its findings in this file
- [x] Update status to completed

## Related Past Improvements

- improvement-20260918-205740: prerequisite — fixed the sibling double-quoted-argument-blindness hole in the same
  matcher family this improvement targets for variables/substitutions.
- improvement-20260918-185726: same engine area (command-policy path/command matching) — symlink resolution as another
  fail-closed containment fix.
