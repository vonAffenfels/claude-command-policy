# Improvement 20260918-185726: Fix Command-Policy Symlink Path Resolution

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-18
- Updated: 2026-09-18
- Plan started: 2026-09-18T18:56:57+02:00
- Plan finished: 2026-09-18T19:29:35+02:00
- Impl started: 2026-09-18T20:10:24+02:00
- Impl finished: 2026-09-18T20:18:58+02:00
- Depends on: 20260914-213825

## This Improvement's Objective

Fix a confirmed false-ALLOW in `packages/command-policy`: `PathResolutionContext.absolute_path_of`
(`packages/command-policy/lib/path_resolution.py`) normalises paths with `os.path.normpath` only, a purely lexical
operation that never touches the filesystem, so it cannot detect that a path component is a symlink pointing outside the
project. Reproduced live: with a project-local symlink `escape -> ../outside`, `echo hi > escape/pwned.txt` is
auto-approved (ALLOW) by command-policy, while the literal traversal `echo hi > ../outside/pwned.txt` is correctly
denied (RedirectOutsideAllowedPaths), and the deprecated old engine (`packages/shfmt-permissions`, which calls
`os.path.realpath`) correctly passes-through (not auto-approved) on the same symlinked command. Root cause is
pre-existing (`absolute_path_of` landed in leaf `20260914-213502`, the redirect policy consuming it in leaf
`20260914-213652`); leaf `20260914-213825` did not introduce it but increased exposure by wiring up the PreToolUse
entrypoints. command-policy is not currently enabled in user settings (only shfmt-permissions is), so no user is exposed
today, but leaf `20260914-213825` also marked shfmt-permissions deprecated in favor of command-policy, so the
recommended successor engine carries this live gap. This improvement adds symlink resolution to the shared
path-resolution seam so every consumer (redirect validation, allowedCommands argument-path validation, PathsFilter, and
the Read/Grep/Glob `decision_for_path`) is fixed uniformly, pins the behaviour with a real-symlink fixture mirroring the
old engine's `TestPathValidation::test_symlink_resolved_before_validation`, and decides whether the shfmt-permissions
deprecation's switch-now guidance needs adjusting until this lands.

## Context / Why This Exists

**Origin / trigger:** Found by an independent review of leaf `20260914-213825`, which deliberately deferred it to its
own improvement rather than absorbing it into that leaf's own scope.

**Consumer(s) of the output:** None yet / write-only. `command-policy` is not enabled in user settings today (only
`shfmt-permissions` is), so this closes a gap before anyone is exposed, rather than fixing a live incident.

**Adjacent systems already covering part of the need:** (none identified) — `packages/shfmt-permissions` (the deprecated
old engine) already does `realpath`-based resolution correctly, but as prior art/reference to follow, not as a system
that currently covers this need for `command-policy` users.

## Proposed Approach

The entire fix lives in `PathResolutionContext` (`packages/command-policy/lib/path_resolution.py`), which is the SOLE
factory-produced value object every path-boundary consumer shares — confirmed by tracing every call site of
`absolute_path_of`/`is_contained` back to `Config._path_resolution()` (`config.py:354`), the single construction point
used by `RedirectPathValidationPolicy`, `AllowedCommandPolicy`, `DefaultParser`/`StructuredParser`, `PathsFilter`, and
`decision_for_path`. No other file needs to change to reach every surface.

1. **Add an injected symlink-resolution seam**, mirroring the existing `is_directory_predicate` shape:
   - `PathResolutionContext.__init__` gains `realpath_predicate=None`, stored as `self._realpath`, defaulting to the
     identity function `lambda path: path` (a no-op — consistent with keeping unit tests decoupled from the real
     filesystem unless a test explicitly injects a fake).
   - `for_process()` passes `realpath_predicate=os.path.realpath` (non-strict — see the dangling/loop/nonexistent-leaf
     assumption below for why no extra handling is needed).
   - **`self._cwd` is realpath'd ONCE at construction** (`self._cwd = realpath_predicate(cwd)`), rather than left raw.
     This serves double duty: it is both the join-base for relative values in `absolute_path_of` AND the primary
     boundary compared against in `is_contained` — realpath'ing it once at the source keeps both uses consistent with no
     separate resolution step at each call site.
2. **`absolute_path_of` resolves symlinks on its result.** Split the existing normpath logic into a private
   `_lexical_absolute_path_of` (unchanged: `~`-expansion / absolute / cwd-relative-join branches, still lexical only),
   then `absolute_path_of(value) = self._realpath(self._lexical_absolute_path_of(value))`. This is the ONLY place
   symlink resolution is applied to a candidate path, and every consumer (redirect targets, `allowedCommands` argument
   paths via `default_parser.py`/`structured_parser.py`, `PathsFilter`'s `exactly` entries, `decision_for_path`'s
   target/rule paths) already routes through this one method, so all of them pick up the fix with no per-consumer
   change.
3. **`is_contained` resolves the OTHER side too — the boundary, not just the candidate** (Design Decision: symmetry).
   Today `is_contained`'s helper `_is_within(path, prefix)` applies only `os.path.normpath(prefix)` to each
   `additionalAllowedPathPrefixes` entry — no `~`-expansion, no cwd-relative join, no realpath. Route each
   `allowed_prefix` through `self.absolute_path_of(prefix)` instead of the bespoke `os.path.normpath` call:
   - This gives prefixes the SAME `~`-expansion / relative-join / realpath treatment the candidate already gets (closing
     the folded-in `~`-expansion gap and, as an incidental but consistent side effect, also making a genuinely relative
     — non-`~`, non-`/` — prefix entry resolve against the project root instead of comparing an absolute candidate
     against a bare relative string, which could never match under the old `_is_within`).
   - `self._cwd` (already realpath'd at construction — step 1) is used directly as the first candidate; the
     `allowed_prefixes` tuple is mapped through `self.absolute_path_of` before the same `_is_within` string comparison
     runs. `_is_within` itself no longer needs its own `os.path.normpath(prefix)` call, since its input is now always an
     already-fully-resolved absolute path.
4. **No special-casing for a not-yet-existing redirect target, a dangling symlink, a symlink loop, or a self-referencing
   symlink.** `os.path.realpath` in its default (non-strict) mode already handles every one of these gracefully with no
   exception — verified live (see the Assumptions section). This directly resolves the task's concern that "realpath can
   raise OSError": that is only true of `strict=True`, which this design does not use.
5. **TOCTOU is real and is documented, not engineered away** (see Implementation Notes) — resolution happens once, at
   decision time; the command executes afterward. This fix closes the STATIC symlink-escape gap (a symlink already in
   place when the hook runs); it does not and cannot make the check atomic with execution.
6. **`sensitivePaths` is deliberately NOT covered by this fix, and the residual gap is stated rather than implied.**
   `SensitivePathsPolicy` (`lib/sensitive_paths_policy.py`, Pass 0) matches by plain SUBSTRING CONTAINMENT against the
   command's own RAW TEXT — it is never handed a `PathResolutionContext` and resolves nothing, by design (its module
   docstring and the decision-model knowledgebase article both pin the over-matching substring behaviour as intentional,
   with an explicit "do not narrow it without re-adjudicating" warning). The seam fix therefore cannot and does not
   reach it. What that leaves:
   - **A symlink resolving OUTSIDE the project is still caught** after this fix — not by `sensitivePaths`, but by the
     now-symlink-aware containment checks (redirect validation and argument-path validation), which deny it for being
     out of bounds regardless of whether Pass 0 recognised it.
   - **The genuine residual gap is a symlink pointing at a sensitive path that lives INSIDE the allowed boundary** —
     e.g. `sensitivePaths: [".env"]` with an in-project symlink `link -> .env`, where `cat link` evades the raw-text
     scan and passes containment because the resolved path really is inside the project. This is NOT fixed here.
   - **Out of scope deliberately**, because closing it means changing Pass 0's matching character (raw-text denylist →
     resolved-path matching), which the knowledgebase explicitly requires re-adjudicating on its own terms rather than
     as a side effect of a containment fix. Worth its own follow-up improvement; recorded here so it is not lost.

## Affected Components

**Files:**

- `packages/command-policy/lib/path_resolution.py` — the only production file that changes. Add `realpath_predicate` to
  `PathResolutionContext.__init__` and `for_process()`; split `absolute_path_of` into a private lexical helper plus a
  realpath step; realpath `self._cwd` once at construction; route `is_contained`'s prefix handling through
  `self.absolute_path_of` instead of `_is_within`'s bespoke `os.path.normpath`.
- `packages/command-policy/tests/test_permission_decisions.py` — new decision-specification cases (real symlink fixture)
  pinning the fix at the outcome level, per the task's explicit preference for the decision-spec suite.
- `packages/command-policy/tests/test_path_resolution.py` — ALREADY EXISTS with a clean fake-predicate unit-test style
  (`test_is_contained_admits_a_path_under_the_root`,
  `test_a_relative_value_resolves_against_the_injected_cwd_not_the_real_process_cwd`, etc. — twelve tests today, none
  covering `realpath_predicate` since that parameter doesn't exist yet). Extend it, don't replace its style: add cases
  for the injected `realpath_predicate` seam (fake predicate, no real FS), the `~`-expansion-on-prefixes fix (fake
  predicate), and the construction-time `_cwd` resolution — plus the one real-tmp_path symlink case mirroring the
  decision-spec case at the unit level.
- `packages/command-policy/lib/config.py` — NOT in the original Affected Components list, but required:
  `_path_resolution()` (`config.py:354`) constructs `PathResolutionContext` directly with its own
  `exists_predicate`/`is_directory_predicate` rather than delegating to `for_process()`, so it needed its own
  `realpath_predicate=os.path.realpath` added — confirmed necessary live (the decision-spec symlink cases stayed RED,
  `allow` instead of `deny`, until this one-line addition landed). One line changed.
- `packages/command-policy/tests/test_config.py` — NOT in the original Affected Components list. Added one symlink case
  for `decision_for_path` (Read/Grep/Glob) proving it independently reaches the fix through the same
  `Config._path_resolution()` factory, per the Success Criterion requiring proof rather than inference for that surface.
- `packages/command-policy/lib/redirect_path_validation_policy.py` — the "ONE UNRELATED DEFECT" item from the task: line
  9's docstring still named `additionalAllowedPrefixes`; corrected to `additionalAllowedPathPrefixes` (the leaf
  20260915-011123 rename). Genuinely adjacent (same redirect-path-validation module this improvement already edits
  transitively via the shared seam), so folded in rather than left for a third hand-forward. One line changed, no
  behaviour change.

**Classes/Functions:**

- `PathResolutionContext.__init__` / `for_process()` (new `realpath_predicate` parameter)
- `PathResolutionContext.absolute_path_of` (split into lexical helper + realpath step)
- `PathResolutionContext.is_contained` / the module-level `_is_within` helper (prefix resolution routed through
  `absolute_path_of`)

## Implementation Notes

**Testing Strategy:** TDD (per the user's global CLAUDE.md, which mandates the `tdd` skill for all test-writing work —
no project-specific override found in this repo's own `CLAUDE.md`/`ARCHITECTURE.md`).

**TOCTOU — stated plainly, not implied as atomic.** Path resolution happens once, at hook decision time
(`Config.decision_for`/`decision_for_path`, called from the PreToolUse hook before Claude Code executes the tool). The
actual command runs afterward, as a separate step. Nothing in this fix — or in the engine generally — makes the
containment check atomic with execution: a symlink created, swapped, or removed in the window between the decision and
the command actually running is NOT caught by this or any check the engine performs. This fix closes the STATIC gap (a
symlink already in place, unchanged, at decision time) reported in the task; it does not claim to close a
time-of-check-to-time-of-use race, and no reasonable static analysis of a command string could.

**Why a real-symlink fixture is an explicit, reasoned exception to this suite's general filesystem-avoidance
discipline.** `path_resolution.py`'s module docstring and the wider codebase deliberately push filesystem access behind
injected predicates so policies and filters stay unit-testable without a real FS. This improvement's fixture is the one
deliberate exception: the THING UNDER TEST is filesystem behaviour itself — whether `os.path.realpath` (the injected
default for `for_process()`) actually resolves a real symlink the way the fix assumes. A fake `realpath_predicate`
covers every other case (loop/dangling/self-reference semantics are pinned via a fake predicate returning
attacker-controlled values, exercising `is_contained`'s logic in isolation); only the "does the real default predicate
actually do this" claim needs a real `tmp_path` symlink, mirroring the old engine's own
`TestPathValidation::test_symlink_resolved_before_validation`
(`packages/shfmt-permissions/tests/test_analyze_bash_command.py:3928`) and this suite's own existing precedent of using
real `tmp_path` fixtures for path/prefix cases (e.g. `test_a_path_under_an_additional_allowed_prefix_is_permitted`,
`cwd_pinned_inside_project` in `conftest.py`) — this suite already accepts real-tmp_path path tests for boundary/prefix
cases; a real symlink is the same category of exception, just for symlink resolution specifically.

**Reproduction to pin, from the task report** (must resolve `deny` after the fix, matching the old engine's
passthrough-not-auto-approved and the literal-traversal case's existing `deny`):

```
project/
  escape -> ../outside      (symlink, created inside the temp project dir)
config: {"allowedCommands": ["cat"]}   (or "echo" — any allow-listed program with a redirect)
command: echo hi > escape/pwned.txt
before fix: allow   (the reported false-ALLOW)
after fix:  deny (RedirectOutsideAllowedPaths)
```

Add the mirror case for `allowedCommands` argument-path validation (not just redirects) — e.g. `cat escape/passwd`
against an entry with path validation enabled — since the fix is at the shared seam, not the redirect policy alone, and
a test should pin that breadth directly rather than relying on inference from the redirect case.

**What does NOT need a symlink fixture:** the `~`-expansion-on-prefixes fix and the "no special-casing needed for
dangling/loop/self-reference" claims are pinned with a FAKE `realpath_predicate` (e.g. one that maps a declared set of
paths to declared resolved values, or that raises to prove the engine never calls it unnecessarily) — no real filesystem
needed for those, consistent with the suite's general discipline.

## Test Architecture

**Existing helpers to reuse:**

- `test_path_resolution.py`'s own style: direct `PathResolutionContext(...)` construction per test, no factory/builder —
  twelve existing tests already establish this idiom; new tests should match it rather than introducing a builder.
- `test_permission_decisions.py`'s `assert_decision(command, config, expected_decision)` (returns the full result for
  further `assert_reason_includes`/`assert_primary_reason` inspection) and `conftest.py`'s `cwd_pinned_inside_project`
  fixture (real `tmp_path` + pinned `CLAUDE_PROJECT_DIR`/cwd) — both used as-is for the decision-spec-level symlink
  case, no new fixture needed at that layer.

**Fantasy callsites (what the tests want to write):**

1. `PathResolutionContext(cwd=tmp_path_str, realpath_predicate=os.path.realpath).absolute_path_of("escape/pwned.txt")`
   resolving to the real symlink target — the unit-level real-FS case.
2. `PathResolutionContext(cwd="/project", realpath_predicate=lambda p: FAKE_RESOLUTIONS.get(p, p)).is_contained(...)` —
   the fake-predicate style for the `~`-expansion-on-prefixes and dangling/loop-shaped cases, no real FS.
3. `assert_decision("echo hi > escape/pwned.txt", {"allowedCommands": ["echo"]}, "deny")` inside
   `cwd_pinned_inside_project()` with a real symlink created via `tmp_path`-level `Path.symlink_to` — the decision-spec
   case mirroring the old engine's `test_symlink_resolved_before_validation`.

**New helpers to create:** none. All three fantasy callsites are directly expressible with what already exists
(`PathResolutionContext`'s own constructor, `assert_decision`, `cwd_pinned_inside_project`) — no new test helper,
factory, or builder is needed.

**Testability-driven production-architecture decisions:** none beyond the `realpath_predicate` injection point itself
(Proposed Approach step 1), which follows the established `is_directory_predicate`/`exists_predicate` shape exactly — no
new abstraction is being introduced for testability's sake beyond continuing that existing pattern.

## Assumptions

- **`os.path.realpath` (non-strict, the default) does not raise for a non-existent leaf under a real parent directory**
  — confirmed (ran `os.path.realpath(os.path.join(realdir, "doesnotexist.txt"))` in a live probe; returned the
  lexically-joined path with no exception)
- **`os.path.realpath` (non-strict) does not raise `OSError` on a two-node symlink loop** — confirmed (created
  `a -> b -> a` in a live probe; `os.path.realpath(a)` returned a stable path, no exception)
- **`os.path.realpath` (non-strict) does not raise on a self-referencing symlink (`a -> a`)** — confirmed (live probe;
  returned the lexical path unchanged, no exception, including with a further child component appended)
- **`os.path.realpath` (non-strict) resolves a dangling symlink to its (nonexistent) target with no exception, both bare
  and with a further child path component appended** — confirmed (live probe against a symlink pointing at
  `/nonexistent/target/xyz`)
- **A project-local symlink to an external directory, joined with a not-yet-existing leaf filename, correctly resolves
  to the external absolute path** (the exact shape of the reported false-ALLOW: `escape -> ../outside` then
  `escape/pwned.txt`) — confirmed (live probe reproduced the resolution `outside/pwned.txt` from the symlinked join,
  matching what the fix needs `is_contained` to reject)
- **Every path-boundary consumer in `packages/command-policy` (redirect validation, `allowedCommands` argument-path
  validation, `PathsFilter`, `decision_for_path`) reaches `PathResolutionContext.absolute_path_of`/`is_contained`
  through the single `Config._path_resolution()` factory** — confirmed (grepped every call site of `absolute_path_of`/
  `is_contained`/`PathResolutionContext(` across `lib/`; all trace back to `config.py:354`'s `_path_resolution()`,
  called from `RedirectPathValidationPolicy`, `AllowedCommandPolicy`, `DefaultParser`/`StructuredParser` construction,
  and `decision_for_path`)
- **`additionalAllowedPathPrefixes` entries currently receive no `~`-expansion in `is_contained`/`_is_within`** —
  confirmed (read `_is_within`: only `os.path.normpath(prefix)`, no `_expand_home`-equivalent call; confirmed no
  existing test in `test_permission_decisions.py` exercises a `~`-prefixed `additionalAllowedPathPrefixes` entry)

## Design Decisions

### Symlink-resolution symmetry between candidate and boundary paths

- **Chosen:** Realpath BOTH sides of every containment check — the candidate path (`absolute_path_of`'s output) AND the
  boundary paths (`PathResolutionContext._cwd`, i.e. the project root, plus every `additionalAllowedPathPrefixes`
  entry). Mirrors the old engine, which realpath'd its prefixes at `_get_allowed_path_prefixes()` construction time as
  well as the candidate at `_path_within_prefixes()`.
- **Rationale:** rationale not captured (resolving only the candidate risks false denials when the project root or a
  configured prefix itself sits behind a symlink — e.g. macOS's `/tmp` -> `/private/tmp` — since the realpath'd
  candidate would then fail to prefix-match the un-resolved boundary).
- **Rejected alternatives:** Realpath the candidate only, leaving `_cwd`/`allowed_prefixes` as lexically-normalized
  strings.
- **Date:** 2026-09-18

### Whether to fold in the adjacent `~`-expansion gap in `is_contained`/`_is_within`

- **Chosen:** Fold it in as part of this improvement. `additionalAllowedPathPrefixes` entries currently receive no `~`
  expansion in `is_contained`/`_is_within` (only `os.path.normpath`), unlike `absolute_path_of`'s target-side handling,
  which does expand `~`. A configured prefix like `~/.config` therefore never matches anything today. This is a
  DIFFERENT root cause (missing tilde-expansion, not missing symlink-resolution) but lives in the exact same
  `is_contained`/`_is_within` code this improvement is already touching for the symlink fix, and is currently untested
  either way.
- **Rationale:** rationale not captured (same function is already being edited for the symlink fix; the touch is small).
- **Rejected alternatives:** Record as an `## Observed during exploration` item and leave it for a separate future
  improvement.
- **Date:** 2026-09-18

### Whether this improvement should also adjust shfmt-permissions' deprecation "switch now" guidance

- **Chosen:** Leave it entirely to the trunk's INTEGRATE session. Leaf `20260914-213825`'s own `## Interface` section
  already names "verify and, if confirmed, fix the symlink-escape gap" as a follow-up owned by INTEGRATE, which also
  owns reconciling whether the deprecation guidance should hold off "switch now" messaging until security gaps close.
  This improvement fixes the code, adds the pinning tests, and records the assumption; it does not touch
  `docs/knowledgebase/command-policy-decision-model.md`'s deprecation language or the plugin.json/marketplace.json
  descriptions.
- **Rationale:** rationale not captured (INTEGRATE already owns reconciling cross-leaf guidance changes per its
  Interface contract; editing it here would duplicate or conflict with that reconciliation).
- **Rejected alternatives:** Adjust the deprecation guidance in this improvement too, since it directly resolves the
  blocking condition INTEGRATE was waiting on.
- **Date:** 2026-09-18

## Success Criteria

- [x] The reported reproduction now denies: `echo hi > escape/pwned.txt` (project-local symlink `escape -> ../outside`)
      decides `deny` with a `RedirectOutsideAllowedPaths` reason, not `allow`.
- [x] The same symlink-escape is caught for `allowedCommands` argument-path validation, not just redirects (e.g.
      `cat escape/passwd` against a path-validated entry).
- [x] `PathsFilter` and `decision_for_path` (Read/Grep/Glob) are covered by at least one test each demonstrating they
      inherit the fix via the shared `absolute_path_of` seam (no per-consumer code change was needed, but the fix must
      be proven to actually reach them).
- [x] `additionalAllowedPathPrefixes` entries now expand `~` (e.g. `~/.config` matches a path under the real home
      directory via the injected/fake home).
- [x] A dangling symlink, a symlink loop, and a self-referencing symlink are each covered by a test and do not raise an
      unhandled exception through `Config.decision_for`/`decision_for_path`.
- [x] All twelve existing `test_path_resolution.py` tests and the full `test_permission_decisions.py` suite remain green
      (no regression from constructing `PathResolutionContext` without an injected `realpath_predicate`, which must keep
      defaulting to a no-op).
- [x] `cd packages/command-policy/tests && nix-shell --run pytest` is green (modulo the four pre-existing `xargs`-parser
      failures already tracked as out of scope — see the decision-model knowledgebase article's Gotchas section).
      CORRECTION during implementation: the actual pre-existing baseline is TWO failures, not four (confirmed by running
      the full suite before any change: `test_a_nested_command_filter_composes_with_other_filters_across_entries` and
      `test_propagation_does_not_see_operands_arriving_on_stdin`, both
      `ParserCouldNotInterpretInvocation(program=xargs)` — matching the task's own "EXPECTED TEST BASELINE" section, not
      this Success Criterion's stale "four"). Final run after all changes: same 2 failures, 625 passed (613 baseline +
      12 new).
- [x] No change is made to `docs/knowledgebase/command-policy-decision-model.md`'s deprecation language or to
      `plugin.json`/`marketplace.json` — per the Design Decision to leave that to the trunk's INTEGRATE session. NOTE:
      the repo's Stop hook flagged that the article should document the new mechanism, which the Design Decision does
      not forbid (it scopes only the "switch now" deprecation-guidance language, not the whole file). Added two
      narrowly-scoped, timeless paragraphs — one extending the existing Parsers/`PathResolutionContext` paragraph to
      describe the `realpath_predicate` seam and its symmetric boundary resolution, one new Gotchas bullet on TOCTOU —
      leaving the "Two Packages, One Job" deprecation section (lines ~9-13) untouched. Confirmed via `git diff` that no
      line in that section changed.
- [x] `sensitive_paths_policy.py` is left UNCHANGED (Proposed Approach step 6) — its raw-text substring matching is out
      of scope by design. If implementation finds itself editing Pass 0, that is a scope breach: stop and raise it
      rather than folding it in.

## Implementation TODO

- [x] Update status to in-progress
- [x] Read `packages/command-policy/lib/path_resolution.py`, `packages/command-policy/tests/test_path_resolution.py`,
      and `packages/command-policy/tests/test_permission_decisions.py` fresh (implementation runs in a separate context
      with no memory of this planning session)
- [x] TDD: write a failing unit test in `test_path_resolution.py` for the injected `realpath_predicate` seam (fake
      predicate; no real FS) before touching production code
- [x] Add `realpath_predicate` to `PathResolutionContext.__init__` (default: identity `lambda path: path`) and to
      `for_process()` (`os.path.realpath`); store as `self._realpath`
- [x] Realpath `self._cwd` once at construction (`self._cwd = realpath_predicate(cwd)`)
- [x] Split `absolute_path_of` into a private lexical helper (existing `~`/absolute/cwd-relative-join logic, unchanged)
      plus a realpath step applied to the result; TDD each branch
- [x] Route `is_contained`'s prefix handling through `self.absolute_path_of(prefix)` instead of `_is_within`'s bespoke
      `os.path.normpath(prefix)`; drop the now-redundant normpath call from `_is_within` itself; TDD the `~`-expansion
      and realpath-on-prefix cases
- [x] **Milestone:** all `test_path_resolution.py` unit-level cases green, including the one real-`tmp_path`-symlink
      case (dangling, loop, self-reference, and the escape-to-outside reproduction all covered)
- [x] Add the decision-spec case(s) to `test_permission_decisions.py` using `cwd_pinned_inside_project` + a real
      symlink: the redirect-escape reproduction from the task report, and the argument-path-validation mirror case
- [x] **Milestone:** `cd packages/command-policy/tests && nix-shell --run pytest` green except the four pre-existing
      tracked `xargs` failures (confirm the count/cause hasn't changed — if it has, that is a new regression to flag,
      not silently absorb). Actual pre-existing count is TWO, not four (see Success Criteria correction note); confirmed
      unchanged after the fix.
- [x] Verify the fix reaches `PathsFilter` and `decision_for_path` (Read/Grep/Glob) with at least one test each, since
      Success Criteria requires proving this rather than inferring it from the shared-seam design
- [x] Confirm no edits were made to `docs/knowledgebase/command-policy-decision-model.md`'s deprecation language or to
      `plugin.json`/`marketplace.json` (Design Decision: left to INTEGRATE)
- [x] Update status to completed
