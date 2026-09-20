# Improvement 20260914-213153: Config Value Object

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-14
- Updated: 2026-09-17
- Plan started: 2026-09-15T13:15:09+02:00
- Plan finished: 2026-09-15T16:27:37+02:00
- Impl started: 2026-09-16T23:58:54+02:00
- Impl finished: 2026-09-17T00:09:53+02:00
- Trunk: 20260914-195111
- Kind: decomposed
- Depends on: 20260914-213049

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`

## Context / Why This Exists

**Origin / trigger:** Measured 2026-09-14 against the old shfmt-permissions code: the bare-string-to-entry-dict
normalisation is duplicated across two modules (corrected 2026-09-15 from an original 'exactly one call site' claim),
and config_loader.validate_config validates only five top-level scalar knobs, descending into nothing else. Also
required as leaf 3 of trunk 20260914-195111 because filters/policies are constructed FROM config value objects — the
config model must exist before them.

**Consumer(s) of the output:** Six scripts read config_loader's output today (analyze-bash-command.py, analyze-path.py,
render_config.py, lint-config-on-write.py, session-start-render.py, subagent-start-render.py). Under command-policy,
four map onto settled bin/ names (command-policy-analyze-bash-command, command-policy-analyze-path, explain-policy,
audit-session-policy); render_config.py dissolves into Config.explain()/Config.warnings(); and the three renderer hook
scripts need NEW command-policy entrypoints plus three NEW hook registrations (SessionStart, SubagentStart, PostToolUse
Write|Edit) — this leaf ships all of them.

**Adjacent systems already covering part of the need:** None — config_loader.py and its six consumers are the whole
validation/rendering surface today; no other tool covers part of this need (confirmed by user).

## This Improvement's Objective

Build a `Config` value object in the NEW `packages/command-policy/lib/` package (additive rewrite; the old
`packages/shfmt-permissions/scripts/config_loader.py` is left untouched and stays live at 6.1.2 per the trunk's
'additive, deprecate only' cutover decision) that replaces dict-returning config parsing with copy-on-write value
objects, and make linting and rendering behaviour OF those value objects rather than separate interpreters of a raw
dict.

This is leaf 3 of trunk `20260914-195111` (the Statement value-object full rewrite), in the re-cut nine-leaf stream. It
depends on leaf `20260914-213049` (the authored decision specification), whose settled `## Interface` fixes this leaf's
public entrypoint contract: `packages/command-policy/lib/config.py` is to carry
`Config.from_dict(cfg).decision_for(command)`. THIS LEAF MUST extend `Config.from_dict` with real parsing/validation
WITHOUT changing the `decision_for(command)` signature; that supersedes this leaf's original open question of whether
the named constructor is called `fromText` (it is `from_dict`, settled upstream). NOTE (verified 2026-09-15): that file
does not exist yet — leaf 20260914-213049 is at `ready-to-implement`, planned but not implemented. The CONTRACT is
binding; the FILE is not yet there. See `## Assumptions`.

It also builds on leaf `20260915-010936` (package scaffold, in-progress), which fixed the package root, the
`lib/`-as-flat-sys.path-entry convention (`import config`, never `import lib.config`), the six settled `bin/` command
names, and the `tests/conftest.py` with its `run_entrypoint` subprocess fixture.

THIS LEAF DOES NOT IMPLEMENT `decision_for`. That is leaf `20260914-213652` (the pipeline leaf). The RED specification
suite (`tests/test_permission_decisions.py`) therefore STAYS RED after this leaf finishes — this leaf's own tests are
unit tests of construction, merge, warnings and explain.

The target shape, decided at trunk level and refined here:

- `Config.from_dict(cfg)` is the settled named constructor consuming an already-parsed dict (also the 'from-dict named
  constructor for tests' the old suite's TEST CONSTRAINT anticipated). Configuration arrives as a dict and becomes value
  objects at that edge, never as raw dicts read with `.get()` at depth.
- MERGE IS A VALUE-OBJECT OPERATION (decided this session): `Config.merged_with(other)` composes configuration layers
  copy-on-write, and each nested value object owns its own merge semantics. The loader performs pure I/O only — read the
  file, JSON-parse it — and carries no merge semantics whatsoever.
- `Config.warnings()` aggregates the warnings of every value object it constructed. THIS BECOMES THE LINT OUTPUT.
- `Config.explain()` renders by asking each constructed value object to explain what it does and what it constrains.
  THIS BECOMES THE RENDER OUTPUT, and this leaf is free to redesign that output for the deny-by-default model rather
  than porting today's format.
- The individual config concepts become copy-on-write value objects in their own right: `AllowedCommand` (absorbing the
  bare-string-vs-object-entry normalisation), `SensitivePath`, and the equivalents for blocked commands, sensitive
  variables and the allowed-prefix set. Path rules (`allowedPaths`) live behind a `PathConfig` property of the one
  `Config`.
- Per the trunk's NEW OUTCOME MODEL (banner section B): four of today's five decision knobs (`defaultDecision`,
  `sensitiveVariableResponse`, `pathValidationResponse`, `filterRejectionResponse`) DIE — they become constants, not
  config fields. `commandSubstitutionResponse` survives REDUCED: its `ask` value dies and `block` becomes deny, but the
  `via-allowed-commands` MATCHING choice remains meaningful and stays configurable. `Config`'s validation and
  `warnings()` must reflect a schema with four fewer knobs, not carry them forward as dead weight.

WHY THIS IS WORTH DOING (measured 2026-09-14, CORRECTED 2026-09-15 — line numbers apply to the OLD
`packages/shfmt-permissions/scripts/` code being read as source material): the bare-string-to-entry-dict normalisation
(`{"program": entry, "filters": []}`) exists at TWO sites, not one as this leaf and the trunk's Shared Context both
originally claimed — `analyze-bash-command.py:2227-2229` inside `_check_command_allowed`, and `render_config.py:39` in
`_entry_as_dict`, whose docstring openly states it mirrors the first. That is literal duplicated normalisation across
two modules, which strengthens the case for one model owning it. Meanwhile `config_loader.validate_config` validates
only FIVE top-level scalar decision knobs and descends into nothing else: `allowedCommands` entries, `filters`,
`allowedVariables`, `pathValidation`, `commandParser` and `propagate` are all consumed as untyped dicts at maximum
depth. One model that knows its own validity, warnings and self-description collapses the parallel surfaces into thin
callers.

SCOPE (decided this session): this leaf ships the `lib/` model AND ALL of its consumers, including the three hook
entrypoints and hook registrations the new package does not yet have (SessionStart, SubagentStart, PostToolUse
`Write|Edit`). See `## Design Decisions`.

## Proposed Approach

**Where the code lives.** All model code in `packages/command-policy/lib/` as flat modules (`import config`, never
`import lib.config`, per the scaffold leaf's settled convention). All entrypoints in `packages/command-policy/bin/`;
there is no `scripts/` directory and this leaf must not add one. The old `packages/shfmt-permissions/` package is READ
as source material and left completely untouched.

**The construction path.** Three named constructors plus one copy-on-write composer:

- `Config.defaults()` — the base layer, replacing today's `DEFAULT_CONFIG` dict.
- `Config.from_dict(cfg)` — the settled public entrypoint (signature fixed upstream by leaf 20260914-213049). Builds
  every nested value object; this is where validation and warning collection happen.
- `Config.merged_with(other)` — copy-on-write composition of two layers. THE MERGE SEMANTICS LIVE HERE AND IN THE NESTED
  VALUE OBJECTS, never in the loader. Each nested concept answers how it composes: the collection concepts (allowed
  commands, blocked commands, sensitive variables, sensitive paths, allowed prefixes, path rules) UNION; the one
  surviving scalar knob (`commandSubstitutionResponse`) is overlay-wins. Today this distinction is emergent from a bare
  `isinstance(x, list)` check in `merge_configs` (`config_loader.py:68-69`) and is therefore accidental; here it becomes
  an explicit property each concept declares.
- A thin loader in `lib/` reads the user and project config files and JSON-parses them — PURE I/O, no semantics — then
  composes `Config.defaults().merged_with(user).merged_with(project)`.

**Provenance is a first-class property.** Because layers are now composed as value objects rather than flattened as
dicts before validation, each layer knows where it came from (defaults / user file / project file). That lets
`warnings()` name the offending file — 'your user config set `commandSubstitutionResponse` to X, which is not a valid
value' — which today's single post-merge `validate_config` pass cannot do. This is what replaces the `_knobCorrections`
magic dict key (`config_loader.py:118`, `:172`, `:179-181`): knob corrections become ordinary warnings carrying
provenance, and the key itself, along with its user-injection-stripping guard, ceases to exist.

**The value-object inventory.** `Config` holds: an allowed-command collection of `AllowedCommand` (each carrying its
program and its filters; `AllowedCommand` absorbs the bare-string-vs-object normalisation that today lives duplicated at
`analyze-bash-command.py:2227-2229` and `render_config.py:39`), a blocked-command collection, a sensitive-variable
collection, a `SensitivePath` collection, an allowed-prefix collection, the surviving `commandSubstitutionResponse`
choice, and a `PathConfig` property holding the `allowedPaths` rules (each a tools-scope plus a path). Every one is
copy-on-write per the trunk's idiom: `with_*` methods shallow-copy self with one value replaced, sub-values stay shared.

**`warnings()` and `explain()`.** Every value object answers both for itself; `Config` aggregates rather than
interprets. `warnings()` returns structured warning objects (not pre-formatted strings) so different consumers can
present them differently — the SessionStart hook prints text, the SubagentStart hook wraps in a JSON envelope, the
write-linter reports inline. `explain()` composes by asking each child to explain itself; `Config` is responsible only
for ordering and for the surrounding frame, never for reaching into a child's internals to format it. This is the guard
against `explain()` degenerating into a template engine.

**The explain() output is designed for the new model, not ported.** Today's rendering was written for a
passthrough-default engine, where the reader mostly needed to know the exceptions. Under deny-by-default the reader —
usually the MODEL, via injected session context — primarily needs to know what it CAN run. The output is therefore
organised around the auto-allowed surface first. Trunk leaf `20260915-011123`'s equivalence-search skill is specified to
read this same rendered surface, so whatever this leaf settles becomes that skill's input contract and belongs in the
`## Interface` hand-back.

**Consumers this leaf ships.** `explain-policy` (user-facing, replaces `render-shfmt-permissions`/`render_config.py`),
plus three NEW hook entrypoints in `bin/` with three NEW registrations added to `hooks/hooks.json`: a SessionStart
renderer (plain text), a SubagentStart renderer (returning the `hookSpecificOutput`/`additionalContext` JSON envelope),
and a PostToolUse `Write|Edit` config linter that fires only on writes to the config path. Each is a thin caller of
`warnings()`/`explain()` — no config interpretation of its own. Per the scaffold's naming rule (hook-invoked entrypoints
are prefixed because plugin `bin/` is APPENDED to PATH and a generic name can be shadowed), the three new ones carry the
`command-policy-` prefix; their exact names extend the scaffold leaf's settled scheme and should be recorded in the
`## Interface`.

**What dies.** `allowedReadPaths` (declared at `config_loader.py:31`, referenced nowhere — verified dead). The four dead
decision knobs and their `VALID_*` sets. `_knobCorrections` as a dict key. `render_config.py` as a module.
`merge_configs` as a free function over dicts.

## Affected Components

**Files:**

- `packages/command-policy/lib/config.py` (extend leaf 20260914-213049's stub: real from_dict, defaults, merged_with,
  warnings, explain; decision_for stays NotImplementedError)
- `packages/command-policy/lib/` (new modules for the nested value objects — exact module split to be decided during
  implementation)
- `packages/command-policy/lib/placeholder.py` (DELETE — the scaffold interface says the first leaf adding a real lib/
  module removes it)
- `packages/command-policy/bin/explain-policy` (implement: render + lint via Config)
- `packages/command-policy/bin/command-policy-render-session-start` (NEW, name per the prefix rule)
- `packages/command-policy/bin/command-policy-render-subagent-start` (NEW, name per the prefix rule)
- `packages/command-policy/bin/command-policy-lint-config-on-write` (NEW, name per the prefix rule)
- `packages/command-policy/hooks/hooks.json:3-46` (add SessionStart, SubagentStart and PostToolUse Write|Edit
  registrations alongside the existing PreToolUse ones, in the same plugin wrapper format)
- `packages/command-policy/tests/test_scaffold.py:11-18` (remove explain-policy from STUB_ENTRYPOINTS — it no longer
  exits with empty stdout — and repoint the placeholder import)
- `packages/command-policy/tests/` (new unit test modules for construction, merge, provenance, warnings, explain, and
  the four entrypoints)
- `packages/shfmt-permissions/scripts/config_loader.py:21-182` (READ ONLY — source material, left untouched)
- `packages/shfmt-permissions/scripts/render_config.py:39` (READ ONLY — second normalisation site, source material)
- `packages/shfmt-permissions/hooks/hooks.json:46-79` (READ ONLY — the three renderer hook registrations being carried
  over)

**Files to delete:**

- `packages/command-policy/lib/placeholder.py`

**Classes/Functions:**

- Config (extended: defaults, from_dict, merged_with, warnings, explain; decision_for left unimplemented)
- AllowedCommand
- SensitivePath
- PathConfig
- blocked-command / sensitive-variable / allowed-prefix collection value objects (names to settle during implementation)
- a structured Warning value carrying provenance

**Modules:**

- command-policy

## Implementation Notes

**This leaf must not implement `decision_for`.** Leaf 20260914-213652 owns the pipeline.
`tests/test_permission_decisions.py` (leaf 20260914-213049's RED specification suite) therefore REMAINS RED when this
leaf finishes, by design. Do not 'fix' it; do not weaken it to make it pass. This leaf's own tests are separate unit
tests. When running the suite, the ONLY acceptable failures are that file's.

**Ordering against leaf 20260914-213049.** That leaf's `lib/config.py` stub does not exist on disk yet (it is at
`ready-to-implement`, planned but unimplemented). The `Depends on: 20260914-213049` edge is what guarantees the stub
plus its RED suite land BEFORE this leaf's implementation session starts. If for any reason this leaf implements first,
it must create `lib/config.py` with exactly the settled signatures rather than inventing its own.

**`test_scaffold.py` WILL break, by design.** Its `test_each_stub_entrypoint_exits_zero_with_empty_stdout` asserts every
name in `STUB_ENTRYPOINTS` prints nothing (`tests/test_scaffold.py:25-30`). `explain-policy` is in that list and this
leaf makes it print. Remove it from the list as part of implementing it — do not weaken the assertion for the
entrypoints that are still stubs. The three NEW hook entrypoints are implemented from the start and never belong in that
list.

**`placeholder.py` removal is a handoff, not cleanup.** The scaffold leaf's interface explicitly assigns its deletion
and the `test_scaffold.py` import repoint to 'the first leaf that adds a real lib/ module' — that is this leaf.

**Two plugins may both render at SessionStart.** `shfmt-permissions` is live at 6.1.2 and registers its own SessionStart
and SubagentStart renderers (`packages/shfmt-permissions/hooks/hooks.json:46-66`). Adding the equivalents to
`command-policy` means anyone with BOTH plugins installed gets two config renderings per session. The trunk's 'additive,
deprecate only' cutover accepted retained exposure deliberately, but duplicate session output is a user-visible
consequence worth stating in the deprecation note — flag for leaf 20260914-213825 and for INTEGRATE.

**Merge semantics are being made explicit, not changed.** Today every list unions and every scalar is overlay-wins
purely because `merge_configs` tests `isinstance(x, list)` (`config_loader.py:68-69`). The new model must reproduce the
same OUTCOME while making each concept declare its own composition rule. Deliberate non-change: a project config can
only ADD to a user config's collections, never remove from them — there is no subtraction today and this leaf does not
introduce one.

**Per-layer vs post-merge validation.** Today `validate_config` runs ONCE on the merged dict, so a bad knob value cannot
be attributed to a file. Validating per layer (a consequence of composing value objects rather than dicts) is what makes
provenance possible, and it is a deliberate improvement rather than an accident of the refactor. Check the end result
still matches: an invalid value in the user layer that is validly overridden by the project layer must not produce a
misleading final state or a misleading warning.

**`assert_config_is_reachable` equivalent.** The old suite (`tests/test_analyze_bash_command.py:53-73`) re-ran every
test config through the real `validate_config` so tests could not rely on knob values a real round-trip would rewrite.
The new suite needs an equivalent guard against `Config.from_dict`, or that protection is silently lost.

**Warning objects, not strings.** `warnings()` must return structured values because its consumers present them
differently (plain text at SessionStart, a JSON `additionalContext` envelope at SubagentStart, linter output on config
write). Returning pre-formatted strings would push formatting decisions back out into the callers this leaf exists to
thin.

**Hook registration format.** `packages/command-policy/hooks/hooks.json` uses the plugin WRAPPER format — events nested
under a top-level `"hooks"` key, each entry `{matcher, hooks: [{type, command, timeout}]}` with
`${CLAUDE_PLUGIN_ROOT}/bin/<name>` commands (verified at `:3-46`). SessionStart and SubagentStart take NO matcher; the
linter takes matcher `Write|Edit`. Old-package timeouts were 5s for all three.

**Size warning.** With all consumers folded in, this leaf covers the model, four entrypoints, three hook registrations
and their tests. It is deliberately the chosen scope, but it is on the large side for one leaf — if implementation finds
it bloating a session's context, the honest move is to split the consumer half into a sibling leaf of the same trunk
rather than rushing it.

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions

**Discovered during implementation: the knob's "explicit" flag.** `Config.merged_with` cannot decide overlay-wins for
`commandSubstitutionResponse` by "did the overlay object have a value" alone, because every `Config` always carries
_some_ resolved value (the default when unconfigured). Config therefore tracks a private
`command_substitution_response_explicit` flag alongside the resolved value - set when the raw dict actually contained
the key (valid or not) - and `merged_with` only lets the overlay win when that flag is true. Without it, a project layer
that never mentions the knob would silently reset a user layer's explicit `deny` back to the default on every merge.
This flag is Config-internal (not part of `## Interface`'s public surface) and propagates through
`merged_with`/`_replace` like any other field.

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/conftest.py` — lib/ sys.path bootstrap enabling a direct `import config` in unit tests,
  plus the run_entrypoint(name, args, stdin, env) subprocess fixture for driving bin/ entrypoints end-to-end
- `packages/command-policy/tests/conftest.py` (cwd-pinning fixture) — added by leaf 20260914-213049; pins cwd so
  project-config discovery is deterministic — reuse it rather than adding a second one
- `packages/shfmt-permissions/tests/test_config_loader.py` — 504 lines of merge and knob-validation CASES to mine as
  reference material for coverage — not an importable helper
- `packages/shfmt-permissions/tests/test_render_config.py` — 381 lines of rendering and lint CASES as reference material
  for explain()/warnings() coverage — not an importable helper

**New helpers to create:**

- config layer builder — tests need to construct user/project layers as plain dicts for the pure-construction tests, and
  — for loader tests only — as real files under tmp_path with the home/project locations pointed at them
- warning assertion helper — warnings() returns structured values, so tests should assert on warning identity and
  provenance rather than on formatted strings

**Fantasy callsites (test-facing API sketches):**

- `Config.defaults().merged_with(Config.from_dict({'allowedCommands': ['rg']})).allowed_commands`
- `Config.from_dict({'commandSubstitutionResponse': 'nonsense'}).warnings()  # names the knob, the configured value, the layer it came from, and what is in effect`
- `Config.from_dict(cfg).explain()  # rendering organised around what is auto-allowed`

**Testability-driven production decisions:**

- Split pure construction (from_dict / merged_with / warnings / explain — zero IO) from the file loader (the only IO),
  so nearly every test needs no filesystem at all. This is the house rule that rules receive their data while the edge
  fetches it.
- The loader takes its config file locations as explicit parameters rather than computing them from module-level
  constants at import time, so tests can point it at tmp_path without monkeypatching module internals.
- warnings() returns structured warning values rather than formatted strings, so tests assert on identity and provenance
  and each of the three consumers owns its own formatting.
- Each configuration layer carries its provenance, which is what makes a warning attributable to a specific file — and
  makes that attribution directly assertable in a test.

## Assumptions

- **The bare-string-to-entry-dict normalisation exists at EXACTLY ONE call site (analyze-bash-command.py:2226-2229) and
  nowhere else — asserted by this leaf's original objective AND by the trunk's Shared Context 'Measured facts about the
  code being replaced'** — refuted (code-research 2026-09-15: a SECOND site exists at
  packages/shfmt-permissions/scripts/render_config.py:39 (\_entry_as_dict), whose own docstring states it normalises to
  the same shape \_check_command_allowed does. Both produce an identical {'program': str, 'filters': []}. Confirmed no
  OTHER script does its own isinstance check — lint-config-on-write.py, session-start-render.py and
  subagent-start-render.py all route through render_config, and analyze-path.py never reads allowedCommands. The finding
  STRENGTHENS the case for one model owning the normalisation, but the 'exactly one' figure is false. Corrected in this
  leaf's objective; INTEGRATE should correct the trunk's Shared Context copy.)

- **packages/command-policy/lib/config.py already exists carrying leaf 20260914-213049's Config.from_dict / decision_for
  stub, so this leaf extends an existing file** — refuted (Neither packages/command-policy/lib/config.py nor
  packages/command-policy/tests/test_permission_decisions.py exists on disk or anywhere in git history (checked
  2026-09-15). Leaf 20260914-213049's Meta status is ready-to-implement — finalised plan, no implementation — and its
  '## Interface' uses the plan skill's standard 'what this leaf produced' phrasing for a hand-back written at planning
  finalize, not a claim about files on disk. The CONTRACT (Config.from_dict(cfg).decision_for(command), signature
  unchangeable by this leaf) is settled and binding; the FILE is not yet there. The Depends-on edge is what sequences
  them.)

- **allowedReadPaths is a live config key that must be carried into the new model** — refuted (code-research: declared
  once in DEFAULT_CONFIG at config_loader.py:31 and explicitly marked deprecated there; referenced NOWHERE else in the
  codebase. It is dead and must not be carried into the command-policy Config model.)

- **The three renderer scripts' behaviours can be absorbed into command-policy's existing two PreToolUse entrypoints
  without new hook registrations** — refuted (packages/shfmt-permissions/hooks/hooks.json: lint-config-on-write.py is
  PostToolUse matcher Write|Edit (:68-79), session-start-render.py is SessionStart (:46-56), subagent-start-render.py is
  SubagentStart (:57-66). Distinct lifecycle events with distinct I/O contracts — subagent-start returns a JSON
  hookSpecificOutput envelope, session-start prints plain text — so they cannot be folded into a PreToolUse Bash/Read
  handler. command-policy needs three NEW registrations.)

- **render_config.py imports from config_loader and is itself a config consumer in its own right** — refuted
  (code-research: render_config.py imports NOTHING from config_loader. It is a pure-function module (render_entry,
  render_summary, lint_config, render_and_lint) receiving an already-loaded config dict from its three callers. It
  therefore dissolves into Config.explain()/Config.warnings() rather than becoming a thin caller of them.)

- **Implementing explain-policy is compatible with the existing scaffold test suite as written** — refuted
  (packages/command-policy/tests/test_scaffold.py:11-18 lists explain-policy in STUB_ENTRYPOINTS, and :25-30 asserts
  every such entrypoint exits 0 with EMPTY stdout. An implemented explain-policy prints its rendering, so that test
  fails by design. Removing explain-policy from the list is a required step of this leaf, and the assertion must stay
  intact for the entrypoints that remain stubs.)

- **Config merge semantics today are lists-union and scalars-overlay-wins, applied generically by an isinstance check
  rather than declared per key** — confirmed (config_loader.py:52-73 (merge_configs); :68-69 returns base_value +
  overlay_value when BOTH values are lists, otherwise the overlay value wins. Layer order is DEFAULT_CONFIG -> user file
  -> project file (load_config_from_files, :76-112).)

- **validate_config validates only the five decision knobs and descends into no structural config key** — confirmed
  (config_loader.py:156-182 iterates DECISION_KNOBS (:123-129) and nothing else — no validation of allowedCommands
  entries, filters, allowedVariables, pathValidation, commandParser, propagate, or any list shape, and no type checking
  at all. It additionally strips a user-supplied \_knobCorrections key (:172) because that key is internal telemetry
  that would otherwise ride through the merge into lint_config.)

- **command-policy's hooks.json uses the plugin wrapper format and this leaf can extend it with three more event
  registrations in the same shape** — confirmed (packages/command-policy/hooks/hooks.json:3-46 — events nested under a
  top-level 'hooks' key, each entry {matcher, hooks: [{type: 'command', command: '${CLAUDE_PLUGIN_ROOT}/bin/<name>',
  timeout}]}. Currently only PreToolUse (Bash timeout 10; Read/Grep/Glob timeout 5 each).)

- **tests/conftest.py gives this leaf everything it needs to test both lib/ modules and bin/ entrypoints** — confirmed
  (packages/command-policy/tests/conftest.py:19-52 — inserts lib/ onto sys.path so tests do a direct `import config`,
  and provides run_entrypoint(name, args, stdin, env) driving a bin/ entrypoint end-to-end via subprocess with
  os.environ overlaid. It deliberately has NO importlib module-loader fixture (:5-9) and must not gain one. Leaf
  20260914-213049 additionally adds a cwd-pinning fixture here.)

## Design Decisions

### Scope boundary between this leaf and trunk leaf 20260914-213825 (consumer landing)

- **Chosen:** lib/ + ALL consumers — this leaf ships the Config model AND explain-policy AND the three new hook
  entrypoints (SessionStart, SubagentStart, PostToolUse Write|Edit) with their hooks.json registrations
- **Rationale:** These consumers are trivially thin — each is a few lines calling warnings()/explain() — so splitting
  them across a leaf boundary costs more in handoff than it saves in context.
- **Rejected alternatives:** lib/ only, leaving every consumer to leaf 20260914-213825 (was the planner's
  recommendation, on context-budget grounds); or lib/ plus explain-policy alone as a single proving consumer
- **Date:** 2026-09-15

### Malformed and missing config file handling

- **Chosen:** A config file that is PRESENT but unparseable triggers a LOUD warning surfaced through the SessionStart
  and SubagentStart hooks, accompanied by an explanation of which commands ARE currently auto-allowed. A config file
  that is simply ABSENT stays silent.
- **Rationale:** User's instruction, verbatim: 'This should already trigger a loud warning in the SessionStart and
  SubagentStart hook that explains the available auto allowed commands'. Under deny-by-default a silently-ignored config
  file means every command denies with no explanation of why, so the warning must also state what IS in effect. An
  absent file is the normal case (no project config, fresh user) and is not a problem to report.
- **Rejected alternatives:** Warn on any read failure including a simply-absent file; or keep today's fully-silent
  behaviour for both cases (except (json.JSONDecodeError, OSError): pass at config_loader.py:100-101 and :109-110)
- **Date:** 2026-09-15

### Where config-merge logic lives

- **Chosen:** Merge is a value-object operation: Config.merged_with(other) composes layers copy-on-write and each nested
  value object owns its own composition rule. The loader does pure I/O (read + JSON-parse) and carries no merge
  semantics.
- **Rationale:** User's note, verbatim: 'There is logic behind the merge - at least adding together allowedCommands,
  haven't looked at the others. But this logic should be in the VO not in the code surrounding the VO'. Merging
  allowedCommands is domain behaviour, so it belongs to the object that owns the concept, not to a helper beside it.
- **Rejected alternatives:** Merge the raw dicts in a loader helper before a single Config.from_dict call (today's shape
  — merge_configs at config_loader.py:52-73 — which keeps merge semantics outside the value objects)
- **Date:** 2026-09-15

### Whether path rules share the command Config model

- **Chosen:** One Config covering the whole config file, with the path rules separated behind a PathConfig property
- **Rationale:** User's note, verbatim: 'One Config, but I'm fine with a PathConfig property to separate that logic
  out'. One file, one model, one explain() covering everything the user configured — while the path logic, which shares
  no vocabulary with the bash analyzer, stays isolated behind its own value object.
- **Rejected alternatives:** A wholly separate PathConfig model constructed independently from the same file
- **Date:** 2026-09-15

### How free this leaf is to design Config.explain()'s rendered output

- **Chosen:** Free to redesign for the deny-by-default model — organise the output around what the reader CAN run,
  rather than porting render_config.py's exception-oriented format
- **Rationale:** rationale not captured
- **Rejected alternatives:** Stay close to today's format, changing only what the dead knobs force; or ship explain() as
  structured data only and defer all rendering to leaf 20260915-011123
- **Date:** 2026-09-15

## Success Criteria

- [x] packages/command-policy/lib/config.py exposes Config.defaults(), Config.from_dict(cfg), Config.merged_with(other),
      Config.warnings() and Config.explain(); decision_for(command) keeps its settled signature and still raises
      NotImplementedError
- [x] No isinstance(entry, str) normalisation of an allowedCommands entry exists anywhere in packages/command-policy
      outside AllowedCommand's own named constructor (grep-verifiable)
- [x] No consumer reads a raw config dict: no .get("allowedCommands"), .get("sensitivePaths") or equivalent appears
      outside lib/config.py's construction code (grep-verifiable)
- [x] Collection concepts union across layers and the surviving commandSubstitutionResponse knob is overlay-wins,
      asserted by unit tests that touch no filesystem
- [x] Copy-on-write holds: a with\_\* call returns a new Config whose unchanged sub-objects are the SAME objects as the
      original's (identity-asserted, not just equality)
- [x] A present-but-unparseable config file produces a warning naming that file; an absent config file produces no
      warning at all
- [x] Every warning names the layer it came from (defaults / user / project), including an invalid knob value that a
      later layer validly overrides
- [x] \_knobCorrections appears nowhere in packages/command-policy — knob corrections are ordinary warnings
- [x] allowedReadPaths and the four dead knobs (defaultDecision, sensitiveVariableResponse, pathValidationResponse,
      filterRejectionResponse) appear nowhere in packages/command-policy
- [x] bin/explain-policy renders the config and its warnings; the SessionStart entrypoint emits plain text; the
      SubagentStart entrypoint emits a valid {"hookSpecificOutput": {"hookEventName": "SubagentStart",
      "additionalContext": ...}} envelope; the config-write linter fires only for writes to the config path — each
      verified through run_entrypoint
- [x] The loud broken-config warning reaches the reader ALONGSIDE the rendering of what is currently auto-allowed, in
      both the SessionStart and SubagentStart entrypoints
- [x] hooks/hooks.json carries five registrations in the plugin wrapper format: the two existing PreToolUse ones plus
      SessionStart, SubagentStart and PostToolUse Write|Edit
- [x] lib/placeholder.py is deleted and tests/test_scaffold.py imports a real lib/ module instead, with explain-policy
      removed from STUB_ENTRYPOINTS and the empty-stdout assertion still intact for the remaining stubs
- [x] cd packages/command-policy/tests && nix-shell --run "pytest -v" runs with every test of THIS leaf passing, and the
      only failures being test_permission_decisions.py's by-design RED specification cases

## Implementation TODO

- [x] Update status to in-progress
- [x] Delete lib/placeholder.py and repoint tests/test_scaffold.py's import to the first real lib/ module
- [x] Build AllowedCommand (TDD): bare-string and object entries both normalise through its named constructor
- [x] Build the remaining collection value objects (TDD): blocked commands, sensitive variables, SensitivePath, allowed
      prefixes
- [x] Build PathConfig (TDD): allowedPaths entries as a tools-scope plus a path
- [x] Build the structured Warning value carrying its layer provenance (TDD)
- [x] Build Config.defaults() and Config.from_dict() assembling the full model, with the four dead knobs absent and
      commandSubstitutionResponse validated (TDD)
- [x] Add the assert_config_is_reachable equivalent: a guard re-running every test config through Config.from_dict so
      tests cannot rely on values a real round-trip would rewrite
- [x] Build Config.merged_with() (TDD): collections union, commandSubstitutionResponse overlay-wins, merge semantics
      owned by each value object and absent from the loader
- [x] Assert copy-on-write identity: a with\_\* call returns a new Config whose unchanged sub-objects are the SAME
      objects
- [x] Build Config.warnings() (TDD): an invalid knob value names the layer it came from, and knob corrections fully
      replace \_knobCorrections
- [x] Build Config.explain() (TDD): each child explains itself while Config only orders and frames, with output
      organised around what is auto-allowed
- [x] Build the file loader (TDD): pure read plus JSON-parse per layer composed via merged_with, warning by name on a
      present-but-unparseable file and staying silent on an absent one
- [x] Implement bin/explain-policy AND remove it from test_scaffold.py's STUB_ENTRYPOINTS in the same step, keeping the
      empty-stdout assertion intact for the remaining stubs
- [x] Implement bin/command-policy-render-session-start: plain text, warnings alongside what is auto-allowed
- [x] Implement bin/command-policy-render-subagent-start: hookSpecificOutput/additionalContext JSON envelope, warnings
      alongside what is auto-allowed
- [x] Implement bin/command-policy-lint-config-on-write: fires only for writes to the config path
- [x] Register the three new hooks in hooks/hooks.json (SessionStart, SubagentStart, PostToolUse Write|Edit) in the
      plugin wrapper format
- [x] Grep-verify the negative criteria: no isinstance-on-entry outside AllowedCommand, no raw config .get() outside
      lib/config.py, no allowedReadPaths, no \_knobCorrections, none of the four dead knobs
- [x] Run the full suite and confirm every test of this leaf passes with the only failures being
      test_permission_decisions.py's by-design RED cases
- [x] Reconcile the ## Interface section against what was actually built, correcting anything implementation changed
- [x] Update status to completed

## Interface

**What this leaf produced:** The `Config` value-object model in `packages/command-policy/lib/` — `Config` plus its
nested copy-on-write value objects (`AllowedCommand`, `SensitivePath`, `PathConfig`/`PathRule`, the `NameCollection`
family — `BlockedCommands`, `SensitiveVariables`, `AllowedPrefixes`, sharing one base since all three are an ordered set
of literal names with union merge — and a structured `Warning` carrying layer provenance) — together with the pure I/O
loader (`lib/config_loader.py`: `load_config(user_path, project_path)` / `load_config_from_environment()`), the pure
hook-response builders (`lib/hook_envelopes.py`), all four consumers (`bin/explain-policy`,
`bin/command-policy-render-session-start`, `bin/command-policy-render-subagent-start`,
`bin/command-policy-lint-config-on-write`), and their three new `hooks/hooks.json` registrations.

**Contract for downstream leaves / integrate:**

- The public surface is `Config.defaults()`, `Config.from_dict(cfg, source="config")`, `Config.merged_with(other)`,
  `Config.warnings()` and `Config.explain()`. `source` is an added keyword-only label (not a change to the settled
  positional signature) naming which layer produced a `Config`, for warning provenance — the loader passes
  `source="user"` / `source="project"`. `decision_for(command)` keeps leaf `20260914-213049`'s settled signature and
  STILL raises NotImplementedError — leaf `20260914-213652` implements its body, and
  `tests/test_permission_decisions.py` is still RED by design when this leaf finishes.
- `Config` tracks a private `command_substitution_response_explicit` flag alongside the resolved knob value (set
  whenever the raw layer dict actually contained the key, valid or not). `merged_with` only lets an overlay's knob value
  win when that flag is true, so a later layer that never mentions the knob cannot silently reset an earlier layer's
  explicit choice back to the default. This flag is internal to `Config`, not part of its public surface.
- Leaf `20260914-213502` (Filter/Parser) constructs filters FROM `AllowedCommand`'s filter definitions. `AllowedCommand`
  owns bare-string-vs-object entry normalisation; no downstream leaf may re-implement an `isinstance` check on an
  `allowedCommands` entry.
- Leaf `20260914-213652` (pipeline) receives a fully-constructed `Config`; policies read typed value objects and never a
  raw config dict.
- Leaf `20260915-011123` (skills) consumes `Config.explain()`'s rendered output as its input surface. That format is
  settled HERE and is deny-by-default-oriented — organised around what the reader CAN run, not around exceptions to a
  permissive default.
- Config schema: the four decision knobs `defaultDecision`, `sensitiveVariableResponse`, `pathValidationResponse` and
  `filterRejectionResponse` are GONE; only `commandSubstitutionResponse` remains configurable. `allowedReadPaths` and
  `_knobCorrections` do not exist in the new model.
- Merge is a value-object operation (`Config.merged_with`), with each nested concept owning its own composition rule. No
  leaf may reintroduce dict-level merging outside the value objects.
- `warnings()` returns structured values carrying the layer they came from (defaults / user / project), never
  pre-formatted strings.

**New dependency edges discovered:** None that change the Leaf Stream order. This leaf now also owns consumer surfaces
originally scoped to leaf `20260914-213825`, which narrows that leaf to `analyze-path.py`, the ~100-140
internals-coupled tests, and the deprecation work.

**Follow-ups for integrate:**

1. The trunk's `## Shared Context` "Measured facts" states the bare-string-to-entry-dict normalisation lives at one site
   and nowhere else. That is WRONG — it lives at two (`analyze-bash-command.py:2227-2229` and `render_config.py:39`).
   Correct the trunk's copy.
2. Anyone with BOTH `shfmt-permissions` and `command-policy` installed now gets two config renderings per session, since
   both register SessionStart and SubagentStart renderers. Accepted consequence of the additive cutover; state it in the
   deprecation note (leaf `20260914-213825`).
3. Leaf `20260914-213825`'s scope shrank — re-read it against what this leaf actually shipped rather than against its
   original description.
4. This leaf is on the large side (model plus four entrypoints plus three registrations). If implementation finds it
   bloating a session's context, split the consumer half into a sibling leaf of this trunk rather than rushing it.
