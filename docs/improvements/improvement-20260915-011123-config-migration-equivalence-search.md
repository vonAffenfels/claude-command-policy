# Improvement 20260915-011123: Config Migration Skill & Equivalence-Search Skill

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-15
- Updated: 2026-09-18
- Plan started: 2026-09-17T18:17:40+02:00
- Plan finished: 2026-09-17T19:47:27+02:00
- Impl started: 2026-09-18T12:54:32+02:00
- Impl finished: 2026-09-18T13:12:38+02:00
- Trunk: 20260914-195111
- Kind: decomposed
- Depends on: 20260915-010959

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`

## This Improvement's Objective

LEAF of trunk `20260914-195111` — owns two skill-authoring efforts that share one input surface (`Config.explain()`'s
rendered output): (1) a user-run config-migration skill from `~/.claude/shfmt-permissions.json` to
`~/.claude/command-policy.json`, and (2) the model-facing equivalence-search skill
(`command-policy:find-auto-allowed-command`) that every deny reason points at.

DISCOVERED DURING THIS SESSION'S PLANNING: three of the four config-key renames this leaf's own objective text
originally claimed as "settled" (`allowedVariables`, `additionalAllowedPrefixes`, `pluginProgram`) were never actually
applied anywhere in the shipped engine — verified directly against `packages/command-policy/lib/config.py` and
`allowed_command.py`, which still read the OLD key names. Only `pathValidation` -> `hasNoPathParameters` actually landed
(in the completed leaf `20260914-213153`), and `propagate` was SUPERSEDED entirely — it is no longer a renamed key but a
structural reshape into an ordinary `{"type": "nestedCommand"}` filter (settled by leaf `20260914-213049` and leaf
`20260914-213652`'s planning, engine-side implementation not yet built). The user decided (during this leaf's planning)
that THIS leaf both settles final names AND applies them by extending the already-completed `Config`/`AllowedCommand`
value objects, rather than passing them to a new sibling leaf.

## Context / Why This Exists

**Origin / trigger:** Created during trunk `20260914-195111`'s 2026-09-15 re-plan: the config-migration decision ("add a
skill to migrate but no code to auto-detect the need") and the hint-richness decision ("near miss derived + reference a
skill that looks for the equivalent command based on the rules rendering") each implied a skill no existing leaf owned.

**Consumer(s) of the output:** Skill 1 (`migrate-config`)'s consumer is the human upgrading from shfmt-permissions to
command-policy. Skill 2 (`find-auto-allowed-command`)'s consumer is the model itself, reached via a deny reason that
names the skill by its frozen contract name — it is the self-correction half of the new outcome model's branch-1 loop.

**Adjacent systems already covering part of the need:** Both skills sit on `Config.explain()` (leaf `20260914-213153`,
completed) rather than re-reading raw config. `packages/shfmt-permissions/skills/config/SKILL.md` documents today's full
config surface and is what the migration skill translates FROM. Leaf `20260915-010959` (deny reasons, not yet
implemented) froze the skill-2 contract name and its unconditional-pointer design. Leaf `20260914-213502`
(Filter/Parser, not yet implemented) will later enrich `Config.explain()`'s per-entry filter descriptions; by
leaf-stream order it lands before this leaf implements, so skill 2's input is already rich by then.

## Proposed Approach

Two co-located but independent efforts, both living under `packages/command-policy/`, sharing `Config.explain()` as
input:

**A. RENAME COMPLETION** (extends the already-completed `Config` value-object leaf). Apply the three config-key renames
leaf `20260914-213049`'s audit handed to leaf `20260914-213153` but which never actually landed in shipped code:

- `allowedVariables` -> `onlyTheseVariables` (states the deny-by-default plainly; B1's own suggested direction, adopted
  as final)
- `additionalAllowedPrefixes` -> `additionalAllowedPathPrefixes` (disambiguates from the unrelated `allowedPaths`
  Read/Grep/Glob key; adds "Path")
- `pluginProgram` -> `programGlob` (names what it is — a program resolved via a wildcarded glob against the plugin cache
  — not "a plugin"; this name appears nowhere in the corpus except this leaf's own draft, so it is being finalized here,
  not merely carried forward)

Rename the Python-side identifiers to match, not just the JSON keys (the internal name should not perpetuate the same
confusion the JSON rename fixes): `AllowedCommand`'s `allowed_variables` param/attr -> `only_these_variables`; the
`AllowedPrefixes` class (`name_collection.py`) -> `AllowedPathPrefixes`, its `_label` ->
`"additionalAllowedPathPrefixes"`; `Config`'s `allowed_prefixes` property -> `allowed_path_prefixes`. Update every
existing call site and existing test in `test_allowed_command.py`, `test_config.py`, `test_name_collection.py` to match
(red-then-green: rename breaks them, fix them). `pathValidation` -> `hasNoPathParameters` is ALREADY correctly
implemented (leaf 213153) — verified in shipped code, no change needed there.

Add `programGlob` support to `AllowedCommand`: a new `program_glob` field (dict: `marketplace`, `plugin`, `path` —
mutually exclusive with `program`) parsed from the `programGlob` JSON key, validated the same way the old engine did
(path must not start with `/`, none of `marketplace`/`plugin`/`path` may contain `..`).

Fold in a scope-adjacent gap while touching `AllowedCommand.explain()`: today it never mentions
`allowed_variables`/`onlyTheseVariables` at all, even though the entire point of the rename is to make deny-by-default
variable semantics legible — add that to `explain()`'s output (e.g. "(only variables permitted: X, Y)" when set), since
skill 2 depends on `explain()` actually surfacing this to reason about equivalence.

CROSS-LEAF HAND-BACK to leaf `20260914-213652` (pipeline, ready-to-implement, NOT yet implemented — still cheap): that
leaf's `AllowedCommand` Policy class must implement the actual `programGlob` MATCHING logic (resolve
`CLAUDE_CODE_PLUGIN_CACHE_DIR`, build the `{cache_root}/{marketplace}/{plugin}/*/{path}` glob pattern, `fnmatch` against
the invoked command), mirroring shfmt-permissions' `_build_plugin_program_pattern`/`_check_command_allowed`
`pluginProgram` branch. This leaf only settles the config SHAPE; leaf 213652 owns whether an invocation actually matches
it. Record this hand-back explicitly so it is not lost before leaf 213652 is implemented.

**B. CONFIG-MIGRATION SKILL** (`packages/command-policy/skills/migrate-config/SKILL.md`, user-invocable, wrapped by a
thin command `packages/command-policy/commands/migrate-config.md` per the "command as reliable entry point to a skill"
pattern — a migration is a deliberate, must-run-exactly-when-asked action, not a pattern-matched one). Backed by a new
pure-logic module `lib/config_migration.py` (no I/O) plus a new `bin/migrate-config` entrypoint (the 5th user-facing
`bin/` command, following the existing `bypass-policy`/`add-allow-policy`/`explain-policy`/`audit-session-policy` naming
shape). SEMANTIC, not textual: the four dead decision knobs (`defaultDecision`, `sensitiveVariableResponse`,
`pathValidationResponse`, `filterRejectionResponse`) are STRIPPED from the output and ALWAYS surfaced in a
plain-language summary explaining they no longer exist and that deny-by-default is materially stricter than the shipped
default (`defaultDecision: passthrough`) — shown even when the source config never set them explicitly, since the user
is losing that behaviour regardless. `commandSubstitutionResponse` survives: `via-allowed-commands` passes through
unchanged; `ask` and `block` both migrate to `deny` (matching `VALID_COMMAND_SUBSTITUTION_RESPONSES` in the shipped
`Config`). Per-entry translations: `onlyTheseVariables` / `additionalAllowedPathPrefixes` / `programGlob` key renames as
above; `pathValidation:false` -> `hasNoPathParameters:true` (inverted polarity); `propagate` (string or object form) ->
append an ordinary `{"type": "nestedCommand", "maxDepth": N}` filter to the entry's filters array (structural reshape,
not a key rename — `propagate` itself disappears as an entry-level key); `allowedReadPaths` (deprecated old key) ->
converted into equivalent `allowedPaths` entries using the same `{path, tools}` shape the old SKILL.md already documents
for that deprecation, then merged with any existing `allowedPaths`. `allowedCommands` (bare-string entries unchanged),
`blockedCommands`, `sensitiveVariables`, `sensitivePaths`, `allowedPaths` copy across with no key change.

DRY-RUN BY DEFAULT: `bin/migrate-config` with no `--write` flag reads whichever of `~/.claude/shfmt-permissions.json`
and `${CLAUDE_PROJECT_DIR}/.claude/shfmt-permissions.json` exist (skip silently whichever does not — never fabricate a
project config from nothing), computes the migrated config in memory, and prints (as structured JSON on stdout) the
migrated config, the list of dropped/renamed/reshaped items, and — if a target `command-policy.json` already exists — a
diff against it. It writes NOTHING. The skill reads this dry-run output, presents the summary and any diff to the user
in prose, and uses `AskUserQuestion` to confirm before invoking `bin/migrate-config --write`, which performs the actual
write(s) (mirrors `add-allow-policy`'s "approving the dialog IS the write" pattern). `bin/migrate-config` never
overwrites an existing `command-policy.json` without that confirmation round-trip — confirmation is the skill's job, not
the bin script's, since `AskUserQuestion` is a conversational tool the `bin/` entrypoint cannot use.

The old `shfmt-permissions.json` file(s) are NEVER modified or deleted — purely additive, matching the trunk's cutover
decision.

**C. EQUIVALENCE-SEARCH SKILL** (`packages/command-policy/skills/find-auto-allowed-command/SKILL.md`, user-invocable:
false — reached primarily via the deny-reason pointer, though a user's own natural-language ask can also trigger it same
as `shfmt-permissions:config`). PURE PROSE REASONING ONLY, deliberately NOT verified against `Config.decision_for()`
even once leaf 213652 ships it (design decision below) — runs `bin/explain-policy` to read the live rendered rules
(AUTO-ALLOWED COMMANDS section primarily; blocked/ sensitive sections to avoid suggesting something already known-bad),
reasons in prose about what auto-allowed command/shape accomplishes the same goal as the command the calling session
just had denied, and states its best candidate or says plainly that none was found. No structured input/output contract
beyond that — the invoking session already has the full denied command and deny reason in its own context (Skill tool
loads the skill body into the SAME conversation, not a subagent), so the skill body only needs to instruct the reasoning
procedure, not accept parameters.

## Affected Components

**Files:**

- `packages/command-policy/lib/allowed_command.py` (extend: `only_these_variables` rename, new `program_glob` field +
  validation, `explain()` enrichment for `only_these_variables`)
- `packages/command-policy/lib/name_collection.py` (rename `AllowedPrefixes` -> `AllowedPathPrefixes`, `_label` ->
  `additionalAllowedPathPrefixes`)
- `packages/command-policy/lib/config.py` (`Config.from_dict` reads `additionalAllowedPathPrefixes`; `allowed_prefixes`
  property -> `allowed_path_prefixes`)
- `packages/command-policy/lib/config_migration.py` (NEW — pure translation logic, no I/O)
- `packages/command-policy/bin/migrate-config` (NEW — the 5th user-facing `bin/` command; dry-run by default, `--write`
  to apply)
- `packages/command-policy/skills/migrate-config/SKILL.md` (NEW, user-invocable)
- `packages/command-policy/commands/migrate-config.md` (NEW — thin wrapper per command-agent-authoring.md's "command as
  reliable entry point to a skill" pattern; first `commands/` dir in this package)
- `packages/command-policy/skills/find-auto-allowed-command/SKILL.md` (NEW, user-invocable: false)
- `packages/command-policy/tests/test_allowed_command.py` (update for renames + new `program_glob` field)
- `packages/command-policy/tests/test_config.py` (update for `additionalAllowedPathPrefixes` rename)
- `packages/command-policy/tests/test_name_collection.py` (update for `AllowedPathPrefixes` rename)
- `packages/command-policy/tests/test_config_migration.py` (NEW)
- `packages/command-policy/tests/test_consumer_entrypoints.py` (extend for `bin/migrate-config`'s dry-run/`--write` CLI
  contract via `run_entrypoint`)
- `packages/command-policy/lib/allowed_command_policy.py` (NOT in the original plan — added because leaf
  `20260914-213652` was already `completed` by the time this leaf started; see the RECONCILIATION note in Implementation
  Notes. Extended with `programGlob` matching-time resolution: candidate matching, and every reason-construction call
  site that read `entry.program` now reads `entry.program_label` so a `programGlob` entry without a plain `program`
  never surfaces `None` in a Reason.)
- `packages/command-policy/lib/warning_value.py` (extended: `dead_decision_knob_removed`,
  `propagate_reshaped_to_nested_command`, `allowed_read_paths_migrated` classmethods for migration warnings)
- `packages/command-policy/tests/test_allowed_command_policy.py` (extend for `programGlob` matching)
- `packages/command-policy/tests/test_permission_decisions.py` (extend: one black-box `programGlob` allow case)
- `docs/knowledgebase/command-policy-decision-model.md` (extend with a section on the two skills, once leaf
  `20260915-010959` has created/extended this article — do not create a second article, per the one-file test)
- `packages/shfmt-permissions/skills/config/SKILL.md` (READ ONLY — the source schema this migrates FROM)

**Classes/Functions:**

- `AllowedCommand` (extended: `program_glob` field, `only_these_variables` rename, `program_label` property, `explain()`
  enrichment)
- `AllowedPathPrefixes` (renamed from `AllowedPrefixes`)
- `Config` (`allowed_path_prefixes` property rename, `from_dict` reads renamed key)
- `ConfigMigration` / `migrate_shfmt_permissions_config` (new pure translation function/value carrying `new_config` +
  structured warnings list)
- `AllowedCommandPolicy` (extended: `_entry_matches_program`/`_program_glob_pattern` module functions implement
  `programGlob`'s matching-time half — the cross-leaf hand-back to leaf `20260914-213652`, completed directly here)

**Modules:**

- command-policy

## Implementation Notes

READ FIRST: this leaf's own file previously stated the `propagate` rename as `propagate -> evaluateNamedValueAsCommand`
and `pluginProgram` -> "programGlob" as though already settled elsewhere — the `propagate` claim is STALE (superseded
2026-09-16 by leaf `20260914-213049`/`20260914-213652` into a `{"type": "nestedCommand"}` filter reshape) and
`programGlob` was NOT settled anywhere else in the corpus before this planning session finalized it here. Do not trust
the phrase "handed down from leaf 20260914-213049's audit" for `propagate` literally — read the Approach section above,
which reflects the corrected, verified state.

ORDERING: measured twice during this planning session, and it MOVED mid-session — leaf `20260914-213502` (Filter/Parser)
read `ready-to-implement` early on and read `completed` by the end (`Impl finished: 2026-09-17T18:37:45+02:00`,
implemented concurrently in a peer session while this plan was being written). Leaf `20260914-213652` (Pipeline) was
still `ready-to-implement` at the close of planning. Both precede this leaf in the trunk's Leaf Stream and this leaf's
own Depends-on chain runs through leaf `20260915-010959` -> leaf `20260914-213652`, so by the time THIS leaf is
implemented both should exist. Re-verify at implementation start (a quick Meta-status check on both files) before
assuming `Config.explain()` already has rich per-entry filter descriptions or that `Config.decision_for()` exists and is
not still a `NotImplementedError` stub — this leaf's sibling leaves are moving while it waits, so any status recorded
here is a snapshot, not a standing fact.

CROSS-LEAF HAND-BACK REQUIRED, leaf `20260914-213652`: implement `programGlob` matching in the `AllowedCommand` Policy
class (resolve `CLAUDE_CODE_PLUGIN_CACHE_DIR`, build the wildcarded-version glob pattern, `fnmatch` the invoked command
against it) — this leaf only adds the config-shape field, it does not implement matching-time behaviour. If leaf 213652
is ALREADY implemented by the time this leaf starts (check its Meta status), this hand-back must instead become a direct
extension of that leaf's already-shipped `AllowedCommand` Policy code — treat it the same way this leaf itself is
extending completed leaf 213153's code (an accepted, rare reconciliation), not as blocked work.

MIGRATION MUST NOT SILENTLY DROP THE FOUR DEAD KNOBS. Always print the plain-language strictness note (deny-by-default
is materially stricter than the shipped `defaultDecision:passthrough` default), regardless of whether the source config
set any of the four knobs explicitly — the user is losing that behaviour either way.

DRY-RUN IS THE DEFAULT AND ONLY WAY `bin/migrate-config` TOUCHES DISK ON `--write`: without `--write` it must not
create, modify or delete any file — verify this with a test that runs it against a temp `HOME` with no `--write` flag
and asserts no `command-policy.json` was created.

TEST ISOLATION: never let a test write to the real user's `~/.claude/command-policy.json`. Use the existing
`run_entrypoint` fixture's env override to set `HOME` to a pytest `tmp_path` for every migration test
(`conftest.py:51-72` already supports this — env overlays `os.environ` per-call, no new fixture needed for this alone).

SKILL 2 HAS NO STRUCTURED INPUT CONTRACT. It is invoked into the SAME conversation (Skill tool, not a subagent dispatch)
that already holds the denied command and its deny reason in context — do not design it as though it needs parameters
passed in; its SKILL.md body only needs to instruct the reasoning procedure (run `explain-policy`, reason over the
rendered rules, state a candidate or say none was found).

DISCOVERED DURING THIS LEAF'S IMPLEMENTATION: two correctness gaps in the `propagate` -> `nestedCommand` reshape that
the plan's Proposed Approach did not call out, both handled in `lib/config_migration.py` rather than deferred:

1. **The bundled reference parsers do not populate the `nestedCommands` channel yet.**
   `packages/command-policy/parsers/ nix-shell.py` (a byte-for-byte copy of the old engine's script) only emits
   `named: {"command": ...}`; the new `CommandParser.interpret` reads sub-commands from `raw_output["nestedCommands"]`
   (`lib/command_parser.py:42-45`), a field that script never writes. So a migrated entry whose `commandParser` is
   `{"type": "provided", "name": "nix-shell"}` (or `nix`/`timeout`) gets a `nestedCommand` filter that always fails
   closed — it now DENIES the wrapped command instead of propagating to it, until a future leaf teaches those bundled
   scripts to publish `nestedCommands`. Porting the bundled parsers is out of this leaf's Affected Components, so
   `config_migration.py` instead emits `Warning.propagate_reshaped_to_nested_command` for every migrated `propagate`
   entry, naming this risk explicitly (`lib/warning_value.py`).
2. **`commandParser.structured`'s field names are not identical between engines** (`structured_parser.py`'s own
   docstring: "today's StructuredParser mixes snake_case and camelCase across these four; that inconsistency is not
   ported"). A source entry using the old `options_with_arguments`/`double_dash_stops` spelling would otherwise migrate
   with a `commandParser` whose fields the new `StructuredParser.from_definition` silently never reads (defaults to "no
   options consume arguments" — a silent behavioural change, the exact failure mode `Config.from_dict`'s own load-time
   rejection rule exists to catch elsewhere). `config_migration._migrate_command_parser` renames both fields when
   `type == "structured"`; `pathOptions`/`pathPositionals` were already camelCase in the old schema, so nothing to do
   there.

**Testing Strategy:** TDD

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/conftest.py:51 run_entrypoint` — drives `bin/migrate-config` end-to-end via subprocess;
  its env override sandboxes `HOME` for migration tests
- `packages/command-policy/tests/conftest.py:111 assert_config_is_reachable` — guards migrated-output test fixtures
  against knob values no real `Config.from_dict` round-trip would produce

**New helpers to create:**

- `shfmt_permissions_config_fixture(tmp_path, **overrides)` — builds a temp `~/.claude/shfmt-permissions.json` (and
  optionally a project one) so migration tests don't hand-roll file I/O per case
- `assert_migration_warns_about(result, knob_or_key)` — structural assertion that a specific dropped/renamed/reshaped
  item appears in the dry-run's warnings list, following the `assert_decision`/`assert_reason_includes` naming
  convention used elsewhere in this suite

**Fantasy callsites (test-facing API sketches):**

- `migrate_shfmt_permissions_config(old_cfg).new_config`
- `migrate_shfmt_permissions_config(old_cfg).warnings  # dropped knobs, renames, reshapes`
- `assert_migration_warns_about(result, "defaultDecision")`

**Testability-driven production decisions:**

- Migration logic lives in a pure `lib/config_migration.py` function with no filesystem access, so tests construct plain
  dicts and assert the translated dict + warnings list without touching disk — `bin/migrate-config` is the only I/O
  layer, tested via `run_entrypoint` against a sandboxed `HOME`
- `bin/migrate-config`'s dry-run/`--write` split exists specifically so the destructive path (actually writing) is a
  single flag-gated branch, testable in isolation from the (much larger) translation-logic test surface

## Assumptions

- **`packages/command-policy/lib/config.py` and `allowed_command.py` still use the OLD key names `allowedVariables` and
  `additionalAllowedPrefixes`, i.e. the B1/B2 renames handed to leaf 213153 were never applied** — confirmed (Read
  `lib/config.py:74-89` and `lib/allowed_command.py:28-39` directly (2026-09-17): `Config.from_dict` reads
  `cfg.get("additionalAllowedPrefixes")`; `AllowedCommand.from_entry` reads `entry.get("allowedVariables")`. Neither has
  been renamed.)
- **`pathValidation:false` -> `hasNoPathParameters:true` is the one rename that DID land in leaf 213153's shipped code**
  — confirmed (`lib/allowed_command.py:19,37` — `has_no_path_parameters` field exists, parsed from
  `entry.get("hasNoPathParameters", False)`, matching leaf `20260914-213049`'s B4 resolution exactly.)
- **`propagate` -> `evaluateNamedValueAsCommand` (as this leaf's own pre-existing objective text claimed) is still the
  settled design** — refuted (`docs/improvements/improvement-20260914-213049-shfmt-golden-corpus-harness.md:448-463`
  (B5, SUPERSEDED 2026-09-16): `propagate` is not renamed at all — it is replaced by an ordinary
  `{"type": "nestedCommand"}` filter, settled during leaf `20260914-213652`'s planning and confirmed again in that
  leaf's own file at lines 79-81. The spelling `evaluateNamedValueAsCommand` is the original, now-dead proposal.)
- **`programGlob` is an already-settled name for the `pluginProgram` rename, adopted from an earlier leaf's decision** —
  refuted (grep for "programGlob" across every file in `docs/improvements/` (2026-09-17) returns exactly one hit: this
  leaf's own pre-existing draft text. Leaf `20260914-213049`'s B6 only flags the `pluginProgram`/plugin vocabulary
  collision as "worth resolving" — no leaf ever picked a final name. It is finalized in THIS planning session, not
  carried forward from elsewhere.)
- **`pluginProgram` matching (resolving `CLAUDE_CODE_PLUGIN_CACHE_DIR` and glob-matching the invoked command path) has
  matching-time implementation somewhere in command-policy already, or is owned by an identifiable leaf** — refuted
  (grep for "pluginProgram" across `docs/improvements/` and command-policy's `lib/` (2026-09-17): no `lib/` file
  implements it, and no leaf's plan (213502 Filter/Parser, 213652 Pipeline, 213825 land-across-consumers) mentions
  porting it. It is a genuine orphan, addressed here via the cross-leaf hand-back to leaf 213652 recorded in
  Implementation Notes.)
- **Leaf `20260914-213502` (Filter/Parser) and leaf `20260914-213652` (Pipeline) are both planned but not yet
  implemented as of this planning session, so this leaf's own implementation-time assumptions about `Config.explain()`'s
  richness and `Config.decision_for()`'s existence must be re-checked at implementation start rather than assumed** —
  confirmed, then PARTLY OVERTAKEN WITHIN THE SAME SESSION, which is itself the finding worth keeping. First measurement
  (2026-09-17, early): both Meta blocks read `- Status: ready-to-implement` with no `- Impl started:` line. Second
  measurement (same session, after the plan was written): leaf `20260914-213502` now reads `- Status: completed` with
  `Impl finished: 2026-09-17T18:37:45+02:00` — it was implemented concurrently by a peer session
  (`claude-marketplace-impl-20260914-213502`) while this plan was being drafted. Leaf `20260914-213652` was still
  `ready-to-implement` at the close of planning. The re-check-at-implementation-start instruction therefore stands MORE
  strongly, not less: sibling leaves in this trunk move while a leaf waits its turn, so any sibling status written into
  a plan is a snapshot with a timestamp, never a standing fact to build on.
- **`conftest.py`'s existing `run_entrypoint` fixture already supports overriding `HOME` per test invocation, so
  migration tests can be isolated from the real user's `~/.claude/` without a new fixture** — confirmed
  (`packages/command-policy/tests/conftest.py:51-72` — `run_entrypoint(name, args=(), stdin=None, env=None)` overlays
  `env` on `os.environ` for the subprocess call; passing `env={"HOME": str(tmp_path)}` sandboxes any `~/.claude/` path
  resolution inside `bin/migrate-config`.)

## Design Decisions

### Whether this leaf settles+applies the abandoned config-key renames itself or splits them into a new sibling leaf

- **Chosen:** This leaf both settles final names and applies them, extending the already-completed
  `Config`/`AllowedCommand` value objects directly
- **Rationale:** Already the natural owner: this leaf's objective already claims the rename hand-back from leaf 213049's
  audit, and the migration skill needs the final names to exist before it can translate old configs — keeping it in one
  place avoids a cross-leaf dependency for a small amount of engine work. Avoids another baton-pass round-trip:
  splitting into a sibling leaf means a full SHAPE/DESCEND cycle for what is a small, contained rename, not worth the
  overhead this late in the trunk.
- **Rejected alternatives:** Drop the renames entirely and migrate old keys as pass-through (abandons B1/B2/B6
  permanently); split a new discovered sibling leaf to own settling+applying the renames, with this leaf only doing the
  migration translation once that leaf lands
- **Date:** 2026-09-17

### Whether to hand back programGlob matching-time implementation to leaf 213652

- **Chosen:** Yes — this leaf settles the renamed config field/shape AND writes a cross-leaf hand-back requiring leaf
  213652 to implement the actual glob/cache-root matching logic, mirroring leaf `20260915-010959`'s own precedent of
  handing a contract change back to a not-yet-implemented sibling
- **Rationale:** rationale not captured
- **Rejected alternatives:** Settle the field/shape only and flag matching-time support as an open gap for an
  unspecified future improvement, leaving migrated `programGlob` entries inert until something else ports the matching
  logic
- **Date:** 2026-09-17

### Final names for the three previously-unsettled config-key renames

- **Chosen:** `allowedVariables` -> `onlyTheseVariables`; `additionalAllowedPrefixes` ->
  `additionalAllowedPathPrefixes`; `pluginProgram` -> `programGlob`
- **Rationale:** rationale not captured (proposed by the planner as the only reasonable reading of each B-item's stated
  intent; accepted without requested changes)
- **Rejected alternatives:** None proposed — the user was invited to object to any of the three before they were
  persisted and did not
- **Date:** 2026-09-17

### Whether the equivalence-search skill verifies its own suggested candidate against Config.decision_for() before presenting it, once leaf 213652 ships that method

- **Chosen:** No — pure prose reasoning only, never shells out to `decision_for` even though it will exist by the time
  this leaf implements
- **Rationale:** The caller is already an agent starting from empty context, handed only the allow/deny rules and asked
  to figure out an equivalent. If it cannot find a suitable replacement and still hands one back confidently, that
  candidate gets tested for real a moment later when the calling session actually tries to run it — the engine denies it
  again if it was wrong, so the self-correction loop the whole outcome model is built on already catches a bad
  suggestion. A pre-verification step would also reintroduce engine logic into what should stay a thin,
  skill-authoring-only consumer of `Config.explain()`.
- **Rejected alternatives:** Verify via `decision_for` before presenting: run the candidate through
  `Config.from_dict(cfg).decision_for(candidate)` and only present candidates that come back allow — rejected as
  unnecessary engine-logic creep given the natural verification-by-next-attempt already exists, and as scope drift for a
  leaf explicitly chartered as skill-authoring, not engine work
- **Date:** 2026-09-17

### Whether bin/migrate-config overwrites an existing ~/.claude/command-policy.json without confirmation

- **Chosen:** Never silently overwrite — compute the migrated output, diff it against the existing file if one is
  present, and the skill uses `AskUserQuestion` to confirm before `bin/migrate-config --write` actually writes
- **Rationale:** rationale not captured
- **Rejected alternatives:** Refuse outright and tell the user to move the existing file aside manually before
  re-running — rejected as less convenient for the expected re-run-after-a-config-tweak case, at the cost of a bit more
  implementation surface (the diff + confirm round-trip)
- **Date:** 2026-09-17

### Name of the new user-facing bin/ migration command

- **Chosen:** `migrate-config`
- **Rationale:** rationale not captured
- **Rejected alternatives:** `migrate-policy-config` (keeps the exact "-policy" word every other user-facing command
  carries; rejected as unnecessarily long once the plugin's own name already says "policy")
- **Date:** 2026-09-17

## Success Criteria

- [x] `AllowedCommand` parses `onlyTheseVariables` (not `allowedVariables`) and `explain()` states which variables are
      permitted when set
- [x] `AllowedCommand` parses a `programGlob` entry (`marketplace`/`plugin`/`path` dict, mutually exclusive with
      `program`) with the same `..`/leading-`/` validation the old engine applied
- [x] `Config` parses `additionalAllowedPathPrefixes` (not `additionalAllowedPrefixes`); the `AllowedPathPrefixes` class
      and its `explain()` label reflect the new name
- [x] Every existing test in `test_allowed_command.py`, `test_config.py` and `test_name_collection.py` that referenced
      the old names is updated and passes
- [x] A cross-leaf hand-back note for leaf `20260914-213652` (`programGlob` matching-time implementation) exists in this
      file's eventual Interface section — RECONCILED rather than merely noted: 213652 was already `completed`, so this
      leaf implemented the matching-time half directly (`AllowedCommandPolicy._entry_matches_program`/
      `_program_glob_pattern`), covered by both unit tests (`test_allowed_command_policy.py`) and a black-box decision
      case (`test_permission_decisions.py`)
- [x] `bin/migrate-config` with no flags never writes, creates, or deletes any file, against a temp `HOME` with no
      existing `command-policy.json`
- [x] `bin/migrate-config`'s dry-run output plainly states the four dead knobs (`defaultDecision`,
      `sensitiveVariableResponse`, `pathValidationResponse`, `filterRejectionResponse`) and the deny-by-default
      strictness change, every time, regardless of whether the source config set them
- [x] `propagate` (both string and object forms) migrates to an appended `{"type": "nestedCommand", ...}` filter entry,
      never as a renamed top-level key
- [x] `pathValidation:false` in a source entry migrates to `hasNoPathParameters:true` in the output entry
- [x] `allowedReadPaths` entries (deprecated old key) migrate into equivalent `allowedPaths` entries and merge with any
      pre-existing `allowedPaths`
- [x] `bin/migrate-config --write` against a target that already has a `command-policy.json` only writes after the
      skill's `AskUserQuestion` confirmation; the bin script itself computes but never silently applies an overwrite
- [x] The original `shfmt-permissions.json` file(s) are never modified or deleted by any part of this migration
- [x] `find-auto-allowed-command` is `user-invocable: false` and contains no call to `Config.decision_for` or any
      equivalent verification step
- [x] `find-auto-allowed-command`'s SKILL.md instructs running `explain-policy` and reasoning over its output; it
      defines no structured input parameters
- [x] `docs/knowledgebase/command-policy-decision-model.md` documents both skills (extended, not duplicated into a new
      article)

## Implementation TODO

- [x] Update status to in-progress
- [x] Write tests for `AllowedCommand.only_these_variables` (renamed from `allowed_variables`) covering JSON key
      `onlyTheseVariables` and the `explain()` enrichment; implement the rename + `explain()` addition to pass; refactor
- [x] Write tests for `AllowedCommand.program_glob` (new field: `marketplace`/`plugin`/`path`, mutually exclusive with
      `program`, `..`/leading-`/` validation); implement to pass; refactor
- [x] Write tests for `AllowedPathPrefixes` (renamed from `AllowedPrefixes`, `_label` ->
      `additionalAllowedPathPrefixes`); implement the rename; refactor
- [x] Write tests for `Config.allowed_path_prefixes` (renamed from `allowed_prefixes`) and `Config.from_dict` reading
      `additionalAllowedPathPrefixes`; implement to pass; refactor
- [x] Update every existing call site and assertion in `test_allowed_command.py`, `test_config.py`,
      `test_name_collection.py` that references the old names so the full suite passes green again
- [x] Write tests for `migrate_shfmt_permissions_config()` covering: the four dropped knobs always warn; the
      `commandSubstitutionResponse` `ask`/`block` -> `deny` collapse (`via-allowed-commands` unchanged); the three
      per-entry key renames; `pathValidation:false` -> `hasNoPathParameters:true`; `propagate` (string and object forms)
      -> appended `nestedCommand` filter; `allowedReadPaths` -> merged `allowedPaths`; implement
      `lib/config_migration.py` to pass; refactor
- [x] Write the `shfmt_permissions_config_fixture` and `assert_migration_warns_about` test helpers
- [x] Write tests for `bin/migrate-config` via `run_entrypoint` against a sandboxed `HOME`: no-flag dry-run writes
      nothing and prints the migrated config + warnings + diff (when a target exists); `--write` writes
      `command-policy.json`; implement `bin/migrate-config` to pass; refactor
- [x] Write `packages/command-policy/skills/migrate-config/SKILL.md` (reads dry-run output, presents summary + diff,
      `AskUserQuestion` confirms, then invokes `--write`) and the thin `commands/migrate-config.md` wrapper
- [x] Write `packages/command-policy/skills/find-auto-allowed-command/SKILL.md` (`user-invocable: false`; instructs
      running `bin/explain-policy` and reasoning in prose over the rendered rules; no structured parameters; explicit
      framing that this runs after a deterministic deny, never inside the hook's decision)
- [x] Record the cross-leaf hand-back to leaf `20260914-213652` (`programGlob` matching-time implementation) in this
      file's Interface section
- [x] Extend `docs/knowledgebase/command-policy-decision-model.md` with a section documenting both skills
- [x] Run the full suite: `cd packages/command-policy/tests && nix-shell --run pytest`
- [x] Update status to completed

## Interface

**RECONCILIATION, not a pending hand-back:** the plan's cross-leaf hand-back to leaf `20260914-213652` (`programGlob`'s
matching-time behaviour — resolving `CLAUDE_CODE_PLUGIN_CACHE_DIR`, building the wildcarded-version glob pattern,
`fnmatch`-ing the invoked command against it) anticipated that leaf still being unimplemented when this leaf started.
Checking its Meta status at implementation start found it already `completed` (`Impl finished: 2026-09-17T18:xx`), so
per this leaf's own Implementation Notes the hand-back became a direct extension of that leaf's already-shipped
`AllowedCommandPolicy` — the same kind of accepted, rare reconciliation this leaf itself performs on completed leaf
`20260914-213153`'s `Config`/`AllowedCommand`.

**What this leaf produces (beyond the two skills and the migration module):**

- `AllowedCommand.program_glob` (config-shape field, `packages/command-policy/lib/allowed_command.py`) plus a new
  `program_label` property every reason-construction call site now reads instead of `.program`, so a `programGlob` entry
  without a plain `program` never surfaces a bare `None` in a `Reason`.
- `AllowedCommandPolicy`'s matching-time half (`packages/command-policy/lib/allowed_command_policy.py`):
  `_entry_matches_program`/`_program_glob_pattern` module functions. A `programGlob` entry's candidate match is now
  `fnmatch(command.command_word, "{cache_root}/{marketplace}/{plugin}/*/{path}")`, mirroring shfmt-permissions'
  `_build_plugin_program_pattern`/`_check_command_allowed`. Validation (`..`, leading `/`, completeness) already
  happened at `AllowedCommand.from_entry` construction time (this leaf's own Part A), so the matching function trusts
  the stored dict and never re-validates or returns `None` for an incomplete config the way the old engine's
  `_build_plugin_program_pattern` did.
- `migrate_shfmt_permissions_config`'s per-entry translation renames `pluginProgram` -> `programGlob` verbatim (the dict
  shape is unchanged, so no field-level translation is needed beyond the key rename itself).

**Contract for downstream leaves:** any future leaf reasoning about `allowedCommands` entry matching must go through
`_entry_matches_program`, not a bare `entry.program == command.command_word` comparison — a `programGlob` entry has no
`program` at all (it is `None` by construction), and skipping this function silently drops every such entry from
matching. Any future leaf constructing a `Reason` that names an entry should read `entry.program_label`, not
`entry.program`, for the same reason.

## Related Past Improvements

- `improvement-20260914-213049-shfmt-golden-corpus-harness.md` — source of the original B1/B2/B4/B5/B6 config-key-rename
  audit; this leaf verifies which of those renames actually landed and completes the ones that didn't (and confirms
  B5/`propagate` was superseded by a filter reshape, not a rename).
- `improvement-20260915-010959-deny-reason-escalation-paths.md` — froze the `find-auto-allowed-command` contract name
  and its unconditional-pointer design that skill C implements; also the leaf this one depends on for implement-order.
