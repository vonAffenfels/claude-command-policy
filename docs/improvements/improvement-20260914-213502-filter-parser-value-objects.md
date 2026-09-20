# Improvement 20260914-213502: Convert Filter and Parser Families to Value Objects

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-14
- Updated: 2026-09-17
- Trunk: 20260914-195111
- Kind: decomposed
- Plan finished: 2026-09-16T16:04:08+02:00
- Impl started: 2026-09-17T18:23:05+02:00
- Impl finished: 2026-09-17T18:37:45+02:00
- Depends on: 20260914-213153

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md` — this leaf
is part of that trunk's subject. The trunk's `## Shared Context (For Leaves)` carries the copy-on-write idiom, the
policy pipeline and its Pass ordering, the naming decisions, the corrected code coordinates, the test-suite split and
the environment constraints. Do not re-derive any of it.

## Context / Why This Exists

**Origin / trigger:** Leaf 3 of trunk 20260914-195111's re-cut nine-leaf stream. SHAPE scoped it because a filter is
CONSTRUCTED FROM a config definition (once AllowedCommand.fromDefinition exists via leaf 20260914-213153), and because
'not just Policy, also Filter, Parser' becoming copy-on-write value objects only pays off once the sub-values are
themselves copy-on-write.

**Consumer(s) of the output:** The policy pipeline (leaf 20260914-213652) calls Filter.matches()/Parser output as part
of AllowedCommand's matching; Config's explain()/warnings() (leaf 20260914-213153) consumes each filter's own
explain()/derive_alternative() for the deny+hint mechanism.

**Adjacent systems already covering part of the need:** Config value object (leaf 20260914-213153, interface settled,
not yet implemented) supplies AllowedCommand's normalized filter/parser definitions this leaf constructs FROM. The
authored decision specification (leaf 20260914-213049, currently mid-implementation) pins the behavioural assertions
this leaf's filters must satisfy.

## This Improvement's Objective

Convert the Filter and Parser families — 13 classes selected by two factory functions — into copy-on-write value
objects, and dissolve the shared-primitive coupling in `ParsedResult`.

This is leaf 3 of trunk `20260914-195111` (the Statement value-object full rewrite). It depends on leaf
`20260914-213153` (the config model), because a filter is CONSTRUCTED FROM a config definition — once
`AllowedCommand.fromDefinition(...)` exists, a filter stops reading a raw dict slice and starts being built from a value
object. It is the direct application of the trunk's decision that 'not just Policy, also Filter, Parser' become
copy-on-write value objects, because structural sharing only pays off when the sub-values are themselves copy-on-write.

WHAT EXISTS TODAY (measured, 2026-09-14, re-verified 2026-09-16):

Nine filter classes, each reading its own raw config slice in its constructor: `ParameterRegexFilter` (`:460`),
`MatchFullParameterFilter` (`:485`), `PositionalArgRegexFilter` (`:507`), `ArgumentAtIndexFilter` (`:532`),
`PositionalArgAtIndexFilter` (`:562`), `NamedValueFilter` (`:592`), `OptionValueFilter` (`:628`), `OptionPresentFilter`
(`:665`), `PathsFilter` (`:686`). They are selected by `create_filter` and its `filter_classes` dict (`:762-783`). Their
shared config vocabulary: `type`, `action` (default `block`), `pattern` (default `""`), `index` (default `0`), `name`,
`option`, `exactly` (PathsFilter only), `timeout_ms`, `fallback`.

Four parser classes: `DefaultParser` (`:89`, heuristic — dash-prefixed is an option, else positional, with path
detection via `_detect_paths` at `:122`), `StructuredParser` (`:159`, driven by
`options_with_arguments`/`pathOptions`/`pathPositionals` config), `CommandParser` (`:359`, runs an external script via
subprocess with timeout and fallback), `ProvidedParser` (`:791`, resolves a bundled `parsers/<name>.py` and delegates to
`CommandParser`). Selected by `create_parser` (`:738`). They produce `ParsedResult` (`:58`) with its `ParsedOption`
(`:45`) and `ParsedPositional` (`:52`).

A KNOWN DEFECT TO DISSOLVE, NOT PRESERVE: `ParsedResult.paths` is a shared bag with two unrelated consumers —
`_check_path_validation` (`:1886`) and `PathsFilter` (`:686`) — so adding anything to `paths` silently changes filter
matching. Two distinct concepts are sharing one primitive list. The trunk expects this to become two named concepts
rather than one list two things happen to read.

Also note `_check_command_allowed`'s `call_exprs` parameter is PLURAL with exactly ONE caller passing a single-element
list (`analyze-bash-command.py:1971`) — vestigial generality that should not be carried into the new model. It belongs
to the pipeline leaf `20260914-213652`, not to this one.

TEST SURFACE (migration, not safety net): all nine filter classes and all four parser classes are directly instantiated
by tests — `TestParameterRegexFilter` (`:2026`) through `TestOptionPresentFilter` (`:2269`), `TestPathsFilter`
(`:4283`), `TestDefaultParser` (`:1485`), `TestStructuredParser` (`:1601`), `TestCommandParser` (`:1739`),
`TestProvidedParser` (`:1918`), `TestProvidedParserNixShell` (`:3130`), `TestProvidedParserTimeout` (`:3275`),
`TestDefaultParserPathDetection` (`:3724`), `TestStructuredParserPathDetection` (`:3782`). The factories are called
directly at `:2311` and `:2354`, and `ParsedResult`/`ParsedOption`/`ParsedPositional` are constructed field-by-field in
`TestParsedResult` (`:1386-1481`). `tests/test_new_parsers.py` (985 lines) also follows this leaf. These tests break by
design; the behaviour they pin must be re-expressed against the new model.

The open questions SHAPE recorded here (whether the Filter family collapses, what replaces the factories, what
`ParsedResult` becomes, whether the external parsers can be value objects, how filters feed `explain()`) are now SETTLED
— see `## Proposed Approach` and `## Design Decisions`.

## Proposed Approach

Filter family: introduce `Filter { matcher: Matcher, action: Action }` — Action is a small value object owning only the
block/required inversion (today duplicated identically across 8 of the 9 filter classes); Matcher stays a family of ~8
concrete classes, one per today's projection+comparison pair (ParameterRegexMatcher, MatchFullParameterMatcher,
PositionalArgRegexMatcher, ArgumentAtIndexMatcher, PositionalArgAtIndexMatcher, NamedValueMatcher, OptionValueMatcher,
OptionPresentMatcher), each answering only 'what did this raw match do' with no knowledge of block/required.
`Filter.matches(parsed)` = `action.applies_to(matcher.match(parsed))`. `PathsFilter` stays entirely OUTSIDE this
composition — its 'exactly'-match-over-a-list semantics has no block/required action at all, so it remains its own value
object.

CRITICAL: the Matcher result is THREE-STATE, not boolean — see Implementation Notes. Four of the eight filters
short-circuit to 'filter fails' before the action is applied, which is NOT the same as matched=False and would invert
under a naive boolean composition.

Parser family: `DefaultParser`/`StructuredParser` stay fully pure (no IO, construct via named constructor,
parse(arguments) is a pure function). `CommandParser`/`ProvidedParser` become pure config-holding value objects (command
path or resolved bundled-script path, timeout_ms) with a pure `interpret(raw_output) -> ParsedResult` method; they never
call subprocess themselves. A separate edge-level `ExternalParserFactory` (real subprocess.run inside,
dependency-injected — never constructed ad-hoc inside a value object) is what the pipeline calls to obtain raw_output,
which it then hands to `interpret()`. This leaf defines the value objects and the factory's shape/contract; wiring the
factory into the actual policy-pipeline call site is leaf 20260914-213652's job (stated explicitly in this leaf's
Interface section at finalize).

Bundled parser scripts (15 files ~85KB: git.py, npm.py, awk.py, etc.) stay external/subprocess-executed via the
ExternalParserFactory — NOT ported to in-process value objects in this leaf. Verified (grep across trunk + all four
sibling leaf files) that no prior leaf/trunk decision requires in-process porting; it would be substantial scope growth
beyond what SHAPE measured (13 classes + 2 factories). They move to a new top-level `packages/command-policy/parsers/`
directory — a FIFTH top-level directory the scaffold leaf did not settle, added because these scripts are neither
library code nor entrypoints and are explicitly meant as findable reference examples end users copy to build their own.

Construction: `create_filter`/`create_parser` factory-dict functions are replaced by named constructors on the value
objects themselves (e.g. `Filter.from_definition(dict)`, and a `from_definition` equivalent per Parser subtype for pure
config construction) — consistent with the trunk's 'smart value objects construct themselves from their sources via
named constructors' rule. The `ExternalParserFactory` is a separate edge-level collaborator, not a replacement factory
function for construction.

ParsedResult.paths: split into TWO independently-named fields on the parse result (exact names to be settled during
implementation/Refactor — candidates: paths_for_validation feeding path-prefix validation, paths_for_filtering feeding
PathsFilter), both currently populated from the same detection heuristic as today, so a future divergence in detection
logic is a visible one-line change rather than a silent cross-effect between two unrelated consumers.

Fallback semantics: CommandParser/ProvidedParser's `fallback` field (today: deny|ask|legacy) becomes a CONSTANT —
deny+hint, always — when an external parse fails. No longer configurable; the `fallback` key should be dropped from the
parser config schema entirely. Consistent with the trunk's already-settled pattern that 'the config can no longer
express be lenient' (banner section B, the four dying decision knobs). Flag this for leaf 20260915-011123 (migration
skill) at finalize, since it is one more knob the migration skill must know has died.

Invalid regex: today `except re.error: matched = False` means a typo'd pattern with a `block` action makes the filter
PASS — a silent fail-open on malformed config. Instead, `Filter.from_definition()` validates the pattern compiles, and
an uncompilable pattern surfaces through `Config.warnings()` (leaf 20260914-213153's structured, layer-carrying warnings
— never pre-formatted strings). This is a deliberate behaviour change, not a port.

Ambient filesystem/cwd: `DefaultParser._detect_paths` calls `os.path.exists()` (a real filesystem read) and
`os.path.abspath()` (reads ambient cwd), and `PathsFilter` normalizes its `exactly` patterns with `os.path.abspath()`
too. Both receive an injected path-resolution context (a fixed cwd plus an exists-predicate) instead of reading ambient
process state — the same DI shape as ExternalParserFactory, and what makes these value objects exercisable without a
real filesystem or a pinned cwd.

Each Filter/Matcher instance and PathsFilter gets an explain() and derive_alternative() method mirroring today's free
functions \_describe_filter/\_derive_filter_alternative (:2159-2209), now operating on the filter's own typed fields
instead of a raw dict, so Config's explain()/warnings() and the deny+hint mechanism can call filter.explain() directly.

NOT every value object in this leaf needs copy-on-write `with_*` mutation methods: Filter/Matcher/Action/Parser are
constructed once from a config definition and never incrementally modified afterward (unlike Statement, which mutates
during recursive decomposition) — plain immutable value objects with named constructors are sufficient; do not force
unnecessary `with_*` methods onto them.

## Affected Components

**Files:**

- `packages/shfmt-permissions/scripts/analyze-bash-command.py:45` (ParsedOption)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:52` (ParsedPositional)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:58` (ParsedResult)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:89` (DefaultParser, incl. \_detect_paths :122-156)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:159` (StructuredParser)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:359` (CommandParser)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:791` (ProvidedParser)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:460-731` (nine Filter classes)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:738-788` (create_parser/create_filter factories)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:2159-2209` (\_describe_filter/\_derive_filter_alternative
  — hint machinery to port onto Filter/Matcher)
- `packages/shfmt-permissions/scripts/parsers/` (15 bundled parser scripts — move to packages/command-policy/parsers/)
- `packages/command-policy/lib/` (new modules: proposed filter.py, matcher.py, action.py, parser.py, parsed_result.py,
  external_parser_factory.py, path_resolution.py — exact boundaries are an implementation-time call)
- `packages/command-policy/parsers/` (NEW top-level directory for the bundled reference parser scripts)
- `packages/command-policy/tests/` (new test files for Filter/Matcher/Action/Parser/ParsedResult)

**Classes/Functions:**

- Filter (new)
- Matcher (new family, ~8 concrete classes)
- Action (new)
- PathsFilter (ported, stays separate)
- DefaultParser
- StructuredParser
- CommandParser
- ProvidedParser
- ExternalParserFactory (new, edge-level)
- path-resolution context (new, edge-level)
- ParsedResult
- ParsedOption
- ParsedPositional
- create_filter (removed)
- create_parser (removed)

**Modules:**

- shfmt-permissions (source)
- command-policy (target)

## Implementation Notes

**Module layout.** `lib/` is a flat sys.path directory — `import filter`, never `import lib.filter`. There is no
`scripts/` directory and no leaf may add one. The bundled parser scripts go in a new top-level
`packages/command-policy/parsers/`, NOT in `lib/` and NOT in `bin/`: they are neither library code nor entrypoints, and
are meant to be findable reference examples end users copy to build their own. This is a fifth top-level directory the
scaffold leaf (20260915-010936) did not settle — call it out in the Interface hand-back.

**THE THREE-STATE MATCHER SUBTLETY — the single easiest thing to silently break in this leaf.** Four of the eight
filters short-circuit to 'filter fails' BEFORE the action is applied, and that is NOT the same as `matched = False`:

- `ArgumentAtIndexFilter` (:547-548) and `PositionalArgAtIndexFilter` (:577-578) — index out of bounds -> `return False`
- `NamedValueFilter` (:606-607) — named value absent -> `return False`
- `OptionValueFilter` (:648-649) — option not present -> `return False`

With a `block` action and an out-of-bounds index, today returns False (filter FAILS, invocation not allowed). A naive
`action.applies_to(matcher.match(parsed))` with `matched=False` computes `not False` = True (filter PASSES, invocation
ALLOWED) — the exact opposite outcome, and a fail-open one. The Matcher contract must therefore express THREE outcomes —
matched / not-matched / target-absent — where target-absent short-circuits to 'filter fails' regardless of action.
Preserve today's fail-closed behaviour here; it is consistent with the new deny-by-default model. Every one of these
four needs an explicit test for the absent case under BOTH actions.

**Invalid regex is a deliberate behaviour change.** Today `except re.error: matched = False` is a fail-open on malformed
config. The new named constructor validates the pattern compiles and surfaces an uncompilable pattern as a structured
`Config.warnings()` entry (leaf 20260914-213153's contract: structured values carrying layer provenance, never
pre-formatted strings). Do not port the swallow.

**Implemented shape of the above (2026-09-17):** `Filter.from_definition` raises `config.ConfigError` (reused, per that
module's own docstring, which already anticipated this leaf using it) when a pattern fails `re.compile`, and sets
`.filter_type` / `.pattern` attributes on the exception instance so a catcher can build a `Warning` without re-parsing a
message string. `Filter.from_definition(definition)` stays single-argument/single-return per the Interface contract — it
does NOT itself append to `Config.warnings()`, since `Config` does not yet construct `Filter` objects from
`AllowedCommand.filters` (that construction site is leaf 20260914-213652's pipeline). This leaf's own test suite
(`test_filter.py`) verifies the raise and its carried facts; the pipeline leaf is responsible for catching `ConfigError`
per filter definition and turning it into a `Warning` entry via `Config.warnings()`'s existing structured-value pattern.

**ExternalParserFactory failure modes.** All of: non-zero exit, `subprocess.TimeoutExpired`, `json.JSONDecodeError`,
`OSError` (missing or non-executable script), and an empty/absent command path. Every one collapses to the constant
deny+hint outcome — there is no configurable `fallback` any more. The factory is the ONLY place `subprocess.run` appears
in this leaf's output.

**PathsFilter edge cases to preserve.** Empty `parsed.paths` -> passes (nothing to validate). Non-empty paths with an
empty `exactly` list -> fails (no paths allowed). Both are load-bearing and currently untested-by-name.

**StructuredParser config key casing (2026-09-17).** Today's `StructuredParser` mixes `options_with_arguments` /
`double_dash_stops` (snake_case) with `pathOptions` / `pathPositionals` (camelCase) - an inconsistency, not a deliberate
API. The new `StructuredParser.from_definition` reads all four as camelCase
(`optionsWithArguments`/`doubleDashStops`/`pathOptions`/`pathPositionals`), matching every other config key in this
package (`allowedCommands`, `hasNoPathParameters`, `commandParser`, ...). Flag for the migration skill (20260915-011123)
alongside the `fallback` key's death.

**Bundled parser scripts: COPIED, not moved (2026-09-17).** The Proposed Approach and Design Decisions above say the 15
scripts "move to" `packages/command-policy/parsers/`, but a literal `git mv` would delete
`packages/shfmt-permissions/scripts/parsers/`, which `shfmt-permissions`'s OWN live `ProvidedParser`
(`analyze-bash-command.py:817`, `SCRIPT_DIR / "parsers" / f"{name}.py"`) still resolves against - breaking the trunk's
own overriding "CUTOVER: additive, deprecate only" invariant (Shared Context section A.2: "`command-policy` is built
ALONGSIDE an untouched `shfmt-permissions`... nothing forces its removal"). Resolved by copying the 15 files to the new
`packages/command-policy/parsers/` and leaving `packages/shfmt-permissions/scripts/parsers/` byte-for-byte untouched -
verified `packages/shfmt-permissions/tests/test_analyze_bash_command.py -k ProvidedParser` (24 tests) still passes
against the old plugin's unmodified tree. Flag at INTEGRATE/deprecation time (leaf 20260914-213825): the two copies will
drift if either bundled script is edited in only one place going forward.

**Not this leaf's problem.** `_check_command_allowed`'s vestigial plural `call_exprs` parameter (one caller,
single-element list, `analyze-bash-command.py:1971`) belongs to the pipeline leaf 20260914-213652, not here — do not
carry it into the new model, but do not chase it either.

**Test migration surface.** The test classes listed in this file's TEST SURFACE section break by design; their
ASSERTIONS are the behaviour to re-express against the new model, their call shape is not. `tests/test_new_parsers.py`
(985 lines) follows this leaf too.

**Deferred, deliberately.** Porting the 15 bundled parser scripts to in-process value objects (eliminating their
subprocess calls entirely) was considered and explicitly scoped OUT — see Design Decisions. It remains a plausible
future improvement; nothing in this leaf's design blocks it, since the ExternalParserFactory seam is exactly where an
in-process implementation would substitute.

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/conftest.py` — lib/ sys.path bootstrap enabling direct `import filter` /
  `import parser` in unit tests; run_entrypoint(name, args, stdin, env) subprocess fixture for bin/ entrypoints;
  cwd_pinned_inside_project which pins both cwd and CLAUDE_PROJECT_DIR
- `packages/shfmt-permissions/tests/test_analyze_bash_command.py:2026-2269, :4283` — the nine filter classes' existing
  test CASES — reference material for the behaviour to re-express, not an importable helper
- `packages/shfmt-permissions/tests/test_analyze_bash_command.py:1485-1918, :3130-3275, :3724-3782` — the four parser
  classes' existing test CASES including nix-shell and timeout coverage — reference material, not an importable helper
- `packages/shfmt-permissions/tests/test_analyze_bash_command.py:1386-1481` — TestParsedResult — field-by-field
  construction of ParsedResult/ParsedOption/ParsedPositional; shows exactly the verbosity the new builder should remove
- `packages/shfmt-permissions/tests/test_analyze_bash_command.py:3038-3055` — fake_shfmt_on_path — the existing pattern
  for faking an external executable on PATH; the ExternalParserFactory seam should make this unnecessary for parser
  tests, so treat it as the thing being REPLACED rather than reused

**New helpers to create:**

- parse result builder — every filter test needs a parse result with specific options/positionals/named/paths; today's
  tests construct these field-by-field (see TestParsedResult), which is the duplication the Refactor phase should absorb
- fake ExternalParserFactory — returns canned raw output or a chosen failure mode (non-zero exit, timeout, malformed
  JSON, missing script) so CommandParser/ProvidedParser tests never spawn a process
- fake path-resolution context — supplies a fixed cwd and a controlled exists-predicate so path-detection and
  PathsFilter tests assert against declared state instead of the real filesystem
- filter definition builder — produces {type, pattern, action, index, option, name} definition dicts so filter tests
  exercise the real named constructor (including its new pattern validation) rather than bypassing it

**Fantasy callsites (test-facing API sketches):**

- `Filter.from_definition({"type": "parameterRegex", "pattern": "--force", "action": "block"}).matches(parsed)`
- `CommandParser.from_definition({"command": "/x/p.py", "timeout_ms": 1000}).interpret(raw_output)`
- `ExternalParserFactory(...).raw_output_for(parser, arguments)  # the one place subprocess.run lives`

**Testability-driven production decisions:**

- ExternalParserFactory injected rather than subprocess.run called inline — makes CommandParser/ProvidedParser
  exercisable without spawning a process
- Path-resolution context injected rather than os.path.exists/abspath read ambiently — makes DefaultParser and
  PathsFilter exercisable without a real filesystem or a pinned cwd
- Matcher's three-state result made explicit in the type rather than encoded as an early `return False` — makes the
  target-absent case directly assertable under both actions, instead of being invisible until a behaviour regression

## Assumptions

- **No prior leaf or trunk decision requires the bundled parsers/\*.py scripts to be reimplemented as in-process value
  objects** — confirmed (grep -rniE 'bundled parser|ProvidedParser|parsers/<name>|in-process parser' across the trunk
  file and all four sibling leaf files (213153, 213321, 010936, and this file) returned exactly one hit — a bare
  class-name listing in the trunk's Affected Components — and no decision of any kind.)
- **Four of the eight action-bearing filters short-circuit to 'filter fails' before the action is applied, so a boolean
  Matcher+Action composition would invert their outcome** — confirmed (Read of analyze-bash-command.py:
  ArgumentAtIndexFilter :547-548, PositionalArgAtIndexFilter :577-578, NamedValueFilter :606-607, OptionValueFilter
  :648-649 each `return False` on an absent/out-of-bounds target BEFORE reaching the `if self._action == 'block'`
  branch. The other four (ParameterRegex, MatchFullParameter, PositionalArgRegex, OptionPresent) have no such
  short-circuit.)
- **An uncompilable regex pattern currently makes a block-action filter PASS (a fail-open on malformed config)** —
  confirmed (Read of analyze-bash-command.py :473-479 and the identical shape in
  PositionalArgRegexFilter/ArgumentAtIndexFilter/PositionalArgAtIndexFilter/NamedValueFilter/OptionValueFilter:
  `except re.error: matched = False`, then `if self._action == 'block': return not matched` — i.e. returns True (filter
  passes) for an invalid pattern.)
- **DefaultParser and PathsFilter read ambient filesystem/cwd state** — confirmed (Read of analyze-bash-command.py:
  DefaultParser.\_detect_paths :143-154 uses os.path.normpath, os.path.expanduser, os.path.abspath and os.path.exists;
  PathsFilter.matches :722-724 normalizes its `exactly` patterns with os.path.abspath. Corroborated by
  packages/command-policy/tests/conftest.py's cwd_pinned_inside_project fixture (lines 56-86), which exists to pin cwd +
  CLAUDE_PROJECT_DIR against ambient-cwd false positives.)
- **Leaf 20260914-213153's Config/AllowedCommand contract is settled and available to build against, even though its
  code is not yet implemented** — confirmed (Its ## Interface section is written and its Leaf Stream entry in the trunk
  reads 'status: done'. Its own file Status is 'ready-to-implement' (planned, not yet built) —
  packages/command-policy/lib/config.py currently holds only leaf 20260914-213049's RED-seam stub (Config.from_dict
  returns cls(cfg); decision_for raises NotImplementedError). So the CONTRACT is authoritative here; the code is not yet
  there to import.)

## Design Decisions

### Filter family shape

- **Chosen:** Filter { matcher: Matcher, action: Action } composition; Action is the one shared concept (block/required
  inversion), Matcher stays a family of ~8 concrete classes rather than fully collapsing; PathsFilter stays entirely
  separate (no action concept applies to it)
- **Rationale:** User: "They differ in WHAT they extract and HOW they compare - that sounds to me like the whole
  identity of a filter. The action to take after matching is a distinctive shared principle. I've used Filter { Matcher,
  Action } in the past and I'd also be fine to move that shared concept into a Matcher. That leaves Filter { Matcher,
  Action } as a pretty thin layer but not like that's a bad idea."
- **Rejected alternatives:** Full collapse into one generic Filter class parameterized by a Projection+Matcher+Action
  triple (no separate Matcher family); leaving all 9 filter classes structurally unchanged with no restructuring at all
- **Date:** 2026-09-16

### Parser / external-IO boundary

- **Chosen:** CommandParser/ProvidedParser become pure config value objects with a pure interpret(raw_output) method; a
  separate edge-level ExternalParserFactory (dependency-injected via Config/Statement, never constructed ad-hoc inside a
  value object) performs the actual subprocess call; wiring the factory into the pipeline call site belongs to leaf
  20260914-213652
- **Rationale:** User proposed the DI shape directly: "Sounds like we need an ExternalParserFactory passed to the Config
  or the top level Statement that passed it down the chain." Matches this repo's CLAUDE.md rule that business rules must
  be exercisable without IO — rules receive their data, the edge fetches it.
- **Rejected alternatives:** Keep CommandParser/ProvidedParser 'smart' — subprocess call stays inline inside parse(),
  same shape as today
- **Date:** 2026-09-16

### Bundled parser scripts (parsers/\*.py) scope

- **Chosen:** Stay external/subprocess-executed via ExternalParserFactory; NOT ported to in-process value objects in
  this leaf
- **Rationale:** Verified by grep across the trunk file and all sibling leaf files: no prior decision anywhere requires
  in-process porting. User confirmed after seeing this: 'Not decided anywhere — scope this leaf to the shell only.'
  Porting all 15 bundled scripts (~85KB) would be substantial scope growth beyond what SHAPE measured for this leaf (13
  classes + 2 factories).
- **Rejected alternatives:** Port all 15 bundled parsers/\*.py scripts (git.py, npm.py, awk.py, grep.py, etc.) to
  in-process Python value objects as part of this leaf, eliminating their subprocess calls entirely
- **Date:** 2026-09-16

### Home for the bundled parser scripts in the new package

- **Chosen:** A new top-level packages/command-policy/parsers/ directory (a fifth top-level dir the scaffold leaf did
  not settle)
- **Rationale:** User: "Since they _are_ neither library code nor entrypoints lets move them into their own directory
  parsers/ inside the plugin directory. They are supposed to be reference points for end users to build their own and
  that makes them easily findable too." The reference-example audience is the deciding factor, not just the lib/bin
  taxonomy.
- **Rejected alternatives:** A lib/parsers/ subdirectory (they are real code, and nothing imports them so flat-import is
  unaffected); or bin/ with a command-policy- prefix following the scaffold's internal-entrypoint convention (would
  append 15 names to the Bash PATH)
- **Date:** 2026-09-16

### ParsedResult.paths split

- **Chosen:** Two independently-named fields on the parse result (one feeding path-prefix validation, one feeding
  PathsFilter matching), both populated from the same detection heuristic today
- **Rationale:** rationale not captured
- **Rejected alternatives:** Single shared paths field/value object feeding both consumers as today, just carried as a
  value-object field instead of a dataclass field (defect survives unchanged)
- **Date:** 2026-09-16

### Filter/Parser construction mechanism

- **Chosen:** Named constructors on the value objects themselves (Filter.from_definition(dict), and an equivalent per
  Parser subtype for pure config construction) replace create_filter/create_parser; ExternalParserFactory is a separate
  edge-level collaborator, not a construction-replacing factory
- **Rationale:** Consistent with the trunk's 'smart value objects construct themselves from their sources via named
  constructors' rule. User confirmed for Filter directly and deferred to this reasoning for Parser after asking for the
  planner's take.
- **Rejected alternatives:** Standalone create_filter(dict)/create_parser(dict) module-level factory functions, updated
  to return the new value objects instead of the old classes
- **Date:** 2026-09-16

### Parse-failure fallback semantics

- **Chosen:** Fail closed — deny+hint, constant, no longer configurable; the fallback key leaves the parser config
  schema
- **Rationale:** rationale not captured (user selected the Recommended option). Consistent with the trunk's
  already-settled pattern that the config can no longer express 'be lenient' (banner section B) — this reduces fallback
  to the same shape as the four dying decision knobs.
- **Rejected alternatives:** Fail open (passthrough), mirroring the trunk's separate RESOLVED decision for whole-command
  shfmt parse failure; or keep fallback configurable between deny and passthrough only
- **Date:** 2026-09-16

### Uncompilable filter pattern handling

- **Chosen:** Reject at construction — Filter.from_definition validates the pattern compiles, and an uncompilable
  pattern surfaces as a structured Config.warnings() entry
- **Rationale:** rationale not captured (user selected the Recommended option). The finding that drove the question:
  today's `except re.error: matched = False` combined with a block action makes a typo'd regex silently MORE permissive,
  which is a fail-open that contradicts the new deny-by-default model.
- **Rejected alternatives:** Fail closed at match time (keep swallowing re.error but treat an uncompilable pattern as
  'filter fails' regardless of action, no construction-time validation); or preserve today's fail-open behaviour
  unchanged as a pure port
- **Date:** 2026-09-16

### Ambient filesystem and cwd access inside Parser/Filter

- **Chosen:** Inject a path-resolution context (fixed cwd plus an exists-predicate) into path detection and PathsFilter
  normalization, instead of reading ambient process state
- **Rationale:** rationale not captured (user selected the Recommended option). The finding that drove the question:
  DefaultParser.\_detect_paths calls os.path.exists() and os.path.abspath(), and PathsFilter normalizes 'exactly' with
  os.path.abspath() — so a 'pure' parser and a filter both depend on ambient process state, which is why
  command-policy's conftest already needs a cwd-pinning fixture.
- **Rejected alternatives:** Keep the ambient os.path.exists/abspath reads and rely on the existing
  cwd_pinned_inside_project test fixture; or note the gap and defer the decision to the pipeline leaf
- **Date:** 2026-09-16

## Success Criteria

- [x] Filter is a single value object composed of a Matcher and an Action; the block/required inversion exists in
      exactly ONE place, not duplicated across eight classes
- [x] The Matcher contract expresses three outcomes (matched / not-matched / target-absent); all four target-absent
      cases — argument index out of bounds, positional index out of bounds, named value missing, option missing — fail
      closed under BOTH block and required actions, each covered by an explicit test
- [x] PathsFilter exists as its own value object outside the Filter{Matcher,Action} composition, with its
      empty-paths-passes and empty-exactly-fails edge cases both tested by name
- [x] create_filter and create_parser no longer exist; every filter and parser is constructed through a named
      constructor on its own value object
- [x] DefaultParser and StructuredParser are exercisable in tests with no subprocess and no real filesystem access
- [x] No subprocess call exists inside any Parser value object; all external execution lives in ExternalParserFactory,
      which tests substitute with a fake
- [x] Every external-parser failure mode (non-zero exit, timeout, malformed JSON, missing or non-executable script,
      empty command path) yields deny+hint, and no configurable fallback key remains in the parser config schema
- [x] The parse result carries two independently-named path concepts, so changing the detection heuristic for one is a
      visible one-line change rather than a silent cross-effect on the other
- [x] An uncompilable filter pattern is rejected at construction and surfaces as a structured Config warning carrying
      its layer provenance; it can no longer make a command more permissive — PARTIAL BY DESIGN:
      `Filter.from_definition` raises `config.ConfigError` with `.filter_type`/`.pattern` attributes attached (verified
      in test_filter.py); the actual append into `Config.warnings()` cannot be demonstrated inside this leaf because
      `Config` does not yet construct `Filter` objects from `AllowedCommand.filters` (leaf 20260914-213153 stores them
      opaquely, by that leaf's own design). Wiring the catch-and-warn is leaf 20260914-213652's job — see Interface for
      the exact hand-off contract.
- [x] No os.path.exists or os.path.abspath call remains inside a Filter or Parser value object; path detection and
      normalization receive an injected cwd and exists-predicate
- [x] Each Matcher, Filter and PathsFilter exposes explain() and derive_alternative() reproducing at least today's
      \_describe_filter/\_derive_filter_alternative output, derived from typed fields rather than a raw dict
- [x] The 15 bundled parser scripts live in packages/command-policy/parsers/ and are resolved from there by
      ProvidedParser
- [x] The full command-policy suite passes: cd packages/command-policy/tests && nix-shell --run "pytest -v" — passes in
      the sense that governs this leaf: 284 passed, and the 80 failures are unchanged, pre-existing, and confined to
      test_permission_decisions.py's `Config.decision_for` NotImplementedError (leaf 20260914-213652's job, documented
      as RED-by-design in leaf 20260914-213153's own Interface section)

## Implementation TODO

- [x] Update status to in-progress
- [x] RED: write failing tests for Action — block inverts, required passes through — as the smallest independent piece
- [x] GREEN: implement the Action value object
- [x] RED: write failing tests for the three-state Matcher contract, covering all four target-absent cases under BOTH
      block and required actions
- [x] GREEN: implement the Matcher contract plus ParameterRegexMatcher
- [x] GREEN: implement the remaining seven Matchers (MatchFullParameter, PositionalArgRegex, ArgumentAtIndex,
      PositionalArgAtIndex, NamedValue, OptionValue, OptionPresent)
- [x] RED/GREEN: Filter value object composing Matcher + Action, constructed via Filter.from_definition()
- [x] MILESTONE: Filter.from_definition rejects an uncompilable pattern and surfaces it as a structured Config warning
      instead of silently matching nothing
- [x] RED/GREEN: port PathsFilter as its own value object outside the Filter{Matcher,Action} composition, with
      empty-paths and empty-exactly cases tested by name
- [x] REFACTOR: extract the parse result builder and filter definition builder once test-setup duplication appears
      (reviewed: inline `ParsedResult(options=[ParsedOption(...)])`/`{"type": ..., "pattern": ...}` construction stayed
      one-line and self-documenting everywhere it appears — test_matcher.py's local `parsed()` helper is the one place
      duplication was real enough to name; no shared conftest.py builder was warranted)
- [x] RED/GREEN: parse result value objects (ParsedResult/ParsedOption/ParsedPositional successors) carrying two
      independently-named path concepts instead of one shared paths bag
- [x] RED/GREEN: path-resolution context — inject cwd and an exists-predicate; remove every os.path.exists/abspath call
      from DefaultParser and PathsFilter (PathsFilter done; DefaultParser/StructuredParser follow next)
- [x] RED/GREEN: DefaultParser as a pure value object with a named constructor
- [x] RED/GREEN: StructuredParser as a pure value object with a named constructor
- [x] RED/GREEN: ExternalParserFactory — every failure mode (non-zero exit, timeout, malformed JSON, missing or
      non-executable script, empty command) collapses to deny+hint
- [x] RED/GREEN: CommandParser as pure config plus interpret(raw_output), containing no subprocess call
- [x] Move the 15 bundled parser scripts to packages/command-policy/parsers/ (copied, not moved — see Implementation
      Notes: a literal move would break the still-live shfmt-permissions plugin)
- [x] RED/GREEN: ProvidedParser resolving packages/command-policy/parsers/<name>.py and delegating through
      ExternalParserFactory (ProvidedParser delegates interpret() to an internal CommandParser; the pipeline leaf
      supplies ExternalParserFactory for the actual subprocess call, same as for a bare CommandParser)
- [x] MILESTONE: create_filter and create_parser are deleted; every construction goes through a named constructor (never
      existed in command-policy — grep confirms zero definitions, only prose references to what they replace)
- [x] RED/GREEN: explain() and derive_alternative() on each Matcher, Filter and PathsFilter, reproducing today's
      \_describe_filter/\_derive_filter_alternative output from typed fields
- [x] MILESTONE: the fallback key is gone from the parser config schema — deny+hint is a constant
- [x] REFACTOR: review lib/ module boundaries; delete lib/placeholder.py and repoint tests/test_scaffold.py if it is
      still present (neither exists — already clean from an earlier leaf; confirmed no unused imports across all 12 new
      lib/ modules)
- [x] Run the full suite: cd packages/command-policy/tests && nix-shell --run "pytest -v"
- [x] Re-read the `## Interface` section below and update it if implementation diverged from the planned contract
- [x] Update status to completed

## Interface

**What this leaf produces:** the Filter and Parser value-object model in `packages/command-policy/lib/` — `Filter`
composed of a `Matcher` (family of 8, in `matcher.py`) and an `Action`, `PathsFilter` as its own separate filter kind
(`paths_filter.py` — a dedicated module, not folded into `filter.py`, since it shares no base class with `Filter`), the
four Parser value objects (one module each: `default_parser.py`, `structured_parser.py`, `command_parser.py`,
`provided_parser.py` — split finer than the plan's single proposed `parser.py`, matching this package's one-concept-
per-file convention), the edge-level `ExternalParserFactory`, and the injected `PathResolutionContext`
(`path_resolution.py`) — plus the 15 bundled reference parser scripts COPIED (not moved — see below) into a new
top-level `packages/command-policy/parsers/`.

**Contract for downstream leaves / integrate:**

- `Filter.from_definition(definition)` is the only construction route; it consumes `AllowedCommand`'s already-normalized
  filter definitions (leaf `20260914-213153` owns bare-string-vs-object normalisation — this leaf never re-implements an
  `isinstance` check on an entry). `create_filter`/`create_parser` never existed in `command-policy` at all.
- `Filter.matches(parse_result) -> bool` is the single entry point the policy pipeline calls. Internally it is
  `action.applies_to(matcher.match(...))`, where the matcher result is THREE-STATE (`MatchOutcome.MATCHED` /
  `NOT_MATCHED` / `TARGET_ABSENT`, in `match_outcome.py`) and target-absent fails closed regardless of action. Do not
  re-derive this as a boolean composition — it inverts four filters' outcomes.
- **`Filter.from_definition` raises `config.ConfigError` on an uncompilable pattern** (with `.filter_type`/`.pattern`
  attributes set on the exception instance) — it does NOT itself append to `Config.warnings()`. `Config` does not yet
  construct `Filter` objects from `AllowedCommand.filters` (leaf `20260914-213153` stores them opaquely by design), so
  there is no construction site inside `Config` for this leaf to hook a warning into. **Leaf `20260914-213652` must
  catch `ConfigError` at the site where it calls `Filter.from_definition` per filter entry and turn it into a `Warning`
  via `Config`'s existing structured-value pattern** (see `warning_value.py`'s classmethod shape, e.g.
  `Warning.invalid_knob_value`) — this is the one piece of this leaf's own uncompilable-pattern success criterion that
  could not be verified end-to-end inside this leaf's own test suite; see that criterion's note above.
- `PathsFilter` is NOT a `Filter{Matcher, Action}`. It has no action concept; treat it as its own filter kind with its
  own `matches()`. `PathsFilter.from_definition(definition, path_resolution)` takes the path-resolution context
  explicitly (unlike `Filter.from_definition`, which takes only `definition`) because it normalizes its `exactly`
  entries ONCE, at construction — `matches()` itself performs no filesystem or cwd read.
- `DefaultParser`/`StructuredParser`/`ProvidedParser` are all constructed as
  `SomeParser.from_definition(definition, path_resolution)` — the path-resolution context is a constructor argument, not
  a `parse()`/`interpret()` argument, so `parse(arguments)` and `interpret(raw_output)` stay single-argument.
  `CommandParser.from_definition(definition)` takes no path-resolution context (it has no path-detection heuristic of
  its own to inject into). `DefaultParser`/ `StructuredParser` are pure: `parse(arguments)` needs nothing but the
  path-resolution context injected at construction. `CommandParser`/`ProvidedParser` are pure config plus
  `interpret(raw_output)`; they NEVER perform IO — `ProvidedParser` also resolves whether its bundled script exists via
  the injected context's `.exists(path)`, not a direct filesystem call, so no Parser value object anywhere calls
  `os.path.exists`/`abspath` directly.
- **Leaf `20260914-213652` must inject `ExternalParserFactory`.** This leaf defines its shape and failure semantics but
  deliberately does NOT wire it into the pipeline call site. The pipeline obtains `raw_output` from
  `factory.raw_output_for(parser, arguments)` (returns `None` on any failure, a parsed dict on success), then calls
  `parser.interpret(raw_output)` only when it is not `None`. Every factory failure mode (non-zero exit, timeout,
  malformed JSON, missing or non-executable script, empty command) collapses to `None` -> the pipeline's constant
  deny+hint outcome.
- **Leaf `20260914-213652` must also construct one `PathResolutionContext` per analysis run** (`for_process()` in
  production) **and pass it to every `DefaultParser`/`StructuredParser`/`ProvidedParser`/`PathsFilter` construction
  call** — there is no other seam left for ambient cwd/filesystem state to enter this leaf's value objects.
- `explain()` and `derive_alternative()` are instance methods on each `Matcher`, `Filter` and `PathsFilter`.
  `Filter.explain()`/`derive_alternative()` delegate to `self._matcher.explain(self._action)` /
  `derive_alternative(self._action)` — the Matcher owns the type+target wording, Action owns only the kind
  ("block"/"required"), and each Matcher subclass composes them (all seven pattern-bearing matchers share the base
  `Matcher.explain`/`derive_alternative`; `OptionPresentMatcher` overrides both, matching today's special-cased
  wording). `Config.explain()` and deny-reason construction call them; they do not re-derive descriptions from raw
  dicts.
- Config schema changes this leaf makes: the `fallback` key is GONE from `commandParser`/`provided` parser definitions
  (deny+hint is a constant); an uncompilable filter `pattern` now raises at construction (see above) instead of silently
  matching nothing; and `StructuredParser`'s four config keys are ALL camelCase now
  (`optionsWithArguments`/`doubleDashStops`/`pathOptions`/`pathPositionals` — today's engine mixes snake_case and
  camelCase across these four).

**New dependency edges discovered:** none that change the Leaf Stream order. This leaf's `- Depends on: 20260914-213153`
(settled at SHAPE) is unchanged and remains correct.

**Follow-ups for integrate:**

1. **A FIFTH top-level directory now exists in the package.** `packages/command-policy/parsers/` holds the 15 bundled
   reference parser scripts. The scaffold leaf (`20260915-010936`) settled only `lib/`, `bin/`, `skills/`, `tests/` and
   stated "There is NO `scripts/` directory, and no leaf may add one". `parsers/` is an addition to that vocabulary
   rather than a violation of it — reconcile the scaffold's documented layout at INTEGRATE.
2. **The bundled scripts were COPIED, not moved, and now exist in two places.** A literal move (as the plan's prose
   said) would delete `packages/shfmt-permissions/scripts/parsers/`, which `shfmt-permissions`'s own still-live
   `ProvidedParser` resolves against — breaking the trunk's own "additive, deprecate only" cutover invariant. The two
   copies (`packages/shfmt-permissions/scripts/parsers/*.py` and `packages/command-policy/parsers/*.py`) are identical
   as of this leaf and will DRIFT if either is edited in only one place going forward. Leaf `20260914-213825` (the
   deprecation leaf) should decide whether to delete the old copy once `shfmt-permissions` is actually retired, or
   document the duplication as a permanent consequence of the additive cutover.
3. **Leaf `20260915-011123` (migration skill) gains two more dead-knob-shaped facts, not one.** `commandParser`'s
   `fallback` (today `deny|ask|legacy`) ceases to exist — NOT in the trunk's banner-section-B table of four dying
   decision knobs, so the migration skill will miss it unless told explicitly. Separately, `StructuredParser`'s
   snake_case config keys (`options_with_arguments`, `double_dash_stops`) are renamed to camelCase — a copied-across
   config using the old keys will silently stop consuming its option/double-dash configuration rather than erroring,
   since `dict.get(..., default)` never raises on an unrecognised key.
4. **Leaf `20260915-010959` (deny+hint reasons) consumes instance methods, not free functions.** It may still be planned
   against `_describe_filter`/`_derive_filter_alternative`; those become
   `Filter.explain()`/`Filter.derive_alternative()` here (and `Matcher.explain(action)`/`derive_alternative(action)` one
   level down, for a caller that already has the two parts separately).
5. **Porting the 15 bundled parsers in-process was deferred, not rejected.** The `ExternalParserFactory` seam is exactly
   where an in-process implementation would substitute; a future improvement can do it without touching this leaf's
   value objects.
6. **A behaviour change worth stating in the deprecation/migration notes:** an uncompilable regex pattern that today
   silently makes a command MORE permissive now raises `ConfigError` at construction (destined to become a `Config`
   warning once leaf `20260914-213652` wires the catch — see the contract note above).
7. **The uncompilable-pattern -> `Config.warnings()` wiring is NOT done.** This leaf validated that the letter of its
   own success criterion ("rejected at construction... surfaces as a structured Config warning") could only be
   half-verified here, because `Config` does not yet build `Filter` objects at all. Leaf `20260914-213652` owns both
   halves: catching `Filter.from_definition`'s `ConfigError` per entry, AND actually constructing
   `Filter`/`Matcher`/`Action`/Parser objects from `AllowedCommand`/`Config` in the first place — this leaf only proved
   the value objects work in isolation.
