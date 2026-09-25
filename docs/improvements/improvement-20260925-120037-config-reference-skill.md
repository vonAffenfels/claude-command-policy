# Improvement 20260925-120037: Config Reference Skill

## Meta

- Related Ticket: None
- Status: ready-to-implement
- Created: 2026-09-25
- Updated: 2026-09-25
- Plan started: 2026-09-25T12:00:37+02:00
- Plan finished: 2026-09-25T15:40:41+02:00

## This Improvement's Objective

Bring back a command-policy:config skill, the successor to shfmt-permissions:config. It documents what command-policy
can do and which command-policy.json settings achieve it, so a session can offer the right auto-approval route and
author correct config entries. It also makes `add-allow-policy` visible where sessions actually decide, in the
find-auto-allowed-command agent's fallback and the rendered session rules, so Claude proposes a durable allow entry
without being asked.

## Context / Why This Exists

The predecessor plugin shipped `packages/shfmt-permissions/skills/config/SKILL.md` (in the `claude-marketplace` repo,
~1050 lines, `user-invocable: false`). It served two purposes at once: a schema reference (every key, filter type,
parser type, bundled parser's named values, path validation, merge semantics, escape hatches, worked examples) and a
"view or update" workflow (default to user scope, read the config before changing it, never create a config full of
defaults). Its description triggered on "stop prompting for X", "always allow", "block/restrict a command", so a session
could offer auto-approval as an option even when the user never named the plugin.

command-policy has no equivalent. The author-facing knowledge that exists today is scattered, and none of it is written
for someone editing a config:

- `docs/knowledgebase/command-policy-decision-model.md` is written for developers of this repo and is not loaded into
  user sessions.
- `Config.explain()` (SessionStart/SubagentStart injection, `bin/explain-policy`) renders filtered entries only as "must
  pass N filter(s)" and does not say which filters or how to write one.
- `skills/migrate-config/SKILL.md` explains only the old → new deltas and still points at `shfmt-permissions:config` for
  its "where to write" convention. That reference breaks once the old plugin is uninstalled.
- An earlier improvement (`20260914-213825`, audit-session-policy footer) recorded that "command-policy has no
  config-editing skill of its own yet".

The new schema differs from the old one in ways that make the old skill actively wrong: the four decision knobs are
gone, keys are renamed (`onlyTheseVariables`, `programGlob`, `hasNoPathParameters`, `additionalAllowedPathPrefixes`),
`propagate` became the `nestedCommand` filter, `structured` parsers use per-slot `options`/`positionals` with
`path: false`, every argument is a path candidate by default, and the escape hatches are now `bypass-policy` and
`add-allow-policy`. Several of these have sharp edges an author has to understand. For example, an audit of the
operator's own config found `hasNoPathParameters` declared falsely on three entries (knowledgebase, "three ways, and
only three").

## Proposed Approach

- Ship a `skills/config/SKILL.md` (`command-policy:config`): a reference for the current schema plus a workflow for
  changing config.
- Write path (operator agreed 2026-09-25): new `allowedCommands` entries go through `add-allow-policy`, which asks the
  human, shows the diff and records the stated intent. Everything `add-allow-policy` cannot do (edit or remove an entry,
  `blockedCommands`, `allowedPaths`, `additionalAllowedPathPrefixes`, `sensitive*`) is a direct Edit of
  `command-policy.json`, checked by the existing PostToolUse lint hook. The operator's consequence: `add-allow-policy`
  must keep supporting anything an `allowedCommands` entry can express. It already does this structurally, because the
  entry is passed through opaquely (see Assumptions). Validation is added by the entry refactor below.
- Entry refactor (settled 2026-09-25, details under Implementation Notes):
  `AllowedCommand.from_entry(entry, context, source)` builds Filter/parser value objects once. Every defect becomes an
  `InvalidFilter` / invalid-parser stand-in that fails closed plus a reported problem, never a decision-time
  `ConfigError`. `programGlob` defects included. `PathResolutionContext` is bound at creation. Static problems flow
  through `Config.warnings()`. Problems that need a parser's capabilities come from a new describe protocol (stdin
  `{"describe": true}`), computed only on reporting paths via a describer passed in by the entrypoint.
  `add-allow-policy` refuses a proposal with problems before asking. This absorbs the decision-time half and the
  `programGlob` load-time half of planned improvement `20260920-152953`.
- Advertising `add-allow-policy` (in scope, operator decision 2026-09-25: "thats a few lines added here and there that
  hardly necessitates its own improvement"). The operator observed that Claude never proposes `add-allow-policy`
  unprompted and suspected a no-prompt rule. Measured cause: there is no such rule. The command is simply almost never
  shown to a session (see Assumptions). A skill alone does not fix this, because a skill loads only when its description
  triggers, and a denial routes to the agent, not to the skill. Two text changes:
  1. `agents/find-auto-allowed-command.md` step 4: the "nothing achieves the goal" conclusion names both escalations and
     when to pick each. `bypass-policy` is for a one-off. `add-allow-policy` is for a command shape that will recur, and
     it proposes the durable entry in its canonical form.
  2. `Config.explain()` gains one static line, next to `_DECOMPOSITION_ADVISORY` and like it never config-derived. It
     names `add-allow-policy` with `reason_renderer.ADD_ALLOW_POLICY_CANONICAL_FORM` as the way to propose a durable
     allow entry, and points at `command-policy:config` for writing one. It reaches the main session (SessionStart) and
     every subagent (SubagentStart) through the same render.

## Affected Components

- `lib/allowed_command.py`: builds value objects, carries `source`, `problems()`, `programGlob` as a problem.
- `lib/filter.py` (+ `InvalidFilter`, `paths`/`nestedCommand` dispatch), `lib/paths_filter.py`,
  `lib/nested_command_filter.py`, `lib/action.py` if action defects become problems.
- Parser family: new parser factory (moved from `AllowedCommandPolicy._build_parser`), `lib/structured_parser.py`
  (retired keys → problem), `lib/provided_parser.py` (unknown name → problem), `lib/command_parser.py`,
  `lib/external_parser_factory.py` / a new describer edge object.
- `lib/allowed_command_policy.py`: works on built objects; loses `_build_parser`, `_require_*`, string dispatch.
- `lib/path_resolution.py` (project constructor), `lib/config.py` (context param and storage, static-problem Warnings,
  `described_problems`, `with_additional_warnings`, static `add-allow-policy` line in `explain()`),
  `lib/config_loader.py` (one context for all layers).
- `lib/escalation_policy.py`, `lib/reason.py`, `lib/reason_renderer.py`, `lib/add_allow_write.py`: refuse a proposal
  with problems.
- `bin/command-policy-render-session-start`, `bin/command-policy-render-subagent-start`, `bin/explain-policy`,
  `bin/command-policy-lint-config-on-write`, `bin/add-allow-policy`: construct the describer.
- `parsers/*.py` (all 17): answer describe.
- `agents/find-auto-allowed-command.md`, new `skills/config/SKILL.md`, `skills/migrate-config/SKILL.md`.
- `docs/knowledgebase/command-policy-decision-model.md`, and
  `docs/improvements/improvement-20260920-152953-uncaught-configerror-fail-open.md` (absorbed parts noted).
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`: version bump.
- Tests: `test_allowed_command.py`, `test_allowed_command_policy.py`, `test_config.py`, `test_filter.py`,
  `test_structured_parser.py`, `test_provided_parser.py`, `test_action.py`, `test_permission_decisions.py`,
  `test_bundled_parsers.py`, `test_hook_envelopes.py`, new describe and skill-drift tests.

## Implementation Notes

### Entry validation (settled)

- **Entry validation.** On 2026-09-25 the operator approved "validate via `Config.from_dict`". Measurement showed
  `from_dict` misses most defects (refuted assumption). The operator then proposed, and it was agreed:
  - `AllowedCommand.from_entry` builds `Filter`/parser value objects once instead of storing dicts.
  - `Filter.from_definition` returns either a working Filter or an `InvalidFilter(problems)` that always fails closed
    (generalising today's `UncompilableFilter`). No raising at decision time.
  - `AllowedCommand` exposes a public `problems()`: its own problems (e.g. `programGlob`), each `InvalidFilter`'s, the
    parser's, and the cross-object checks that need filter AND parser together (`optionValue` needs a value-consuming
    parser, `nestedCommand` needs a sub-command-publishing parser). A Filter cannot judge those alone.
  - `add-allow-policy` calls `problems()` before asking. The lint hook calls it after direct edits.
  - This removes the decision-time `ConfigError` source that the planned improvement `20260920-152953` exists to catch.
  - Settled 2026-09-25: (a) `PathResolutionContext` is bound at CREATION, not passed into `parse()`/`matches()` (see
    Design Decisions). (b) A parser describe protocol is added now (see Design Decisions). (c) No split: everything
    stays in this improvement.
  - `programGlob` defects become problems too (operator 2026-09-25: "Putting it on a known system is always good"). The
    load-time raise in `AllowedCommand.from_entry` goes away; the entry never matches and reports its problem.
  - Describe protocol, settled with the operator 2026-09-25:
    1. Asked via stdin `{"describe": true}` (same channel as `{"arguments": [...]}`), never a CLI flag, which could
       collide with the wrapped program's own flags.
    2. Reports `publishesNestedCommands` (bool) and the named values the script may publish (so a `namedValue` filter
       naming one it never publishes is a problem). The `nestedCommands` channel carries entries of `{text, shape}` with
       no key of their own, so a boolean is the whole capability; there is nothing to key per nested command. Also
       `optionsWithValues`, which the `optionValue` check needs (operator approved 2026-09-25).
    3. A script that does not answer describe correctly (non-zero exit, timeout, invalid JSON, missing keys) is a breach
       of contract and therefore a PROBLEM. Operator: "there are no live scripts to protect by keeping the behaviour".
    4. Every bundled parser implements it, and a test checks each description against what the script actually
       publishes.
  - WHEN describe runs: only on the reporting paths, never on the decision path (operator 2026-09-25: "300ms per hook is
    a bit much. Let's go with your design"). See "Problems split by whether they need I/O" below.

### Problems split by whether they need I/O

The operator flagged (2026-09-25) that a process-wide cache stored on a copy-on-write value object would be a mutable
object shared between copies. This applies: `Config._replace` (`lib/config.py:166-181`) hands every field to the new
instance on every `with_*`/`merged_with`. So the describer never lives on a value object:

- **Static problems** need no I/O: unknown filter/parser type, uncompilable pattern, malformed `programGlob`, unknown
  bundled parser name, `optionValue`/`nestedCommand` against a PURE parser. `AllowedCommand` computes them at
  construction. `Config.from_dict` turns them into `Warning`s with layer provenance (replacing
  `_collect_allowed_command_filter_warnings`), so they flow through the existing warnings channel for free (`explain()`,
  SessionStart/SubagentStart, lint hook).
- **Described problems** need the describe subprocess: an external/bundled parser breaching the describe contract,
  `nestedCommand` on a parser that does not publish nested commands, `optionValue` on an option the parser does not
  declare, `namedValue` on a name the parser does not publish. They are computed by an explicit call that receives the
  describer as an argument (e.g. `config.described_problems(describer)`, returning `Warning`s). The reporting entrypoint
  folds the result back in copy-on-write (e.g. `config.with_additional_warnings(...)`) before rendering.
- **The describer** is an edge object next to `ExternalParserFactory`. It owns the `subprocess.run` and a per-instance
  memo keyed by script path. Each reporting entrypoint constructs one as a local and drops it at exit, so "per-process
  cache" means the entrypoint's local object, never module state and never a value-object field.
- **Reporting entrypoints that construct a describer:** `command-policy-render-session-start`,
  `command-policy-render-subagent-start`, `explain-policy`, `command-policy-lint-config-on-write`, `add-allow-policy`
  (the ask path in `escalation_policy.add_allow_policy_transform` is reached from the Bash PreToolUse hook, so exactly
  that one proposal's entry is described there). `command-policy-analyze-bash-command`/`-analyze-path` never construct
  one.
- Layer provenance: `AllowedCommand` carries its `source` layer as an immutable field, set by
  `Config.from_dict(cfg, source)`, so a described problem on a merged config still names its layer (operator
  2026-09-25). The describer is passed in as an argument, as above (operator: "right lets try passing it in then").

### Skill outline (agreed 2026-09-25)

File layout: ONE `SKILL.md`, no reference files (operator 2026-09-25: "The problem with reference files is that they
trigger a read outside the current repository warning". The plugin's files live in the plugin cache, outside every
project, so an on-demand Read prompts). The `references/` split below is therefore folded into `SKILL.md` as sections
after the core, and kept compact to stay well below the old skill's ~1050 lines.

`skills/config/SKILL.md`:

1. **Frontmatter.** `name: config`, `user-invocable: true` (operator 2026-09-25: "I don't see any harm in allowing it").
   The operator's primary route is still plain language ("please change my command policy config"). The old
   `shfmt-permissions:config` description matched poorly in practice: the operator "pretty much had to spell
   shfmt-permissions config out". The old description led with the plugin name ("View or update the shfmt-permissions
   configuration …"). The new one leads with the user's own phrasings: change / update / edit my command policy,
   permissions or auto-approval config; stop asking for X; always allow X; block X. The static `explain()` line (see
   Proposed Approach) names `command-policy:config` in every session's injected context, so the skill name is present
   when such a request arrives. The description triggers on: wanting a command to stop prompting / be auto-approved /
   always allowed; blocking or restricting a command or path; reducing permission prompts; any question about
   `command-policy.json` or how the policy decides. It explicitly does NOT trigger on an ordinary denial, which routes
   to `find-auto-allowed-command`.
2. **The model in one screen.** `allow` is the only outcome that grants. Everything not allowed is deny+hint, which is
   routing, not a block. `bypass-policy` is a one-off escalation to the human. `add-allow-policy` is the durable one.
   Deny-by-default: there are no leniency knobs.
3. **Where config lives, and the merge.** User file by default, project file only on explicit request. Lists union,
   `commandSubstitutionResponse` is overlay-wins only when the overlay sets it, and a project can only widen.
4. **Changing config (workflow).** Read the effective config (`explain-policy`) and the raw file first. New
   `allowedCommands` entry → `add-allow-policy` (canonical grammar, quote the whole entry). Everything else → direct
   Edit, then read the lint output. Problems are reported by `add-allow-policy` (before asking) and by the lint hook.
   Never create a config full of defaults. When to choose `bypass-policy` versus `add-allow-policy`.
5. **Evaluation order and what each objection means.** The six passes in order. Categorical objections (sensitive
   path/variable, blocked command, substitution in deny mode, redirect outside allowed paths) versus near-miss, and
   which ones `bypass-policy` escalates to `ask`.
6. **Entries describe command shapes.** Filters AND within an entry, entries OR across. Every non-vouching entry reports
   its own reason. Write narrow entries rather than scoping a key to one filter.
7. **Variables, substitutions, unknowable arguments.** `onlyTheseVariables` vouches for NAMES, never values. Absence is
   never provable next to unknowable content. Presence only from a separate literal word. An index shifts after an
   unknowable argument. Decomposition as the recovery.
8. **Path containment.** Project root + `additionalAllowedPathPrefixes`, symlinks resolved, every argument a path
   candidate unless ruled out. The three ways to carry unknowable content. `hasNoPathParameters` is a factual claim
   about the program, never a waiver.
9. **Problems.** What counts as one (static versus described), where each is shown, and that a problem entry never
   vouches.
10. The reference sections below follow in the same file.

Reference sections, after the core in the same `SKILL.md`:

- `schema.md`: top-level keys (table: key, type, meaning, merge rule). `allowedCommands` entry keys (`program` |
  `programGlob`, `filters`, `onlyTheseVariables`, `hasNoPathParameters`, `commandParser`, bare-string shorthand).
  `allowedPaths` tool sets, noting it never denies. `sensitivePaths` is a substring match on raw text.
- `filters.md`: all ten filter types, `block`/`required`, "target absent always fails", "a filter sees only what the
  parser produced", `paths` (`exactly`), `nestedCommand` (fails closed, needs a publishing parser, the `--dry-run` two-
  entry composition).
- `parsers.md`: the knowledge ladder (default → `structured` → `provided`/`command`). `structured` schema (per-slot
  `options` with `arguments` and `path`, `positionals`, `doubleDashStops`; retired keys are problems). Bundled parser
  table (named values, `publishesNestedCommands`, `optionsWithValues`). Writing your own `command` parser: the
  `{"arguments": …}` and `{"describe": true}` stdin contract, output keys, `nestedCommands` with `shape`, and that a
  contract breach is a problem.
- `escape-hatches.md`: `bypass-policy` (must be the sole statement; what forces `ask`), `add-allow-policy` grammar and
  its eight violation codes, `audit-session-policy`.
- `examples.md`: a small set of worked entries: git subcommand allow-list via the provided parser, sed without `-i`,
  find without exec/delete, timeout/nix-shell via `nestedCommand`, a custom tool with a `structured` parser using
  `path: false`, `allowedPaths` for a directory outside the project.

Dropped from the old skill as obsolete: the four decision knobs, `propagate`, per-entry `pathValidation`,
`allowedVariables`, `pluginProgram`, `allowedReadPaths`, the CASE A/B split, parser `fallback`,
`options_with_arguments`/`pathOptions`/`pathPositionals`, `bypass-shfmt-permissions`, the `propose-*` commands,
`render-shfmt-permissions`, and the unmatched-commands log. `skills/migrate-config/SKILL.md`'s "Where to write" pointer
moves from `shfmt-permissions:config` to `command-policy:config`.

Drift test (candidate): it asserts the skill files name every member of each code registry, so adding a filter type, key
or bundled parser without documenting it fails the suite. Registries: filter types (`filter.py`'s registry plus
`paths`/`nestedCommand`), top-level keys read by `Config.from_dict`, entry keys read by `AllowedCommand.from_entry`,
parser types, the `parsers/*.py` listing, each bundled parser's describe output against its row in the skill's bundled
parser table, and the `add-allow-policy` violation codes.

### Failure modes of the describe call

- Each describe is one subprocess (`ExternalParserFactory.raw_output_for` pattern: `subprocess.run`, JSON on stdin).
  Running it at entry construction means every config load, i.e. EVERY hook invocation (each Bash command, each
  Read/Grep/Glob, each SessionStart/SubagentStart), pays one Python start per `provided`/`command` entry. The operator's
  config has on the order of ten such entries (git, find, awk, gawk, sed, nix-shell, nix, timeout, …). Measured ~30 ms
  per bundled parser start, so ~300 ms added to every hook invocation (see Assumptions).
- The decision path does not need the capabilities: an external parser that publishes nothing for a `nestedCommand`
  filter already fails closed (empty list), and an `optionValue` filter over a value the script never produces never
  matches.
- Candidate: value objects never run subprocesses (the existing purity line). `problems()` takes the capability lookups
  through an injected edge collaborator (a describer next to `ExternalParserFactory`), caches per process, and is called
  only on the validation paths: `add-allow-policy`, the lint hook, and the Warnings rendered at
  SessionStart/SubagentStart/`explain-policy`.

### Size of the construction-time refactor (measured 2026-09-25)

- `PathResolutionContext` gains a named constructor for the project (today's `Config._path_resolution()` body).
  `config_loader.load_config_from_environment` builds ONE context and passes it to every layer's `from_dict`.
  `Config.from_dict(cfg, source, path_resolution=None)` defaults to the project context, so the 35 `from_dict` calls in
  `test_config.py` and the spec suite's single `decision_for` helper (`tests/test_permission_decisions.py:97`, which
  builds the config INSIDE each `cwd_pinned_inside_project` block) need no change. `Config` stores the context and
  `_policies`/`decision_for_path` reuse it instead of rebuilding it. `merged_with` keeps one context.
- `AllowedCommand.from_entry(entry, path_resolution)` builds the parser (today's `_build_parser` moves out of
  `AllowedCommandPolicy` into a parser factory that returns an invalid-parser stand-in instead of raising) and every
  filter. `Filter.from_definition` takes over the `paths`/`nestedCommand` dispatch that `_filter_passes` does by string
  today, and returns `InvalidFilter(problems)` for every defect. `AllowedCommand.problems()` adds the entry-level and
  filter×parser checks. `__eq__`/`__hash__`/`explain` keep working off the raw definitions.
- `ProvidedParser`: an unknown bundled name becomes a problem instead of a silent `""` command.
- `AllowedCommandPolicy` loses `_build_parser`, both `_require_*` raisers and the string dispatch. The knowability logic
  (block vs required, knowable-only re-parse) stays, but operates on built objects.
- `Config._collect_allowed_command_filter_warnings` is replaced by surfacing `problems()` as Warnings, so
  `explain()`/lint/SessionStart show them through the existing channel.
- Tests: the 21 `from_entry` calls in `test_allowed_command.py` gain a context argument (one fixture). The entries in
  `test_allowed_command_policy.py` are built with a context. The 21 `pytest.raises(ConfigError)` cases (spec 7, policy
  4, allowed_command 4, structured_parser 3, filter 2, action 1) are re-adjudicated: a match-time defect becomes "entry
  never vouches + problem reported". The `programGlob` load-time raise needs its own decision (it breaks the WHOLE
  config today; `20260920-152953`).
- Behaviour note: the context is fixed at load rather than per decision. Every production process (hook, CLI, session
  audit) loads once in the same environment it decides in, so no verdict changes. Tests that change cwd/env between load
  and decide would notice; the spec suite does not.

### PathResolutionContext (measured 2026-09-25)

A value object standing in for the ambient filesystem reads path handling needs: a project root (`cwd`), `home`, and the
`exists`/`is_directory`/`realpath` predicates. It exists so parsers, filters and policies are pure and testable against
declared state. Its operations: `absolute_path_of` (`~` expansion, join onto the project root, `normpath`, symlink
resolution), `exists`, `is_directory`, and `is_contained(path, prefixes)`, which realpaths both sides and uses a
trailing-separator guard.

The only production producer is `Config._path_resolution()` (`lib/config.py:381-389`). It is built fresh per call: root
= `CLAUDE_PROJECT_DIR`, falling back to `os.getcwd()`, with the real `os.path` predicates. It is called twice per
`decision_for` (once each for the redirect and allowedCommands policies in `_policies`) and once per
`decision_for_path`. `PathResolutionContext.for_process()` (root = `os.getcwd()`) is used only by tests.

Consumers, and WHEN each needs it:

| Consumer                                        | Uses                                                                    | Needed at                                                                        |
| ----------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `RedirectPathValidationPolicy`                  | `absolute_path_of`, `is_contained` on redirect targets                  | decision                                                                         |
| `AllowedCommandPolicy`                          | `is_contained` on parsed paths; hands it to parsers and `PathsFilter`   | decision                                                                         |
| `DefaultParser` / `StructuredParser`            | `absolute_path_of` on path candidates, `exists` for the filtering guess | `parse()` only                                                                   |
| `ProvidedParser`                                | `exists` on `parsers/<name>.py`; a missing script becomes command `""`  | construction (so an unknown bundled name silently denies every invocation later) |
| `PathsFilter`                                   | `absolute_path_of` on each `exactly` entry                              | construction                                                                     |
| `path_permission_decision_for` (Read/Grep/Glob) | resolution and matching of `allowedPaths`                               | decision                                                                         |

So the context is really a decision-time input. Only `ProvidedParser` and `PathsFilter` pull it into construction, and
both could defer it: resolve `exactly` in `matches()`, check the bundled script when parsing.

### Observed during exploration

### How filter/parser checking works today (measured 2026-09-25)

- `AllowedCommand.from_entry` (`lib/allowed_command.py:38-57`) stores `filters` and `commandParser` as the raw dicts the
  author wrote. Only `programGlob` is validated there, and it raises `ConfigError`.
- `Config.from_dict` additionally runs `Filter.try_from_definition` over every filter, only to collect uncompilable
  pattern Warnings (`lib/config.py:404-429`). It swallows every other `ConfigError`.
- At decision time, `AllowedCommandPolicy._entry_rejection_reason` (`lib/allowed_command_policy.py:169-198`) rebuilds
  the parser from its dict (`_build_parser`, which raises for an unknown type). It then walks the filter dicts in
  `_filter_passes`, which dispatches on the `type` string: `paths` → `PathsFilter`, `nestedCommand` → a parser
  capability check (raises) plus `NestedCommandFilter`, otherwise an `optionValue` capability check (raises) and then
  `Filter.try_from_definition`. That last call raises for an unknown type and degrades a bad regex to
  `UncompilableFilter`, which always fails. Every Filter is rebuilt on every evaluation.
- So a defect raises only when evaluation REACHES it: an earlier path check or filter that fails, or an earlier entry
  that vouches, hides it. The raised `ConfigError` is uncaught in every `bin/` entrypoint, so the hook exits 1 and
  Claude Code treats the command as having no verdict (fail-open). That is the open improvement `20260920-152953`
  (status planned, no approach yet).
- The knowledgebase (Load-Time Rejection) records the opaque storage as leaf `20260914-213153`'s design. One concrete
  constraint behind it: `StructuredParser.from_definition`, `ProvidedParser.from_definition` and
  `PathsFilter.from_definition` need a `PathResolutionContext`, which today is available only from
  `Config._path_resolution()`, not when an entry is constructed.

### Observed during exploration

- Out of scope: during this planning session, the `find-auto-allowed-command` agent was dispatched for an `ls` of a path
  outside the project. It classified `ArgumentPathOutsideAllowedPaths` as a categorical denial "functionally the same as
  sensitivePaths". The knowledgebase lists it as a NEAR-MISS reason. The agent also claimed a `Read` of that path would
  "very likely hit the same categorical denial". But `decision_for_path` never denies (match → allow, otherwise
  passthrough). So the agent is missing the same schema knowledge this skill would supply. It has only `tools: Read`, so
  it could in principle read a shipped reference file. That is a possible follow-up, not part of this improvement.

## Test Architecture

- Run: `cd tests && nix-shell --run pytest` (CLAUDE.md). TDD per the operator's global instructions (`tdd` skill): run
  the suite first, one test at a time.
- No database or filesystem where avoidable: value objects get an injected `PathResolutionContext` (existing test
  pattern). The describer is injected, so `described_problems` tests pass a fake describer returning fixed descriptions.
  Only the bundled-parser describe tests and the describer's own tests run real subprocesses
  (`tests/test_bundled_parsers.py` `run_parser` convention; `tests/fixtures/fake_parsers/` for contract-breach scripts).
- Fantasy callsites:
  - `entry = AllowedCommand.from_entry({"program": "x", "filters": [{"type": "nope"}]}, context, source="user")`, then
    `entry.problems()` names the unknown type and `user`, and the entry never vouches in `decision_for`.
  - `config.described_problems(FakeDescriber({"parsers/git.py": {"publishesNestedCommands": False, ...}}))` returns a
    Warning for a `nestedCommand` filter on the git parser.
  - `run_parser("git", {"describe": True})` returns a description whose named values match what the parser publishes.
- Re-adjudicate the 21 `pytest.raises(ConfigError)` cases: each becomes "entry never vouches + problem reported" (spec
  suite asserts at `result.reason` level plus the problem, per the knowledgebase's wrapper-spec gotcha).
- Drift test: parametrised over each code registry, asserting `skills/config/SKILL.md` names every member.

## Assumptions

- **add-allow-policy accepts a full JSON allowedCommands entry, not only a bare program name, but it can only APPEND to
  allowedCommands; it cannot edit or remove an entry, or touch
  blockedCommands/allowedPaths/additionalAllowedPathPrefixes/sensitive\*** — confirmed (lib/add_allow_write.py
  parse_entry (json.loads when the text looks like JSON) and apply_proposal (setdefault allowedCommands, append))
- **add-allow-policy is advertised to a session only in edge cases: SessionStart/SubagentStart render never names it
  except when NO config file exists at either scope (layer_presence.py:71); deny reasons point only at
  find-auto-allowed-command, naming add-allow-policy only after a grammar violation of add-allow-policy itself; the
  find-auto-allowed-command agent's terminal fallback names only bypass-policy. The only unconditional mention is
  audit-session-policy's human-facing footer.** — confirmed (rg add-allow-policy over lib/ agents/ hooks/ bin/render-\*:
  hits only reason_renderer.py grammar-violation clauses, layer_presence.py:71, session_audit.py:52;
  agents/find-auto-allowed-command.md:80 names only bypass-policy; this session's own SessionStart output contains no
  add-allow-policy mention)
- **No instruction reaching a session tells Claude to avoid permission prompts; the 'escalate only when nothing else
  works' obligation lives in the developer knowledgebase, not in any session-visible text** — confirmed (User and
  project CLAUDE.md, SessionStart render and the agent body contain no such rule; the phrase lives in
  docs/knowledgebase/command-policy-decision-model.md (Outcome Vocabulary), which is not injected)
- **add-allow-policy passes the entry through opaquely (json.loads, else bare string) in both the ask diff and the
  write, so it already supports every allowedCommands entry shape with no per-key knowledge; but it validates nothing -
  a malformed entry (unknown filter type, bad regex) is shown and written, and the PostToolUse lint hook (matcher
  Write|Edit) does not fire for a write performed via Bash** — confirmed (lib/escalation_policy.py:260-275 \_entry_diff
  and lib/add_allow_write.py parse_entry/apply_proposal pass the entry through; hooks/hooks.json PostToolUse matcher is
  exactly Write|Edit, and add-allow-policy writes from a Bash tool call)
- **Neither write path catches an entry the engine would reject: Config.from_dict raises only for program+programGlob
  conflicts and bad programGlob fields, and warns only on uncompilable patterns; unknown filter type, unknown
  commandParser type, optionValue without a value-consuming parser, and nestedCommand without a sub-command-publishing
  parser raise ConfigError only from decision_for, and only when a command for that program runs. The PostToolUse lint
  hook renders just Config.warnings(), so a direct Edit is no better validated than add-allow-policy.** — confirmed
  (lib/config.py:404-429 \_collect_allowed_command_filter_warnings deliberately ignores every other ConfigError;
  lib/allowed_command_policy.py:315-328, 404-419 raise at decision time; lib/hook_envelopes.py:50-57
  config_write_lint_response = config.warnings(); lib/allowed_command.py:38-124 from_entry checks)
- **Loading a proposed entry through Config.from_dict is enough to validate it before add-allow-policy asks** — refuted
  (from_dict raises only for program+programGlob and programGlob field defects, and only WARNS on an uncompilable
  pattern; unknown filter/parser type and the optionValue/nestedCommand parser-capability checks are raised lazily from
  decision_for (lib/config.py:404-429, lib/allowed_command_policy.py:315-419). The knowledgebase (Load-Time Rejection)
  records this laziness as deliberate: checks are policed against the invoked program's matching entries, not eagerly
  against the whole config.)
- **An external-parser metadata interface exists that tells the engine a script's capabilities (e.g. which options take
  values, whether it publishes nestedCommands)** — refuted (rg over parsers/, lib/command_parser.py,
  lib/external_parser_factory.py, docs/: no describe/capability protocol. A command/provided script receives only
  {"arguments": [...]} on stdin and returns options/positionals/subcommand/named/paths/nestedCommands.
  \_require_parser_declares_option_value skips any parser lacking consumes_value_for_option (external = cannot
  validate), and \_require_parser_can_publish_nested_commands accepts ANY command/provided parser, so e.g.
  provided:git + nestedCommand passes the check yet denies every invocation.)
- **PathResolutionContext is needed only when a parser parses or a filter matches, not when a definition is checked -
  except ProvidedParser (checks the bundled script exists at construction) and PathsFilter (resolves its exactly entries
  at construction)** — confirmed (lib/default_parser.py:58 and lib/structured_parser.py:113 use self.\_path_resolution
  only inside parse(); lib/provided_parser.py:38-40 \_resolve_command calls path_resolution.exists at **init**;
  lib/paths_filter.py:21-25 resolves in from_definition. Sole production producer: Config.\_path_resolution()
  (lib/config.py:381-389), built fresh per call from CLAUDE_PROJECT_DIR (fallback os.getcwd) with real os predicates;
  PathResolutionContext.for_process() is used only by tests.)
- **One bundled parser subprocess costs roughly 30 ms, so describing ~10 provided entries at every config load would add
  ~300 ms to every hook invocation** — confirmed (2026-09-25, date +%s%N around 'echo {...} | python3 parsers/git.py' =
  27.0 ms and parsers/sed.py = 30.8 ms on the operator's machine (warm cache))

## Design Decisions

### Config write path

- **Chosen:** `add-allow-policy` for new `allowedCommands` entries. A direct Edit of `command-policy.json` for
  everything else, linted by the PostToolUse hook.
- **Rationale:** Operator agreed to the recommendation ("Sounds good"). Added consequence in their words: "It makes
  keeping add-allow-policy up to date with anything an allowedCommands entry can do mandatory."
- **Rejected alternatives:** (a) direct edits only, like the old `shfmt-permissions:config`, which loses the
  diff-and-intent prompt. (b) Extending `add-allow-policy` to every config key, which is consistent but a larger change.
- **Date:** 2026-09-25

### Entry defects become values, not exceptions

- **Chosen:** `AllowedCommand.from_entry` builds Filter/parser value objects. A defect yields an `InvalidFilter` / an
  invalid-parser stand-in that always fails closed. `AllowedCommand.problems()` is public and is called by
  `add-allow-policy` and the lint hook.
- **Rationale:** Operator's own design ("from_dict creating a bunch of Filter::from_dict() … make validate a public
  function and actively call it"), refined in discussion to returning an `InvalidFilter` rather than storing errors on a
  valid Filter. Cross-object checks live on `AllowedCommand` because a Filter cannot see the parser.
- **Rejected alternatives:** validating via `Config.from_dict` alone (misses most defects, see Assumptions). A separate
  eager validator beside the lazy checks (two places know the rules). Storing errors inside a Filter and refusing in
  `match()`.
- **Date:** 2026-09-25

### PathResolutionContext bound at creation

- **Chosen:** entries and their parsers/filters receive the context when they are built (`from_entry(entry, context)`,
  with `Config.from_dict` defaulting to the project context).
- **Rationale:** Operator: "passing in a context that only one specific filter needs into the function seems like the
  wrong paradigm though. That should happen at creation. So even if its a little more work on the tests I tend to want
  it in the 'factory'."
- **Rejected alternatives:** method injection (`parse(arguments, context)`, `matches(parsed, context)`), which is fewer
  test changes but threads an argument through every call for the benefit of a few consumers.
- **Date:** 2026-09-25

### Parser describe protocol added in this improvement

- **Chosen:** external (`command`) and bundled (`provided`) parser scripts gain a describe call that reports their
  static capabilities (e.g. whether they publish `nestedCommands`, which options take values). `problems()` uses it
  instead of skipping external parsers or accepting any of them for `nestedCommand`.
- **Rationale:** Operator: "Sounds good to add that now". No external script parsers are in use anywhere today (the
  operator keeps all of theirs bundled), so the interface can be designed freely. It exists for users without repository
  access.
- **Rejected alternatives:** leaving external-parser capability checks dynamic or skipped.
- **Date:** 2026-09-25

### No split

- **Chosen:** the skill, the advertising fix, the value-object refactor and the describe protocol stay in one
  improvement.
- **Rationale:** Operator: "I don't think we should split. I find these things hard to actually see as their own
  sub-steps."
- **Rejected alternatives:** a separate refactor improvement absorbing `20260920-152953`, with this one depending on it.
- **Date:** 2026-09-25

### Describe runs only on reporting paths, with the describer passed in

- **Chosen:** capability problems are computed by `config.described_problems(describer)`, called only by the reporting
  entrypoints. The describer is an entrypoint-local edge object with its own memo, never stored on a value object.
- **Rationale:** Operator: "300ms per hook is a bit much. Let's go with your design", plus their copy-on-write concern
  ("a process wide cache would mean sharing a non-copy-on-write object between the copy-on-write ones"). Then: "right
  lets try passing it in then."
- **Rejected alternatives:** describing at entry construction (~300 ms on every hook call, measured). Storing the
  describer or its cache on `Config`/`AllowedCommand` (a mutable object shared across copy-on-write copies).
- **Date:** 2026-09-25

### Describe contract breach is a problem

- **Chosen:** a script that does not answer `{"describe": true}` correctly is reported as a problem.
- **Rationale:** Operator: "treat is a breach of contract and thus a problem please. As said there are no live scripts
  to protect by keeping the behaviour".
- **Rejected alternatives:** treating silence as "capability unknown" (no problem, runtime behaviour unchanged).
- **Date:** 2026-09-25

### One SKILL.md, user-invocable

- **Chosen:** a single `skills/config/SKILL.md` with `user-invocable: true`, and a description led by user phrasings.
- **Rationale:** Operator: "The problem with reference files is that they trigger a read outside the current repository
  warning". On invocability: "I don't see any harm in allowing it", with plain-language requests as their primary route
  (the old description matched poorly).
- **Rejected alternatives:** `SKILL.md` plus on-demand reference files. `user-invocable: false` like the old skill.
- **Date:** 2026-09-25

## Success Criteria

- `/command-policy:config` exists. A session asked "please change my command policy config" or "stop asking me for X"
  loads it without the plugin being named (checked manually in a fresh session after install).
- The skill names every filter type, top-level key, entry key, parser type, bundled parser and `add-allow-policy`
  violation code in the code, enforced by the drift test. It contains none of the dropped legacy keys.
- Every session's injected rules name `add-allow-policy` with its canonical form and point at `command-policy:config`.
  The `find-auto-allowed-command` agent's fallback names both `bypass-policy` and `add-allow-policy` with when to use
  each.
- No `ConfigError` escapes `decision_for` for any `allowedCommands` defect, and a malformed `programGlob` no longer
  breaks loading: the defective entry never vouches and its problem appears in `explain()`/SessionStart/lint output,
  naming its layer.
- `add-allow-policy` refuses (deny with a rendered Reason) a proposal whose entry has any static or described problem,
  before asking.
- Every bundled parser answers `{"describe": true}`, and a test checks its description against what it publishes. A
  script that breaches the describe contract is reported as a problem.
- The Bash and path decision hooks never run a describe subprocess.
- Full suite green. Version bumped in both `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` in the
  same commit as the content change.

## Implementation TODO

- [ ] Update status to in-progress
- [ ] Add a project constructor to `PathResolutionContext`. `Config.from_dict(cfg, source, path_resolution=None)` stores
      the context. `config_loader` passes one context to all layers. `_policies`/`decision_for_path` reuse it.
- [ ] `Filter.from_definition` covers all ten filter types (taking over `paths`/`nestedCommand` from `_filter_passes`)
      and returns `InvalidFilter(problems)` for every defect, generalising `UncompilableFilter`.
- [ ] Parser factory moved out of `AllowedCommandPolicy._build_parser`, returning an invalid-parser stand-in. Structured
      retired keys and unknown provided names become problems.
- [ ] `AllowedCommand.from_entry(entry, context, source)` builds filters and parser, carries `source`, and exposes
      static `problems()` (incl. `programGlob` and the pure-parser `optionValue`/`nestedCommand` checks).
      `__eq__`/`__hash__`/`explain` stay on the raw definitions.
- [ ] `AllowedCommandPolicy` operates on built objects. Remove `_build_parser`, `_require_*`, the string dispatch.
- [ ] `Config.from_dict` reports static problems as layered Warnings, replacing
      `_collect_allowed_command_filter_warnings`.
- [ ] Re-adjudicate the 21 `pytest.raises(ConfigError)` tests to "never vouches + problem reported".
- [ ] Milestone: full suite green with no decision-time `ConfigError` left for `allowedCommands` defects.
- [ ] Describe protocol: describer edge object (stdin `{"describe": true}`, memo per instance, contract validation) next
      to `ExternalParserFactory`.
- [ ] All 17 bundled parsers answer describe (`publishesNestedCommands`, named values, `optionsWithValues`). A test
      checks each description against actual output. Add contract-breach fixtures.
- [ ] `Config.described_problems(describer)` + `with_additional_warnings`. Wire into
      `command-policy-render-session-start`, `command-policy-render-subagent-start`, `explain-policy`,
      `command-policy-lint-config-on-write`.
- [ ] `add-allow-policy`: the ask path refuses a proposal with static or described problems via a new Reason / violation
      code rendered by `reason_renderer`. The write side re-checks.
- [ ] Milestone: full suite green; decision hooks verified to construct no describer.
- [ ] `find-auto-allowed-command` agent fallback names `bypass-policy` and `add-allow-policy` with when to use each.
- [ ] `Config.explain()` static line naming `add-allow-policy` (canonical form) and `command-policy:config`.
- [ ] Write `skills/config/SKILL.md` per the outline (single file, `user-invocable: true`, phrase-led description).
- [ ] Skill drift test over all code registries.
- [ ] `skills/migrate-config/SKILL.md`: "Where to write" points at `command-policy:config`.
- [ ] Update the knowledgebase (Load-Time Rejection, opaque storage superseded, describe protocol, advertising,
      glossary). Note the absorbed parts in `improvement-20260920-152953`'s file.
- [ ] Bump the version in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
- [ ] Run the full suite: `cd tests && nix-shell --run pytest`.
- [ ] Update status to completed