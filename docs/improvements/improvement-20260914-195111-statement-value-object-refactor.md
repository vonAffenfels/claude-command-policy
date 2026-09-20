# Improvement 20260914-195111: TRUNK. Refactor the core of `packages/shfmt-permissions/scripts/analyze-bash-command.py` from an "-er"-style analyzer operating on raw shfmt AST dicts into an immutable `Statement` value object with copy-on-write mechanics, carrying its configuration and its permission policies as proper value objects and decomposing itself recursively to mirror the shell's own nesting

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-14
- Updated: 2026-09-15
- Plan started: 2026-09-14T19:50:21+02:00
- Plan finished: 2026-09-15T07:15:45+02:00
- Depends on: 20260912-234028

## Leaf Stream

Ordered, dependency-respecting stream of leaf sub-plans for this trunk's baton-pass chain (SHAPE -> DESCEND ->
INTEGRATE). Each leaf's authoritative dependency edge lives in ITS OWN file's `- Depends on:` Meta line, not here — this
list only tracks order + status + the hand-back pointer.

**RE-CUT 2026-09-15 — nine leaves, was six.** The previous six-leaf breakdown was drawn before the plugin move and
before the new outcome model, and it left six pieces of work owned by nobody. Three leaves were added: the package
scaffold (first, so no leaf has to guess at paths — the exact failure that invalidated this trunk), the deny-reason and
escalation surface (split out of the pipeline leaf, which had become the largest by a distance), and the two skills
(migration + equivalence search, both skill-authoring work on one shared surface). The four value-object leaves keep
their original boundaries.

1. `20260915-010936` — **command-policy package scaffold and naming scheme** — NEW, and deliberately first: creates the
   package, registers it in `marketplace.json`, establishes the `conftest.py` the old package never had, and settles all
   five user-facing `bin/` command names. Every later leaf's paths depend on it existing, which removes the whole class
   of failure that invalidated this trunk. Touches no engine logic. — status: done — interface:
   docs/improvements/improvement-20260915-010936-command-policy-plugin-scaffold.md
2. `20260914-213049` — **Authored decision specification** (was: golden-corpus characterization harness) — The rewrite's
   assumed safety net is only ~70% real; author the engine's intended decisions as an implementation-independent
   specification. Every later leaf verifies against it. ⚠ RE-PLAN REQUIRED: its outcome assertions predate the new
   outcome model, and it self-reported as already oversized before any of the 2026-09-15 work landed — consider whether
   its audit/flag-list half separates from its specification half. — status: done — interface:
   docs/improvements/improvement-20260914-213049-shfmt-golden-corpus-harness.md
3. `20260914-213153` — **Config value object** — `Config.fromText`, `warnings()`, `explain()` — Context-producing:
   filters and policies are constructed FROM config value objects, so the config model must exist before them. Also the
   only leaf with a six-consumer blast radius. ⚠ Now also owns the death of four decision knobs and the config-key
   renames. — status: done — interface: docs/improvements/improvement-20260914-213153-config-value-object.md
4. `20260914-213321` — **Statement value object** — recursive decomposition and `RedirectOperator` — The core structural
   model that replaces `walk_ast`'s flattening at 11 call sites. Independent of the config model — a Statement is
   constructible from a command string alone. — status: done — interface:
   docs/improvements/improvement-20260914-213321-statement-value-object.md
5. `20260914-213502` — **Filter and Parser families as copy-on-write value objects** — 13 classes plus two factory
   functions, built from config definitions; large enough to bloat any other leaf's context and separable behind the
   filter/parser construction interface. — status: done — interface:
   docs/improvements/improvement-20260914-213502-filter-parser-value-objects.md
6. `20260914-213652` — **Uniform policy pipeline, Pass ordering and PermissionDecision** — Composes all three models and
   dissolves `BashCommandAnalyzer` itself. Carries the rewrite's hardest correctness problem: reconstructing today's
   positional precedence as declared Pass ordering. Now scoped to the pipeline and the outcome VOCABULARY only — what
   the engine says when it denies moved to leaf 7. — status: done — interface:
   docs/improvements/improvement-20260914-213652-uniform-policy-pipeline.md
7. `20260915-010959` — **Deny+hint reason construction and the escalation paths** — NEW, split out of leaf 6. Owns the
   mechanically-derived near-miss hint, the pointer to the equivalence-search skill, and the three escalation-path
   policies with their settled outcomes: `bypass-policy` -> passthrough/'no opinion', `add-allow-policy` -> forced
   `ask`, and the shell-performed-redirect veto staying ABSOLUTE. Also corrects the inherited `BYPASS_REASON` text,
   whose claim to count as 'a user intervention' is not reliably true. — status: done — interface:
   docs/improvements/improvement-20260915-010959-deny-reason-escalation-paths.md
8. `20260915-011123` — **Config-migration skill and equivalence-search skill** — NEW. Both are skill-authoring work on
   one shared surface (`Config.explain()`'s rendered output), which is why they share a leaf. The migration skill is
   SEMANTIC, not a rename: four decision knobs cease to exist, so a verbatim-copied config is not an equivalent config.
   The equivalence-search skill is what deny reasons point at, and must make explicit that it runs AFTER a deterministic
   deny rather than inside it. — status: done — interface:
   docs/improvements/improvement-20260915-011123-config-migration-equivalence-search.md
9. `20260914-213825` — **Land across consumer surfaces, finish test migration, deprecate the old plugin** — Makes the
   rewrite shippable rather than merely built: the remaining consumer surfaces (including `analyze-path.py`), the
   ~100-140 internals-coupled tests, the `shfmt-permissions` deprecation, and the trunk's final acceptance gates. —
   status: done — interface: docs/improvements/improvement-20260914-213825-land-rewrite-consumers-test-migration.md

## Shared Context (For Leaves)

> ## ✅ RE-PLAN COMPLETE (finished 2026-09-15) — leaf stream re-cut to nine; leaf `20260914-213049` remains separately halted
>
> This trunk was invalidated on 2026-09-15 during leaf `20260914-213049`'s planning session, and a second, larger
> invalidation arrived later the same day (the outcome-model change, item B below). **The re-plan below is now
> finished** — the leaf stream is re-cut (see `## Leaf Stream` above) and SHAPE has spawned leaf `20260915-010936` (the
> package scaffold) as the first leaf in the new chain. Planning/implementing leaves in stream order is UNBLOCKED as of
> this spawn. This banner previously said "ALL LEAVES REMAIN HALTED" and "do not plan"; that language is now stale and
> is corrected here rather than left to mislead a future reader — the re-plan work it referred to (section A/B/C below)
> is done, only the one item in section C still marked open remains outstanding, and that item is scoped to leaf
> `20260914-213049`'s own re-planning, not to the chain generally.
>
> **⚠ LEAF `20260914-213049` SPECIFICALLY REMAINS HALTED (settled 2026-09-15) — this part of the enforcement is still
> live.** It is at status `planned` — the user applied that by hand after the status-updater refused the transition —
> and it ALSO retains its `⛔ DO NOT IMPLEMENT — HALTED PENDING TRUNK RE-PLAN` notice as a second layer, pending its own
> re-planning session (it must place a test file against the now-scaffolded package and re-read its outcome assertions
> against the new outcome model — see section D below). Since `queue-planner` only ever considers files at
> `ready-to-implement`, its dispatch window stays genuinely closed by supported means until that re-planning happens.
> **Any session resuming this chain must still check both layers before assuming THAT SPECIFIC leaf is runnable** — this
> does not apply to the other eight leaves in the re-cut stream.
>
> Two earlier claims in this banner are RETRACTED as wrong: that the leaf "has been reverted to `planned`" (it had not
> been, at the time), and the planner's subsequent counter-claim that the halt "was never applied / action required" (it
> had been applied, as a deliberate prose guard). Both are recorded here because the second error was the planner
> overstating a finding it had not finished verifying — the kind of mistake this trunk's own Assumption-Verification
> discipline exists to catch.
>
> THE UNDERLYING GAP REMAINS, and it is why a hand-edit was needed at all: THE PLUGIN HAS NO SUPPORTED WAY TO HALT A
> `ready-to-implement` IMPROVEMENT. Measured against `packages/improvement/agents/improvement-status-updater.md`:
> `ready-to-implement → planned` does not exist, and `ready-to-implement → blocked` is explicitly forbidden (`:50`, must
> route through `in-progress`). Routing through `in-progress` would stamp the set-once `Impl started` timestamp,
> fabricating an implementation that never happened and making `improvement-timings` render a bogus IMPL duration;
> `blocked` additionally means "tried and failed", which is untrue here. The prose notice was the least-dishonest option
> available.
>
> WHY A PROSE NOTICE ALONE WAS NOT SUFFICIENT (now moot for this leaf, but the reasoning is the gap's evidence):
> `packages/improvement/agents/queue-planner.md` selects candidates from files at status `ready-to-implement`, and its
> only outputs are `next`/`defer`/`in_progress`/`blocked`/`unrunnable` — where `unrunnable` means only "prerequisite
> neither ready nor completed" (`:72-73`). There is NO sanctioned channel for "halted by notice". The queue-planner does
> read the files and is a reasoning agent, so it might have honoured the banner, but nothing required it to. That is
> precisely why the status field had to be corrected by hand rather than left to prose.
>
> A supported-but-dishonest workaround was considered and REJECTED: adding `- Depends on: 20260914-195111` to the leaf
> would make the queue-planner classify it `unrunnable` and never dispatch it, but the trunk is implemented LAST (at
> INTEGRATE), so "leaf depends on trunk" is backwards as a permanent statement and would have outlived its purpose.
>
> **This gap belongs to the improvement plugin, not to this trunk** — see `## Observed during exploration`.
>
> ### A. Resolved by this re-plan so far
>
> 1. **NEW PLUGIN: `command-policy`.** `shfmt-permissions` names the plugin after its own dependency (the `shfmt` binary
>    it shells out to for AST parsing) — it tells a user nothing and reads like a shell formatter. `command-policy` is
>    outcome-neutral, covering allow/deny/passthrough equally, where the rejected `deterministic-auto-approve` named
>    only the `allow` outcome and framed a security control as a convenience feature. "Deterministic" survives as the
>    lead word of the plugin DESCRIPTION: _"Deterministic, rule-based permission decisions for commands and file access.
>    Same input, same verdict, every time — no model judgment in the loop."_
> 2. **CUTOVER: additive, deprecate only.** `command-policy` is built ALONGSIDE an untouched `shfmt-permissions` (today
>    at marketplace version 6.1.2, with live users). The old plugin is marked deprecated in its description; nothing
>    forces its removal. See the design decision of the same name, including the planner's unresolved flag about the
>    fail-open holes this leaves reachable.
> 3. **CONFIG MIGRATION: a migration skill, no auto-detection.** `~/.claude/shfmt-permissions.json` ->
>    `~/.claude/command-policy.json` is performed by a skill the user runs; the engine contains NO code that detects an
>    un-migrated config or falls back to the old path. The skill must cover SEMANTIC migration, not just the filename:
>    under the new outcome model (B) most decision knobs cease to exist, so a copied-across config is not an equivalent
>    config.
> 4. **THE NEW OUTCOME MODEL** — see section B below. This is the largest single change and it post-dates every leaf's
>    scoping.
>
> ### B. THE NEW OUTCOME MODEL (2026-09-15) — supersedes the engine's entire decision vocabulary
>
> The expected tool-call path is now, in the user's own formulation:
>
> ```
> bash(non-auto-approved-command) - deny with reason asking to use an approved command.
>                                   preferably with ai hints which other auto approved commands could be used
> branch 1: uses equivalent tool  - bash(equivalent-auto-allowed-command)
> branch 2: force command through manual approve
>                                 - bash(bypass-policy non-auto-approved-command)  // prompts through claude-code dialog
> ```
>
> Read as outcomes:
>
> - **allow** — auto-approved, runs silently. Unchanged.
> - **deny + hint** — the new DEFAULT for anything not auto-approved. Not "ask the human": it bounces back to the model
>   with a reason naming viable approved alternatives, so the model self-corrects (branch 1). The hint is computed
>   DETERMINISTICALLY by plain code and consumed BY the model; there is no LLM call inside the hook.
> - **passthrough to the Claude Code dialog** — reachable ONLY when the caller explicitly opts in by name via the bypass
>   wrapper (branch 2). It stops being an outcome the config can select by default.
>
> **Consequence 1 — four of the five decision knobs cease to exist.** Measured against current HEAD, the engine has
> exactly five outcome-selecting knobs, all declared in `config_loader.py` `DECISION_KNOBS` (`:123-129`) and validated
> by the `VALID_*` sets (`:37-41`):
>
> | Knob                          | Today's values / default                                                              | Fate under the new model                                                                                                                                                                                                                          |
> | ----------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
> | `defaultDecision`             | `{passthrough, ask}`, default `passthrough` (note: `deny` is NOT a legal value today) | DIES — not-allow-listed becomes deny+hint, a constant                                                                                                                                                                                             |
> | `sensitiveVariableResponse`   | `{ask, block}`, default `ask`                                                         | DIES — collapses to deny                                                                                                                                                                                                                          |
> | `pathValidationResponse`      | `{passthrough, ask, deny}`, default `passthrough`                                     | DIES — collapses to deny                                                                                                                                                                                                                          |
> | `filterRejectionResponse`     | `{passthrough, ask, deny}`, default `passthrough`                                     | DIES — collapses to deny                                                                                                                                                                                                                          |
> | `commandSubstitutionResponse` | `{block, ask, via-allowed-commands}`, default `via-allowed-commands`                  | SURVIVES REDUCED — its `ask` dies and `block` becomes deny, but the `via-allowed-commands` choice (evaluate substitution content against the allowlist vs. refuse it outright) is a MATCHING decision, not an outcome one, and remains meaningful |
>
> The clean line this draws: **the config can no longer express "be lenient". It can only express what is allowed.**
> Every knob of the form "what should happen when X does not match" becomes a constant. This is a significant tightening
> for existing users — today's shipped default (`defaultDecision: passthrough`) means an unrecognised command silently
> falls through to Claude Code's normal flow; under the new model it is denied.
>
> **Consequence 2 — branch 2 ALREADY EXISTS and mostly does not need building.** `bin/bypass-shfmt-permissions` plus
> `_ast_is_bypass_wrapped` (`analyze-bash-command.py:1020-1037`) already return
> `AnalysisResult("passthrough", BYPASS_REASON)` at `:1448-1453`, before every other rule, which prints nothing and
> hands the decision to Claude Code's own dialog. That IS branch 2. What is actually new is (a) the rename to
> `bypass-policy`, and (b) the default flip that makes branch 2 worth reaching for. Its "sole command on the line"
> recognition rule (`sole_invoked_program` `:962-968`, `COMMAND_HIDING_NODE_TYPES` `:899-912`) exists to stop denylist
> smuggling (`rm -rf / ; bypass-... true`) and must survive the rename intact.
>
> **Consequence 3 — there is a THIRD escalation path the new model's two branches do not mention.**
> `propose-shfmt-permissions-{user,project}-allow` (`_check_propose_allow` `:1635-1701`) always forces `ask`, carrying a
> JSON diff of the exact `allowedCommands` entry it would append plus Claude's stated `--intent`, so approving the
> dialog IS the write. Where bypass says "run this once anyway", propose-allow says "make this permanently allowed".
> Under a deny-by-default model this path becomes MORE important, not less — it is the durable fix branch 1 cannot
> reach. Its fate is unresolved; see Open Questions.
>
> **Consequence 4 — CASE A's documented philosophy reverses.** The engine today distinguishes CASE A (program not in
> `allowedCommands` at all -> deliberately opinion-free, `defaultDecision`) from CASE B (program IS allow-listed but
> this invocation was rejected -> `filterRejectionResponse`, enriched with a mechanical reason).
> `docs/knowledgebase/shfmt-permissions.md:44-86` documents CASE A's silence as intentional. The new model abolishes
> that distinction: both become deny+hint. That 554-line knowledgebase article needs substantial rewriting, and its
> rationale sections cannot simply be ported.
>
> **Consequence 5 — the hint has a home to grow into.** `self.config` is already fully in scope at every deny-reason
> construction site, so no plumbing is needed to reach the data a richer hint would want. Today's enrichment is
> `_describe_filter` / `_derive_filter_alternative` (`:2159-2209`), which derive ONLY from the single filter that fired
> and explicitly refuse to build a command-equivalence table because it "would rot like hand-written prose". The chosen
> hint design (see design decisions) respects that refusal: near-miss stays mechanically derived, and cross-command
> equivalence is delegated to a skill/agent that reads the RENDERED rules at need rather than to a static authored map.
>
> ### C. Still open in this re-plan
>
> RESOLVED since this section was first written (all now carry full Design Decisions entries):
>
> - ~~Whether `bypass-policy` may override the sensitive-path redirect veto~~ — RESOLVED: the veto stays ABSOLUTE and
>   unescalatable. The initial "escalates anything" answer was reversed once the concrete existing guard was surfaced.
> - ~~The fate of `propose-allow`~~ — RESOLVED: it survives as a named escalation, renamed `add-allow-policy`, and it is
>   the ONLY path that forces `ask`. `bypass-policy` produces "no opinion" (`passthrough`) instead.
> - ~~Parse-failure behaviour~~ — RESOLVED: keep `passthrough`. A deliberate availability-driven fail-open, and the one
>   place the new model does not deny on non-approval.
>
> STILL OPEN:
>
> - ~~Whether "additive, deprecate only" should carry a forcing function~~ — RESOLVED: the retained exposure IS the
>   forcing function, deliberately. See the cutover and fail-open-holes decisions. No scheduled-removal improvement and
>   no deprecation warning are planned. The one caveat recorded there: the acceptance is calibrated to "one more day"
>   against a nine-leaf chain, so it deserves revisiting if the chain stretches rather than being inherited silently.
> - ~~THE LEAF STREAM HAS NOT YET BEEN RE-CUT~~ — DONE 2026-09-15: re-cut to nine leaves, all previously-homeless work
>   now owned. See `## Leaf Stream` above and `## Proposed Approach` below.
> - Whether `add-allow-policy` keeps the current user-scope/project-scope PAIR of commands or collapses them behind a
>   flag. The name arrived as a naming signal, not a settled rename, and there are two commands today. **Assigned to
>   leaf `20260915-010936`** (the scaffold leaf owns the naming scheme).
> - Whether leaf `20260914-213049`'s audit/flag-list half should separate from its specification half. It self-reported
>   as oversized BEFORE the 2026-09-15 work landed, and the re-cut deliberately did not split it — that call belongs to
>   its own re-planning session, which now has the new outcome model to encode as well.
>
> ### D. Corrections carried forward from leaf `20260914-213049`
>
> - The "eleven short-circuit branches in `analyze` at `:1414-1553`" figure UNDERCOUNTS BY ROUGHLY HALF: ~16 decision
>   points inside `analyze()` plus ~14 more nested in `_check_invocation_allowed` / `_check_call_expr_against_entries`.
>   The real target is ~30 branches.
> - The hard constraint _"the same command plus the same config must produce the same permission decision before and
>   after"_ and the success criterion _"the golden corpus replays with ZERO decision diffs"_ are both **SUPERSEDED** by
>   the user's ruling: _"This is not a refactor this is a rewrite and an improvement of what's there."_ The gate is an
>   AUTHORED specification that deliberately differs from current behaviour in the flagged cases. Execution during that
>   leaf's planning confirmed the current engine ALLOWS `cat ./README.md > "/etc/passwd"`, `echo x > "$HOME/.bashrc"`,
>   `echo x >> ~/.ssh/authorized_keys` and `cat < ~/.ssh/id_rsa` purely because of quoting style. A behaviour-preserving
>   rewrite would have frozen those four allows into the specification.
> - Leaf `20260914-213049`'s own plan survives the plugin move largely intact — its audit, adjudicated flag list (5
>   fail-open holes, 6 renames, 9 coverage gaps), specification design and `## Interface` hand-back are all
>   package-independent. Its paths change, and its outcome assertions must now be re-read against model B. Re-read it
>   rather than re-deriving it. NOTE: `tests/test_permission_decisions.py` does NOT exist yet — that leaf is planned,
>   not implemented, so its specification is still cheap to re-plan.

Everything below is settled at trunk level and applies across leaves. Read it before planning your slice; do not
re-derive it.

## What this rewrite is

A FULL REWRITE of the decision engine onto a recursive, immutable, copy-on-write value-object model. (The original
"behaviour-preserving" framing is superseded — see banner item D.) This engine gates every Bash tool call in every
Claude Code session; a silent regression here is a security regression.

The justification for choosing a full rewrite over an incremental strangler was that a faithful recursive model should
come in WELL BELOW the current 2334 lines, making incremental scaffolding waste. That expectation is checked at the end,
not assumed.

## The copy-on-write idiom — the mechanic every leaf applies

A `with_*` method performs a SHALLOW copy of self with only the changed value replaced on the new instance. Because
sub-values are themselves copy-on-write value objects, unchanged sub-values stay SHARED between copies rather than being
duplicated — only the one thing that actually changed is rebuilt, and it shares most of its own sub-values in turn. The
paradigm compounds: the more participants are copy-on-write, the more sharing you get. This is why Statement, Config,
AllowedCommand, SensitivePath, Filter, Parser and Policy are ALL value objects — a model where some links are mutable
would copy deeply or share unsafely at every step, losing the property the idiom exists for.

Explicitly rejected: `@dataclass(frozen=True)` with `dataclasses.replace` (frozen blocks ordinary attribute assignment
on the fresh copy, forcing `object.__setattr__` gymnastics around the very operation the idiom is built on), and the
bare mutable `@dataclass` style the file's five existing dataclasses use.

These are SMART value objects, not type wrappers: they know how to construct themselves from their sources via named
constructors, they know their own capabilities, and — per the config decision — they explain and warn about themselves.

NOTE there is no precedent in this repo to copy: zero frozen dataclasses, zero `dataclasses.replace`, zero `NamedTuple`,
zero `Enum`/`IntEnum`, zero `Protocol`/`Final`/`abstractmethod`, zero custom `__eq__`/`__hash__`/`__str__`/`__repr__`.
The nearest thing is `CommandAst` (`analyze-bash-command.py:1106`), the one self-declared value object: hand-written
`__init__`, private `_ast` behind a read-only property, a private `_from_ast()` bypass-constructor (`:1126`), and a
`with_heredoc_normalized_to_lit()` transformer (`:1160`). The chosen idiom is a deliberate new convention — decided
once, here, so every leaf spells it the same way.

## The decision pipeline and Pass ordering

A Statement holds its policies. Every rule is a Policy value object with the same shape — `for_statement(statement)`
binds it (returning a new copy-on-write instance), `matches()` says whether it applies, `decision()` yields its verdict.
This covers far more than the allowlist: blocked commands, sensitive variables, sensitive paths, command substitution,
allowlist entries with their filters, path validation, redirect path validation, the bypass wrapper and propose-allow
are all Policies.

Precedence is a declared property, not an artefact of code order: each policy carries a `.pass()` returning an ENUM
BACKED BY AN INT. The int backing gives a strict total order to sort by; the enum gives every position a NAME rather
than a magic number. sensitivePaths is pass 0, because a block there must override anything else.

THE ASYMMETRY EVERY LEAF SHOULD KNOW ABOUT: sorting by pass and taking the first match is NOT equivalent to today's
chain. Today's early returns are almost all DENY/ASK short-circuits, and `allow` is not a competing decision at all — it
is the FALLTHROUGH at `:1553`, reached only when nothing objected. The allowlist can say 'allowed' while redirect
validation, which runs later, still denies. The rule that preserves today's semantics is therefore likely 'passes order
the OBJECTIONS; the decision is the first objection in pass order; allow is the absence of any objection' — but that is
the planner's reading, to be confirmed against the specification, not adopted on argument. NOTE (2026-09-15): the new
outcome model simplifies this — with `ask` gone as a configurable outcome, the objection set is narrower.

## Naming

`AnalysisResult` becomes `PermissionDecision`. `BashCommandAnalyzer` ceases to exist — it is the documented '-er' smell
that triggered this work. Prefer domain language over technical primitives throughout (`shared-design-principles.md`,
`code-clarity.md` in `~/.claude/patterns/`). `Pass` and `RedirectOperator` would be the repo's first two enums — share
one convention rather than inventing two.

## Measured facts about the code being replaced

Verified by code-research against current HEAD, 2026-09-14/15. The coordinates originally captured in this trunk's draft
had DRIFTED and were corrected — do not trust any line number from an older note without re-checking.

- `analyze-bash-command.py` is 2334 lines. `BashCommandAnalyzer` (`:1391`) has 30 methods: `__init__`, ONE public
  `analyze` (`:1414-1553`), 28 private.
- `walk_ast` (`:874`) flattens the whole tree into a stream of every reachable dict node, discarding nesting and sibling
  order, across 11 call sites. `sole_command_call` (`:915`) and `redirect_targets_of` (`:971`) therefore RE-DERIVE
  structure from the flat stream. This is the mechanism the recursive Statement replaces.
- `_check_invocation_allowed` (`:1963`) tears its rich `CommandInvocation` into loose primitives at `:1971`.
  `_check_command_allowed`'s `call_exprs` parameter is plural with exactly one caller passing a single-element list —
  vestigial.
- The bare-string-to-entry-dict normalisation lives at `:2226-2229` and NOWHERE else, as a call-site transform inside
  `_check_command_allowed`; every other surface re-implements its own `isinstance` check.
- `config_loader.py` (182 lines) validates only five top-level scalar knobs — all five of them the DECISION KNOBS listed
  in banner section B. `allowedCommands` entries, `filters`, `allowedVariables`, `pathValidation`, `commandParser` and
  `propagate` are consumed as untyped dicts at maximum depth. It has SIX consumers: `analyze-bash-command.py`,
  `analyze-path.py`, `render_config.py`, `lint-config-on-write.py`, `session-start-render.py`,
  `subagent-start-render.py`.
- `AnalysisResult` (`:841-857`) carries exactly four decision strings: `allow` | `deny` | `ask` | `passthrough`. The
  translation to the hook protocol is the whole of `to_json_response()` (`:847-857`): allow/deny/ask map 1:1 onto
  `permissionDecision`, and `passthrough` returns `None` so the hook prints nothing and Claude Code falls through to its
  own logic. Note the vocabulary mismatch already present today: the knob VALUE `block` maps to the emitted decision
  `deny`.
- `ParsedResult.paths` is a shared bag with two unrelated consumers — `_check_path_validation` (`:1886`) and
  `PathsFilter` (`:686`) — so adding to it silently changes filter matching. Dissolve it into named concepts; do not
  preserve it.
- Three factory-driven families exist today: Parser (4 classes, `create_parser` `:738`), Filter (9 classes,
  `create_filter` `:762`), and free functions over raw dicts.
- `bin/` today holds: `bypass-shfmt-permissions`, `render-shfmt-permissions`, `propose-shfmt-permissions-user-allow`,
  `propose-shfmt-permissions-project-allow`, `shfmt-session-approvals`. Every one of these names carries the old plugin
  name and is user-facing.
- `scripts/analyze-path.py` (the Read/Grep/Glob analyzer on the same hook family) emits only `allow` or nothing, and has
  NO decision knob at all. Do not conflate it with the bash analyzer when reasoning about outcome configurability.

## The test suite is only partly a safety net

Of 371 tests in `tests/test_analyze_bash_command.py` (5015 lines): roughly 250-280 go solely through
`BashCommandAnalyzer(config).analyze(command)` and are implementation-independent — their ASSERTIONS are the decision
specification, though their call shape may change. Roughly 100-140 directly instantiate parser and filter classes,
inspect `CommandAst.ast`'s raw dict by hand, read `ParsedResult.paths`, or call the factories; 8 call the private
`_extract_arg_text_with_vars`. Those are a MIGRATION SURFACE, not a safety net.

CAUTION (2026-09-15): the ~250-280 "safe" behavioural tests are safe against REFACTORING, not against the new outcome
model. Every one of them that asserts `passthrough` or `ask` for a non-approved command asserts an outcome the new
engine will not produce. The size of that overlap is NOT yet measured and is a required input to re-cutting the leaf
stream.

## Environment and house constraints

- Python 3.13 is the tested runtime (`packages/shfmt-permissions/tests/shell.nix` pins `python313` + pytest + a real
  `shfmt`, which the engine shells out to).
- `from __future__ import annotations` and PEP 604 `X | None` unions are the established convention in
  `analyze-bash-command.py`; use them, not `Optional[...]`.
- There is NO `conftest.py` anywhere under `packages/shfmt-permissions/`. Each of the 8 test files independently
  re-implements the same `importlib.util` load of the hyphenated script filename, including the `sys.modules[...]`
  assignment needed for dataclasses with forward refs.
- `assert_config_is_reachable` (`tests/test_analyze_bash_command.py:53-73`) re-runs every test config through the real
  `validate_config`, so test configs cannot use knob values a real config round-trip would rewrite. No equivalent guard
  exists for `allowedCommands`/`filters` shapes.
- Every test builds config as an inline dict literal handed to `BashCommandAnalyzer(config)`; none call
  `load_config_from_files()`.
- Run the suite with: `cd packages/shfmt-permissions/tests && nix-shell --run \"pytest -v\"`.

## Working agreement for leaf sessions

Plan your slice to implementable depth: your own code-research, your own design questions, your own success criteria and
TODO. You are self-contained RELATIVE TO THIS TRUNK — you need not re-derive anything above, but plan deep on your own
slice. Write your `## Interface` section at finalize: what you produced, the contract downstream leaves consume, any new
dependency edges you discovered, and anything INTEGRATE must reconcile.

## This Improvement's Objective

TRUNK. Refactor the core of `packages/shfmt-permissions/scripts/analyze-bash-command.py` from an "-er"-style analyzer
operating on raw shfmt AST dicts into an immutable `Statement` value object with copy-on-write mechanics, carrying its
configuration and its permission policies as proper value objects and decomposing itself recursively to mirror the
shell's own nesting.

THE SHAPE THE USER WANTS (captured verbatim from the planning discussion, 2026-09-14):

```
statement = Statement
    .withAllowedCommands(
        config.get("allowedCommands")
              .map(allowedCommandDefinition => AllowedCommand.fromDefinition(allowedCommandDefinition))
    )
    .withSensitivePaths(...);

// then internally:
statement.withCommand("echo a; echo b");

// which does:
newInstance = self._copy();
newInstance.subCommands = [self.withCommand("echo a"), self.withCommand("echo b")];
return newInstance;
```

And the decision pipeline the statement's policies drive:

```
map(lambda policy: policy.decision(),
    filter(lambda policy: policy.matches(),
           map(lambda policy: policy.forStatement(self), self.policies)))
```

SCOPE: this is a FULL REWRITE of the engine on the recursive value-object model, not a strangler migration. It extends
beyond the analyzer to the config layer (`Config.fromText(...)` owning linting and rendering) and to the Filter, Parser
and Policy families, which all become copy-on-write value objects. Because that exceeds one planning or implementation
context, this improvement is a TRUNK subdivided into leaves — see the Leaf Stream. This file itself is planned and
implemented last, at INTEGRATE, by folding in what the leaves produced.

AS OF 2026-09-15 this trunk is MID-RE-PLAN: the rewrite moves to a new plugin (`command-policy`) and the engine's
OUTCOME MODEL has changed. See the re-plan banner at the top of Shared Context.

## Context / Why This Exists

**Origin / trigger:** Surfaced during the planning session for improvement `20260912-234028` (the redirect-target
allowlist gap). That session's design work kept colliding with the same structural problem from different angles: a rich
`CommandInvocation` is destructured back into loose primitives immediately after being built, so every new fact about an
invocation must be re-threaded through four signatures; config is passed around as raw dicts and `.get()`-ed deep inside
decision code; and the redirect gap itself exists because the AST's own recursive statement structure is flattened away
by a generic `walk_ast` before anything can reason about it. The user recognised the shared cause and described the
intended end state rather than accepting another patch.

**Consumer(s) of the output:** The engine's own maintainers and every future change to it. Downstream, every Claude Code
session depends on the engine's permission decisions. NOTE (2026-09-15): the original framing 'no user-visible behaviour
change intended' is SUPERSEDED — the new outcome model is a deliberate, user-visible behaviour change, and the model
(Claude itself) is now a first-class consumer of the engine's deny reasons, since those reasons are what steer it to an
approved alternative.

**Adjacent systems already covering part of the need:** Governed by the team patterns in `~/.claude/patterns/`:
`shared-design-principles.md` (the "-er" class smell, concept recognition, copy-on-write chains that read like the
process description) and `code-clarity.md` (domain language over technical primitives, the Yes/No test).
`BashCommandAnalyzer` is a direct instance of the documented "-er" smell. Related: improvement `20260912-234028` ships
the redirect-target fix FIRST as a small, independently reviewable change; this refactor should not block or be blocked
by it.

## Proposed Approach

SUBDIVIDED. This trunk is delivered through the leaves in the Leaf Stream, planned and implemented in dependency order
via the baton-pass chain. The cross-cutting design — the copy-on-write idiom, the policy pipeline and its Pass ordering,
the naming decisions, the corrected code coordinates, the test-suite split, and the environment constraints — is settled
and lives in `## Shared Context (For Leaves)` above, which every leaf reads.

THE LEAF BREAKDOWN, RE-CUT 2026-09-15 TO NINE LEAVES. The full ordered stream with per-leaf reasons is in
`## Leaf Stream` above; this section records WHY it cuts where it does.

The re-cut was forced by two things that post-dated the original six-leaf breakdown: the move to a new plugin
(`command-policy`) and the new outcome model. Between them they created six pieces of work that no existing leaf owned —
the package scaffold, the five user-facing `bin/` renames, the `shfmt-permissions` deprecation, the config-migration
skill, the deny+hint reason design, and the equivalence-search skill. Three leaves were added to own them.

WHAT CHANGED AND WHY:

1. **A package-scaffold leaf goes FIRST (`20260915-010936`, new).** This trunk was invalidated precisely because all six
   leaves were scoped as in-place edits under `packages/shfmt-permissions/` and the plugin move made every path wrong at
   once. Creating the real package before anything references it removes that entire class of failure rather than hoping
   each leaf re-derives paths correctly. It also gives every later leaf the `conftest.py` the old package never had. It
   deliberately touches no engine logic, so it stays small.
2. **The pipeline leaf was split in two (`20260914-213652` + `20260915-010959`, new).** The outcome model loaded the
   original pipeline leaf with the entire deny-reason surface and three escalation paths ON TOP of the rewrite's hardest
   correctness problem (reconstructing positional precedence as declared Pass ordering). Leaf 6 now owns the pipeline
   and the outcome VOCABULARY; leaf 7 owns what the engine SAYS when it denies, and the ways out of a denial. The
   interface between them is clean: leaf 6 defines the decision type, leaf 7 fills in its reason.
3. **The two skills got their own leaf (`20260915-011123`, new).** Both are skill-authoring work rather than engine
   work, and both read the same surface (`Config.explain()`'s rendered output), so they share a leaf and depend on the
   config leaf rather than on the engine leaves.
4. **The four value-object leaves keep their original boundaries** (`20260914-213153`, `-213321`, `-213502`, `-213652`).
   Nothing about the plugin move or the outcome model changed where the structural seams are; only their paths change,
   plus two additions of scope — the config leaf now also owns the death of four decision knobs and the config-key
   renames.
5. **The specification leaf keeps its position but needs re-planning (`20260914-213049`).** It moved from first to
   second (behind the scaffold) because it must place a test file, which needs the package. It was NOT split, despite
   self-reporting as oversized before any of the 2026-09-15 work landed — that call is left to its own re-planning
   session, which now also has the new outcome model to encode.

DEPENDENCY EDGES are set on each leaf's own `- Depends on:` Meta line, matching the stream order, so the orchestrator
dispatches them sequentially and cannot run a leaf ahead of its prerequisite.

AT INTEGRATE, this trunk folds the leaves' `## Interface` sections back into its own plan: the final architecture as
actually built, the real before/after line counts against the 2334-line starting point, and any cross-cutting follow-ups
the leaves surfaced.

MEASURED AST FACTS carried for the Statement leaf (probed against the live shfmt binary, 2026-09-14; re-verify if the
shfmt version changes):

1. Redirects attach at FIVE distinct nesting paths: `Stmts[0]`; `Stmts[0].Cmd.Y`; `Stmts[0].Cmd.Stmts[0]`;
   `Stmts[0].Cmd.Then[0]`; `Stmts[0].Cmd.Do[0]`.
2. A redirect belongs to a STATEMENT, and a statement is not always one command: `{ cat a; cat b; } > out.txt` -> Block,
   [cat, cat]; `if true; then cat a; fi > if.txt` -> IfClause, [true, cat]; `while read l; do cat a; done > wh.txt` ->
   WhileClause, [read, cat]; `(cat a; cat b) > sub.txt` -> Subshell, [cat, cat]; `cat a | tee b > out.txt` -> CallExpr,
   [tee].
3. `> /etc/passwd ; cat a` produces a statement with `Redirs` and NO `Cmd` — a redirect owned by no command at all.
4. Statement nodes carry NO `Type` field in shfmt's JSON. Identify statements by position or key presence, never by type
   string.
5. Redirect `Op` is an INTEGER (`>`=63, `<`=65, `<<`=71, `&>`=74), never read by the current code, with no mapping
   anywhere in the repo.

## Affected Components

**Files:**

- `packages/shfmt-permissions/scripts/analyze-bash-command.py` (2334 lines — the full
  BashCommandAnalyzer/CommandInvocation/ParsedResult/CommandAst cluster plus the Parser and Filter families)
- `packages/shfmt-permissions/scripts/config_loader.py` (182 lines — becomes `Config.fromText(...)` owning validation,
  warnings and explanation; `DECISION_KNOBS` `:123-129` and `VALID_*` `:37-41` are where four of five knobs die)
- `packages/shfmt-permissions/scripts/render_config.py` (rendering becomes `Config.explain()`)
- `packages/shfmt-permissions/scripts/lint-config-on-write.py` (linting becomes `Config.warnings()`)
- `packages/shfmt-permissions/scripts/session-start-render.py` (consumer of the render surface)
- `packages/shfmt-permissions/scripts/subagent-start-render.py` (consumer of the render surface)
- `packages/shfmt-permissions/scripts/analyze-path.py` (consumer of config_loader; allow-or-nothing, no decision knob)
- `packages/shfmt-permissions/scripts/propose_allow.py` (the third escalation path — fate unresolved)
- `packages/shfmt-permissions/scripts/parsers/` (per-program parsers invoked as external processes)
- `packages/shfmt-permissions/bin/bypass-shfmt-permissions` (branch 2 — already implements passthrough-to-dialog; needs
  rename)
- `packages/shfmt-permissions/bin/render-shfmt-permissions`
- `packages/shfmt-permissions/bin/propose-shfmt-permissions-user-allow`
- `packages/shfmt-permissions/bin/propose-shfmt-permissions-project-allow`
- `packages/shfmt-permissions/bin/shfmt-session-approvals`
- `packages/shfmt-permissions/hooks/hooks.json` (PreToolUse Bash matcher — the coexistence surface with a second plugin)
- `packages/shfmt-permissions/tests/test_analyze_bash_command.py` (5015 lines, 371 tests)
- `packages/shfmt-permissions/tests/test_new_parsers.py` (985 lines)
- `packages/shfmt-permissions/tests/test_config_loader.py` (504 lines)
- `packages/shfmt-permissions/tests/test_analyze_path.py` (442 lines)
- `packages/shfmt-permissions/tests/test_render_config.py` (381 lines)
- `packages/shfmt-permissions/tests/test_render_hooks.py` (85 lines)
- `.claude-plugin/marketplace.json` (shfmt-permissions currently at version 6.1.2; command-policy needs registering)
- `docs/knowledgebase/shfmt-permissions.md` (554 lines — CASE A's documented silence is reversed by the new outcome
  model)

**Classes/Functions:**

- BashCommandAnalyzer (the '-er' smell being dissolved — ceases to exist)
- CommandInvocation
- ParsedResult / ParsedOption / ParsedPositional
- CommandAst
- AnalysisResult (becomes PermissionDecision; its four-value vocabulary is what the new outcome model rewrites)
- The Parser family: DefaultParser, StructuredParser, CommandParser, ProvidedParser
- The Filter family: ParameterRegexFilter, MatchFullParameterFilter, PositionalArgRegexFilter, ArgumentAtIndexFilter,
  PositionalArgAtIndexFilter, NamedValueFilter, OptionValueFilter, OptionPresentFilter, PathsFilter
- walk_ast / sole_command_call / command_word_of / redirect_targets_of / sole_invoked_program (free functions over raw
  dicts)
- `_describe_filter` / `_derive_filter_alternative` (`:2159-2209` — the existing mechanical hint machinery the deny+hint
  design builds on)
- `_check_propose_allow` (`:1635-1701`) / `_ast_is_bypass_wrapped` (`:1020-1037`)
- New: Statement, Config, AllowedCommand, SensitivePath, RedirectOperator, Policy, Pass, PermissionDecision

**Modules:**

- shfmt-permissions (source)
- command-policy (new target package)

## Implementation Notes

THIS FILE IS A TRUNK. Its own implementation happens at INTEGRATE, after every leaf in the Leaf Stream is done — it
folds the leaves' `## Interface` sections into a final account of what was built. The substantive planning and
implementation live in the leaves.

The cross-cutting design that every leaf needs is in `## Shared Context (For Leaves)`, not here. This section records
only what is specific to the trunk's own integrate-time work.

## Re-plan status (2026-09-15)

This trunk is MID-RE-PLAN and the leaf chain is halted. Resolved: the plugin move to `command-policy`, the
additive/deprecate-only cutover, the skill-based config migration, and the new outcome model (deny+hint by default,
passthrough only via an explicitly named bypass wrapper, hints deterministic and model-facing). Not yet resolved: the
bypass-vs-sensitive-path-veto conflict, any deprecation forcing function, the fate of propose-allow, parse-failure
behaviour, and — the big one — the re-cut of the leaf stream itself.

## Open Questions (for INTEGRATE)

- Did the rewrite actually come in well below 2334 lines? That expectation was the explicit justification for choosing a
  full rewrite over an incremental strangler. If it did not, that is worth writing down honestly — it is the kind of
  prediction that should be checked rather than quietly dropped.
- Did the Pass ordering reconcile cleanly with today's positional precedence, or did the specification reveal orderings
  that resisted declaration? Today's chain places sensitive paths NINTH, while the Pass decision puts sensitivePaths at
  pass 0 — whether the current position was incidental or load-bearing belongs in the trunk's final account.
- Did any leaf surface a cross-cutting discovery that needs a follow-up improvement rather than a silent reopen of an
  earlier leaf?
- Did `shfmt-permissions` ever actually get retired, or is it still installed and serving its known fail-open holes? The
  cutover decision deliberately left that unforced; INTEGRATE should record the real state rather than the intent.

## Note on the improvement this depends on

`20260912-234028` (the redirect-target allowlist fix) shipped first, deliberately, as a small independently reviewable
change. This rewrite must carry the behaviour that improvement established — the redirect-target validation across all
five nesting shapes is part of the decision specification, not something to redesign.

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions, with the authored decision
specification from leaf `20260914-213049` as the implementation-independent specification above the test suite. The
~250-280 behavioural tests are the decision specification and must keep asserting the same decisions where the new
outcome model still permits it; the ~100-140 internals-coupled tests are a migration surface, not a safety net, and get
rewritten against the new model. New value-object behaviour is driven test-first in each leaf.

## Observed during exploration

Incidental findings surfaced while re-planning this trunk, recorded so they are not silently lost. Default action for
each is to leave it alone — none is in this trunk's scope.

- **The improvement plugin has no supported way to halt a `ready-to-implement` improvement.**
  `ready-to-implement → planned` does not exist and `ready-to-implement → blocked` is explicitly forbidden (must route
  through `in-progress`, which stamps the set-once `Impl started` and fabricates an implementation that never happened,
  corrupting `improvement-timings`). `queue-planner` has no output slot for "halted", only
  `next`/`defer`/`in_progress`/`blocked`/ `unrunnable`. The only honest options today are a prose notice the dispatch
  path need not honour, or a hand-edit outside the authoritative status-updater — both of which happened on leaf
  `20260914-213049`. **Worth its own improvement:** a `halted`/`on-hold` status, or a legal reopen transition back to
  `planned`, plus a `queue-planner` slot for it. This affects every trunk/leaves chain, not just this one.
- **The repo's markdown-formatter hook corrupts underscore-heavy identifiers written outside code spans in improvement
  files.** Observed live during this session's `improvement-writer` pass: `config_loader.py DECISION_KNOBS` became
  `config*loader.py`, `BashCommandAnalyzer.__init__` became `BashCommandAnalyzer.**init**`, and
  `__eq__`/`__hash__`/`__str__`/`__repr__` were bolded or stripped — the formatter reads `_` and `__` as markdown
  emphasis. The writer detected and repaired it, but only because it swept for the damage afterwards. Mitigation that
  works: always wrap such identifiers in backticks. A silent corruption of a line number or a dunder name in a plan is
  the kind of thing a later implement session would build to.
- **`commandParser.fallback: "deny"` does not deny.** Its `"deny"` value routes through `_build_filter_rejection_result`
  and is therefore resolved by `filterRejectionResponse` — default `passthrough`. So a config author who sets a parser's
  `fallback` to `"deny"` gets `passthrough` unless they separately set `filterRejectionResponse` to `"deny"`. Its
  `"ask"` value likewise does not emit `ask`; it just `continue`s to the next matching entry. Only `"legacy"` has a
  distinct effect. This is a live naming trap in shipped config semantics, independent of the rewrite — and one the new
  outcome model partly erases anyway by killing `filterRejectionResponse`.

## Assumptions

- **The line numbers captured in the original draft are accurate against current HEAD** — refuted (code-research against
  HEAD 2026-09-14: `_check_invocation_allowed` is at `:1963` and the tear-into-primitives call at `:1971`; bare-string
  normalisation is at `:2226-2229`. Only `_check_path_validation` (def `:1886`) and `PathsFilter` (class `:686`) were
  approximately right. Every structural smell the draft describes still holds — only the coordinates drifted. Corrected
  numbers are in Shared Context; the stale ones must not be carried into any leaf.)
- **The existing test suite is a safety net whose decisions are the specification, and it can stay green throughout the
  refactor** — refuted (Of 371 tests in `test_analyze_bash_command.py` (5015 lines), roughly 250-280 go solely through
  the public `analyze()` route; roughly 100-140 instantiate parser/filter classes directly, inspect `CommandAst.ast`'s
  raw dict, read `ParsedResult.paths`, or call the factories, and 8 call the private `_extract_arg_text_with_vars`.
  Those break BY DESIGN. Compounded 2026-09-15: even the 'safe' 250-280 are safe against refactoring, not against the
  new outcome model — any that assert passthrough/ask for a non-approved command assert an outcome the new engine will
  not produce.)
- **`config_loader.py` is consumed only by the bash analyzer, so changing its contract is contained** — refuted (SIX
  consumers: `analyze-bash-command.py`, `analyze-path.py`, `render_config.py`, `lint-config-on-write.py`,
  `session-start-render.py`, `subagent-start-render.py`.)
- **There is an existing repo precedent for frozen dataclasses, dataclasses.replace, NamedTuple, or Enum that the new
  value objects should match** — refuted (None exists. All 6 dataclasses in the repo are bare and mutable; zero uses of
  `frozen=True`, `dataclasses.replace`, `NamedTuple`, `namedtuple`, `Enum`, `IntEnum`, `Protocol`, `Final` or
  `abstractmethod`, and zero custom `__eq__`/`__hash__`/`__str__`/`__repr__`. The only self-declared value object is
  `CommandAst`, which is hand-rolled. The chosen idiom is a deliberate new convention, pinned once in Shared Context so
  every leaf spells it identically.)
- **The bare-string to entry-dict normalisation of allowedCommands happens in exactly one place** — confirmed
  (`analyze-bash-command.py:2226-2229`, inside `_check_command_allowed`, synthesising
  `{"program": entry, "filters": []}`. A call-site transform, not a load-time one, so every other surface reading
  `allowedCommands` sees the raw string/dict mix. Two downstream behaviours depend on the synthesised shape:
  `_args_to_parse_if_entry_permits_variables` (`:1976`) relies on the absent `allowedVariables` key meaning 'permits no
  variables', and `:2039` relies on the empty `filters` list meaning 'always allowed once the program matches'.)
- **Every test constructs config as a plain dict literal passed directly to the BashCommandAnalyzer constructor** —
  confirmed (`tests/test_analyze_bash_command.py:76-96` — the `analyze()`/`assert_decision()` helpers take a dict and
  pass it unchanged to `BashCommandAnalyzer(config)`. No test in the bash-analyzer suite calls
  `load_config_from_files()`. Under the `Config.fromText` decision the test helpers are themselves a migration surface.)
- **Python 3.13 is the runtime the suite is tested against, so modern typing syntax is safe** — confirmed
  (`packages/shfmt-permissions/tests/shell.nix:4-5` pins `pkgs.python313` and `pkgs.python313Packages.pytest` and
  provisions real `shfmt`. `analyze-bash-command.py:18` already carries `from __future__ import annotations` and uses
  PEP 604 unions throughout.)
- **Sorting policies by a declared Pass and taking the first match reproduces today's decision precedence** — unverified
  (Depends on design that does not exist yet (the Pass assignment per branch) and evidence that does not exist yet (the
  authored specification from leaf `20260914-213049`, whose test file is not written). The planner's analysis is that it
  does NOT reproduce it naively, because today's `allow` is the fallthrough at `:1553` rather than a competing decision.
  Recorded as unverified deliberately: the single highest-risk claim in the rewrite. The 2026-09-15 outcome model
  narrows it somewhat by removing `ask` as a configurable outcome.)
- **The engine has exactly five outcome-selecting config knobs, and the new outcome model kills four of them** —
  confirmed (`config_loader.py` `DECISION_KNOBS` (`:123-129`) and `VALID_*` sets (`:37-41`) declare exactly five:
  `defaultDecision` {passthrough, ask} default passthrough; `sensitiveVariableResponse` {ask, block} default ask;
  `commandSubstitutionResponse` {block, ask, via-allowed-commands} default via-allowed-commands;
  `pathValidationResponse` {passthrough, ask, deny} default passthrough; `filterRejectionResponse` {passthrough, ask,
  deny} default passthrough. Under deny-by-default, four collapse to a constant; only `commandSubstitutionResponse`
  retains a meaningful (matching, not outcome) choice. Note `defaultDecision` cannot even express 'deny' today — an
  invalid value is silently reset by `_fall_back_invalid_knob` (`:132-153`).)
- **Branch 2 of the new model (force a command through manual approval) has to be built** — refuted (It already exists.
  `bin/bypass-shfmt-permissions` plus `_ast_is_bypass_wrapped` (`:1020-1037`) already return
  `AnalysisResult('passthrough', BYPASS_REASON)` at `:1448-1453`, before every other rule; `to_json_response()`
  (`:847-857`) maps passthrough to `None` so the hook prints nothing and Claude Code's own dialog takes over. What is
  genuinely new is the rename to bypass-policy and the default flip that makes it worth reaching for. Its 'sole command
  on the line' recognition (`sole_invoked_program` `:962-968`, `COMMAND_HIDING_NODE_TYPES` `:899-912`) exists to stop
  denylist smuggling and must survive intact.)
- **There is currently no unescalatable hard-deny class, so making bypass universal changes nothing** — refuted (The
  shell-performed-redirect veto (`:1438-1446`, reason text `:1085-1099`) already hard-denies a bypass-wrapped line whose
  own shell redirect targets a sensitivePaths entry, and states in its own reason text that 'The veto is absolute —
  rewrite the line without a redirect to a sensitive path (wrapping it differently cannot help).' The chosen 'escalates
  anything' answer deletes this guard; flagged for re-confirmation.)
- **The trunk's halt of leaf `20260914-213049` was applied — its status was reverted to planned** — refuted (Measured
  2026-09-15: that leaf's Meta line reads `- Status: ready-to-implement`. The halt exists only as prose in this trunk's
  banner and was never applied to the leaf file, leaving it dispatchable by the orchestrator against a superseded
  outcome model.)
- **Leaf `20260914-213049`'s authored specification already exists as a file, so changing it is expensive** — refuted
  (`packages/shfmt-permissions/tests/test_permission_decisions.py` does not exist. That leaf is planned, not implemented
  — its specification is still only a plan and is cheap to re-plan against the new outcome model.)
- **A richer deny hint would need new plumbing to reach the config data it wants** — confirmed (No plumbing needed.
  `BashCommandAnalyzer.__init__` (`:1405-1412`) stores the entire merged config as `self.config`, and every
  reason-building method (`_build_filter_rejection_result`, `_describe_filter`, `_derive_filter_alternative`,
  `_check_command_allowed`, `_check_call_expr_against_entries`) is an instance method with full access to it, including
  the complete `allowedCommands` list for every program. The code simply does not use that scope today — only new logic
  is needed, not new wiring.)

## Design Decisions

### Scope of the refactor: full rewrite vs incremental strangler

- **Chosen:** Full rewrite of the engine on the recursive value-object model, rather than a strangler migration or a
  split into sequential improvements
- **Rationale:** User: 'Pretty sure it's better to think of this as a full rewrite. On the other hand I'm pretty sure
  we'll come in way below 2335 lines of code with that proper recursive design.' If the faithful recursive model
  collapses much of the current code, an incremental migration means building and maintaining scaffolding for code that
  is destined to be deleted — paying the integration cost twice.
- **Rejected alternatives:** Statement core only, with config value objects as a sibling improvement; config value
  objects first and Statement second; strangler migration introducing Statement alongside and moving decision paths one
  at a time
- **Date:** 2026-09-14

### Config representation and the fate of config_loader

- **Chosen:** Replace config_loader's dict-returning functions with a `Config` value object built through a named
  constructor, `Config.fromText(...)`. Linting and rendering become behaviour OF the value objects: `Config.warnings()`
  aggregates the warnings of every value object it constructed and becomes the lint output, and `Config.explain()`
  renders by asking each value object to explain what it does and what it constrains.
- **Rationale:** User's design. Today the bare-string-to-entry-dict normalisation exists at exactly one call site
  (`:2226-2229`) scoped to `_check_command_allowed`, so the other five config consumers each re-implement their own
  `isinstance` handling; and `config_loader` validates only five scalar knobs while everything structural is read raw at
  maximum depth. Making the value objects responsible for their own validity, warnings and self-description collapses
  four parallel surfaces into thin callers of one model.
- **Rejected alternatives:** Constructing the value objects only inside `BashCommandAnalyzer.__init__`; a new
  value-object module adopted surface-by-surface; leaving `config_loader` returning a plain dict and typing only the
  analyzer's own edge
- **Date:** 2026-09-14

### Python copy-on-write idiom for the value objects

- **Chosen:** Hand-rolled smart immutable value objects. A `with_*` method performs a SHALLOW copy of self with only the
  changed value replaced on the new instance; unchanged sub-values stay SHARED between copies.
- **Rationale:** User: immutable value objects are smart in their coding style, and the paradigm compounds — 'it gets
  better the more copy-on-write objects we use because they stay shared among copies until changed and thus creating a
  new copy of themselves - in the best case still sharing most of their values because their sub-values are also
  copy-on-write and thus sharable. Only ever rebuilding one small thing that actually changed while sharing everything
  else.' This is structural sharing / persistent-data-structure semantics, and it is also why `frozen=True` is a poor
  fit: frozen blocks ordinary attribute assignment on the fresh copy, forcing `object.__setattr__` gymnastics around the
  very operation the idiom is built on.
- **Rejected alternatives:** `@dataclass(frozen=True)` with `dataclasses.replace` hidden behind domain-named `with_*`
  methods; a hand-rolled plain class following the existing `CommandAst` precedent literally; a bare mutable
  `@dataclass` matching the file's other five dataclasses
- **Date:** 2026-09-14

### Which concepts become copy-on-write value objects

- **Chosen:** Not only `Statement` and a permission-policy concept, but also the Filter and Parser families — the whole
  model becomes copy-on-write value objects.
- **Rationale:** User: 'Not just Policy, also Filter, Parser. As stated the copy on write paradigm gets better the more
  we use it.' Structural sharing only pays off when the sub-values are themselves copy-on-write; a model where Statement
  is immutable but holds mutable filter and parser objects would copy deeply or share unsafely at every step.
- **Rejected alternatives:** A separate policy concept with Statement modelling shell structure only and the
  filter/parser families left as plain classes; Statement carrying the config directly with no separate policy concept
  at all; deferring the split to the TDD refactor phase
- **Date:** 2026-09-14

### Whether to subdivide this improvement into a trunk with leaves

- **Chosen:** Subdivide. This file becomes the TRUNK; the cross-cutting design goes into Shared Context, and leaves are
  planned and implemented in dependency order through the baton-pass chain.
- **Rationale:** The chosen scope — a full rewrite of a 2334-line engine, plus the config layer, plus four render/lint
  surfaces, plus 13 filter and parser classes, plus ~100-140 test migrations across six config consumers — cannot be
  planned to implementable depth in one context, and each proposed leaf has a genuinely clean interface for the next to
  consume from files alone.
- **Rejected alternatives:** Planning it inline as a single improvement; subdividing along different leaf boundaries
- **Date:** 2026-09-14

### Composition direction between Statement and the permission rules

- **Chosen:** The Statement HOLDS its policies, and the decision is a pipeline over them. Every rule — not just
  allowlist entries with their filters, but sensitive paths, blocked commands, sensitive variables, command
  substitution, path validation, redirect validation, bypass and propose-allow — is a Policy value object with the same
  three-method shape.
- **Rationale:** User's own formulation. Statement-holds-policy is what makes copy-on-write actually pay off during
  recursive decomposition: sub-statements inherit the policies by structural sharing rather than being re-paired with
  them by a caller. The user noted this was broader than they had initially framed it — the original sketch was about
  resolving `allowedCommands` with its filters, and the Policy concept turns out to cover sensitivePaths and every other
  rule equally.
- **Rejected alternatives:** A policy object that receives a Statement and returns a decision; Statement carrying config
  VOs for sharing while a separate policy owns the decision method; deferring the split to the TDD refactor phase
- **Date:** 2026-09-14

### How multiple policy decisions combine — precedence in the pipeline

- **Chosen:** Each Policy carries a `.pass()` returning an ENUM BACKED BY AN INT, and the pipeline sorts by it.
  sensitivePaths is pass 0.
- **Rationale:** User's resolution of a problem raised during planning: today's `analyze` is an ordered chain of early
  returns, so exactly ONE decision is ever produced and its precedence is implicit in the ORDERING OF THE CODE. A
  declarative map/filter/map produces many decisions, so precedence has to become explicit or it is silently lost.
- **Rejected alternatives:** First matching policy wins with no declared ordering; most-restrictive-decision-wins
  regardless of order; leaving the combination rule to emerge during implementation
- **Date:** 2026-09-14

### Name of the result concept

- **Chosen:** `PermissionDecision`, replacing `AnalysisResult`
- **Rationale:** Domain language over technical primitives — the thing produced is a decision about permission, not an
  'analysis result'. It also retires the analyze/analysis vocabulary alongside `BashCommandAnalyzer` itself, so the
  '-er' smell does not survive in the name of its output.
- **Rejected alternatives:** `Decision` (shorter, but loses the qualifier at call sites far from that context); keeping
  `AnalysisResult` to avoid churning every test that asserts on a result
- **Date:** 2026-09-14

### Whether RedirectOperator is in scope

- **Chosen:** Yes, modelled in the Statement leaf alongside the recursive decomposition
- **Rationale:** The redirect gap is the original trigger for the whole refactor, and redirects belong to statements.
  Today `Op` is never read at all and the integers (`>`=63, `<`=65, `<<`=71, `&>`=74) have no mapping, constant set or
  fixture anywhere in the repo, so a named concept is the difference between a magic 63 and a readable one.
- **Rejected alternatives:** Modelling it only once a decision actually needs to distinguish redirect operators; leaving
  it out of scope entirely
- **Date:** 2026-09-14

### Cutover strategy for retiring shfmt-permissions in favour of command-policy

- **Chosen:** Additive, deprecate only — build `command-policy` alongside an untouched `shfmt-permissions`, mark the old
  one deprecated in its description, no forced removal; users migrate on their own schedule
- **Rationale:** User, verbatim: _"I want the rewrite as soon as possible because I'm expecting great things from it. So
  I'm forcing one more reason onto myself to make it happen fast. Also: redirects haven't been looked at at all until a
  few improvements ago and that didn't break yet. They'll hold one more day until we're done with this."_ Two distinct
  arguments, both worth preserving: (1) the open exposure is treated as a DELIBERATE FORCING FUNCTION — a self-imposed
  incentive to ship the rewrite rather than let it drift; (2) an empirical risk read — redirect handling received no
  scrutiny at all until a few improvements ago and nothing broke, so the exposure window has in practice been open far
  longer than this plan extends it, making the marginal added risk small.
- **PLANNER NOTE, not a disagreement:** the risk acceptance is calibrated to "one more day", and the re-cut chain is
  nine leaves. If it stretches well beyond that, the acceptance is worth revisiting rather than inheriting silently — a
  forcing function only functions while the deadline it implies is still believed.
- **Rejected alternatives:** Flag-day rename (git-mv packages/shfmt-permissions to packages/command-policy in one
  commit, remove the old marketplace entry — no coexistence window, no double-hook risk, closes the fail-open holes at
  the same commit that opens the new engine); coexist behind an explicit switch with a mechanism preventing both
  PreToolUse hooks from firing
- **Date:** 2026-09-15

### Whether to fix the five fail-open holes in the current plugin now, separately

- **Chosen:** No — leave them. They close when the rewrite lands.
- **Rationale:** Same reasoning as the cutover decision, given in the same breath. The exposure is deliberately retained
  as a forcing function for shipping the rewrite fast, and the empirical read is that redirect handling went entirely
  unexamined until a few improvements ago without incident, so the incremental risk of holding is small. Doing the fix
  twice — once on an engine being deleted, once in the specification the rewrite is built to — was the cost avoided.
- **What is being accepted, stated plainly so it is not lost:** leaf `20260914-213049` confirmed BY EXECUTION that
  today's engine ALLOWS `cat ./README.md > "/etc/passwd"`, `echo x > "$HOME/.bashrc"`,
  `echo x >> ~/.ssh/authorized_keys` and `cat < ~/.ssh/id_rsa`, purely on quoting style. These are ACTIVE ALLOWS from a
  redirect check that mishandles quoting, not fallthroughs — so the new deny-by-default model does NOT close them
  either; only the corrected redirect validation in the rewrite's specification does. `shfmt-permissions` remains the
  engine everyone actually uses for the whole duration of the chain.
- **Rejected alternatives:** Fix them now as a small separately-reviewable improvement against `shfmt-permissions`,
  letting the rewrite inherit the fix via its specification (ships in days rather than after nine leaves); triage the
  five and patch only the subset reachable without contrivance
- **Date:** 2026-09-15

### Config migration path from shfmt-permissions.json to command-policy.json

- **Chosen:** A migration SKILL the user runs; no code in the engine that auto-detects an un-migrated config and no
  fallback to the old path
- **Rationale:** User: 'add a skill to migrate but no code to automatically do detect the need to do that'. Keeps the
  engine itself free of compatibility branching — the thing that gates every Bash call stays a single clean read of a
  single path — while still not leaving users to hand-edit JSON. PLANNER NOTE: because the new outcome model deletes
  four decision knobs, this skill must perform a SEMANTIC migration, not a rename; a config copied across verbatim is
  not an equivalent config, and a user whose config leaned on `defaultDecision: passthrough` gets a materially stricter
  engine.
- **Rejected alternatives:** Auto-fallback with a one-time warning (read command-policy.json if present, else read
  shfmt-permissions.json); fail closed until migrated (only hardcoded safe defaults apply until the new file exists);
  documentation-only manual migration with no tooling
- **Date:** 2026-09-15

### Scope of the bypass-policy escape hatch — is any deny unescalatable?

- **Chosen:** The shell-performed-redirect veto STAYS ABSOLUTE and unescalatable. `bypass-policy` escalates anything
  else, but a shell redirect into a `sensitivePaths` entry is denied no matter how the line is wrapped.
- **Rationale:** RESOLVED 2026-09-15 after the planner surfaced that this contradicted shipped behaviour. The first
  answer given ("escalates anything, hard-deny class prompts louder") was made against an abstract framing of Pass 0
  that did not put the existing guard in front of the user. The guard is concrete: the shell-performed-redirect veto
  (`:1438-1446`, reason text `:1085-1099`) already hard-denies `bypass-shfmt-permissions cat <<EOF > /etc/shadow`, on
  the explicit grounds that the redirect is performed by the CALLING SHELL and not by the wrapped program — so the
  wrapper cannot legitimately vouch for it. Its own reason text states: 'The veto is absolute — rewrite the line without
  a redirect to a sensitive path (wrapping it differently cannot help).' Once shown the concrete behaviour the user
  chose to keep it. This also preserves the meaning of `sensitivePaths` sitting at Pass 0.
- **Rejected alternatives:** Universal escalation with a louder prompt for the sensitive class (the initial answer,
  reversed once the existing veto was surfaced — it would have deleted a deliberate guard and reduced it to a
  human-attention guard); universal escalation with a uniform prompt and no louder variant; keeping the redirect veto
  while escalating the rest of the sensitive class with a louder reason string
- **Date:** 2026-09-15 (superseding an earlier same-day answer)

### The two named escalation paths produce DIFFERENT outcomes

- **Chosen:** `bypass-policy` produces **"no opinion"** (`passthrough` — the hook prints nothing and Claude Code's own
  permission logic takes over). Only `add-allow-policy` (the renamed propose-allow path) forces **`ask`**, carrying its
  JSON diff into the dialog. So `ask` remains reachable only by explicitly naming a program that requests it — and only
  one of the two programs requests it.
- **Rationale:** User: 'Named escalation sounds good but bypass should produce as "no opinion" response. Only
  add-allow-policy should force "ask" here'. This matches shipped behaviour for bypass (`:1448-1453` already returns
  `AnalysisResult("passthrough", BYPASS_REASON)`) and for propose-allow (`_check_propose_allow` `:1635-1701` always
  forces `ask`). The distinction is real and worth stating: `passthrough` is NOT `ask`. Bypass abstains and lets the
  surrounding Claude Code permission configuration decide; propose-allow demands a human look at a diff.
- **PLANNER CONSEQUENCE, recorded rather than silently encoded:** because bypass abstains rather than prompting, the
  strength of deny-by-default rests partly OUTSIDE this plugin. If the user's own `settings.json` already permits the
  pattern, or the session runs in an accepting permission mode, `bypass-policy <anything>` auto-approves with no human
  ever seeing it; in a `bypassPermissions` session it is a free pass. This is today's behaviour too, so it is not a
  regression — but the existing `BYPASS_REASON` string asserts 'falls through to Claude Code's own permission dialog.
  This counts as a user intervention', and that second sentence is not reliably true. The leaf that owns the escalation
  paths should correct that wording rather than port it.
- **Rejected alternatives:** Both paths force `ask` (loses bypass's abstain semantics and overrides the user's own
  permission configuration); fold propose-allow into the deny hint and drop the separate program (loses the one-step
  propose-and-approve-with-a-diff property); defer the whole question to the policy-pipeline leaf
- **Date:** 2026-09-15

### Parse-failure behaviour under deny-by-default

- **Chosen:** Keep `passthrough`. When `shfmt` is missing, times out, or returns unparseable JSON, the engine still
  abstains rather than denying.
- **Rationale:** Deliberate fail-open, chosen against the grain of the otherwise deny-by-default model. Fail-closed here
  would mean a missing or broken `shfmt` binary denies EVERY Bash command in every session — that reads as a total
  outage, not a security posture, and the failure mode is indistinguishable to the user from the plugin being broken.
  The surrounding Claude Code permission flow still gates the command. Note this is the one place the new model
  deliberately does NOT deny on non-approval, and it is an availability decision, not a security one.
- **Rejected alternatives:** Deny — fail closed (consistent in principle, but a broken install bricks all Bash usage);
  deny with the hint naming the analyzer itself as the cause and pointing at `bypass-policy` (diagnosable, but still
  bricks the common case)
- **Date:** 2026-09-15

### How rich the deny hint should be

- **Chosen:** Near-miss derived mechanically from the rule that actually fired, PLUS a pointer in the deny reason to a
  skill/agent that searches for an equivalent approved command by reading the RENDERED rules
- **Rationale:** User: 'near miss derived + reference a skill or agent that looks for the equivalent command based on
  the rules rendering'. This resolves the rot problem that the existing code explicitly refuses to take on —
  `_derive_filter_alternative` (`:2183-2186`) declines to build a command-equivalence table because it 'would rot like
  hand-written prose'. Delegating cross-command equivalence to a skill that reads the live rendered config at need means
  there is no authored map to drift: the equivalence search always runs against the config as it actually is. It also
  composes with the already-decided `Config.explain()` surface and the existing `bin/render-shfmt-permissions`.
- **Rejected alternatives:** Near-miss only, with no cross-command help at all (weakest when the program is not
  allow-listed at all); near-miss plus a statically authored equivalence map (find -> rg --files, sed -i -> Edit tool)
  that someone owns forever and that drifts from the real allowlist; dumping the allow-listed programs into the deny
  reason and letting the model sort it out
- **Date:** 2026-09-15

### Source of the 'ai hints' in a deny reason

- **Chosen:** Deterministic — computed by plain code from the config and the rejection reason, consumed BY the model. No
  LLM call inside the hook.
- **Rationale:** User confirmed. An LLM call at deny time would add latency to every denied Bash call and put
  nondeterminism inside a security control, directly contradicting the plugin description settled the same day
  ('Deterministic, rule-based permission decisions... Same input, same verdict, every time — no model judgment in the
  loop'). The phrase 'ai hints' means hints FOR the AI, not hints FROM one. Cheap to confirm, expensive to get backwards
  — a later reader implementing an LLM call here would break the plugin's stated identity.
- **Rejected alternatives:** Consulting a model at deny time to phrase or choose the suggestion
- **Date:** 2026-09-15

## Success Criteria

- [ ] Every leaf in the (re-cut) Leaf Stream reaches status done, each with its `## Interface` section written
- [ ] SUPERSEDED — 'the golden corpus replays with ZERO decision diffs'. Replaced by: the authored decision
      specification from leaf 20260914-213049, re-read against the new outcome model, passes in full
- [ ] The new outcome model holds end to end: a non-approved command is DENIED with a reason that names a viable
      approved alternative where one is derivable; `bypass-policy <cmd>` is the only route to the Claude Code dialog; no
      config knob can restore a lenient default
- [ ] The four dead decision knobs (defaultDecision, sensitiveVariableResponse, pathValidationResponse,
      filterRejectionResponse) no longer exist anywhere — not in the engine, not in config validation, not in the
      rendered explanation, not in the knowledgebase
- [ ] `cd packages/<package>/tests && nix-shell --run "pytest -v"` is green across every test file
- [ ] Behavioural tests that asserted `passthrough`/`ask` for non-approved commands have been deliberately
      re-adjudicated against the new model — each one either re-asserted under deny+hint or consciously removed, none
      silently dropped
- [ ] The ~100-140 internals-coupled tests are rewritten against the new model rather than deleted — the behaviour they
      pin is still pinned
- [ ] `BashCommandAnalyzer`, `walk_ast`, `create_parser`, `create_filter` and `AnalysisResult` no longer exist
- [ ] No surface anywhere still reads the config as a raw dict; `Config.warnings()` is the lint output and
      `Config.explain()` the render output
- [ ] `command-policy` is registered in marketplace.json and installable; `shfmt-permissions` is marked deprecated in
      its description and left otherwise untouched
- [ ] A config-migration skill exists and covers the SEMANTIC migration (dead knobs, renamed keys), not just the
      filename change
- [ ] The real before/after line counts of the engine are recorded against the 2334-line starting point — the
      full-rewrite justification is checked, not assumed

## Implementation TODO

- [ ] Update status to in-progress
- [ ] INTEGRATE ONLY — this trunk's own work happens after every leaf is done. The leaves carry the implementation.
- [ ] Read every leaf's `## Interface` section and fold what they produced into this trunk's account of the final
      architecture
- [ ] Record the real before/after line counts of the engine against the 2334-line starting point, and state plainly
      whether the full-rewrite justification held
- [ ] Record how the Pass ordering reconciled with today's positional precedence — in particular whether sensitive
      paths' current ninth position was incidental or load-bearing
- [ ] Verify the authored decision specification passes in full and the full suite is green across every test file
- [ ] Verify the new outcome model holds end to end (deny+hint default, bypass-policy the only passthrough route, no
      knob can restore leniency) and that `command-policy` is registered and `shfmt-permissions` deprecated
- [ ] Raise any cross-cutting discovery a leaf surfaced as a follow-up improvement rather than silently reopening a
      finished leaf
- [ ] Update status to completed
