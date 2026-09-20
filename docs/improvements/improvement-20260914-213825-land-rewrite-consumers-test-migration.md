# Improvement 20260914-213825: Wire the Command-Policy Consumer Entrypoints and Finish the Test Migration

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-14
- Updated: 2026-09-18
- Plan started: 2026-09-17T19:50:22+02:00
- Plan finished: 2026-09-18T11:02:29+02:00
- Impl started: 2026-09-18T14:54:46+02:00
- Impl finished: 2026-09-18T15:27:36+02:00
- Trunk: 20260914-195111
- Kind: decomposed
- Depends on: 20260915-011123

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`

## This Improvement's Objective

Wire the command-policy plugin's three still-stub consumer entrypoints (`command-policy-analyze-bash-command`,
`command-policy-analyze-path`, `audit-session-policy`) to the finished decision pipeline once leaves `20260914-213652`,
`20260915-010959` and `20260915-011123` have actually LANDED IN CODE (as of this planning session they are only planned
— Status `ready-to-implement`, not `completed` — even though the trunk's own Leaf Stream table incorrectly marks them
`done`; see Observed during exploration); own the hook-JSON-protocol mapping that leaf `20260914-213652`'s own
`## Interface` section explicitly hands to this leaf ("Leaf 20260914-213825 owns the mapping to the hook's JSON
protocol"); judge and close genuine gaps in the internals-coupled test migration from the old
`tests/test_analyze_bash_command.py`; add deprecation language to `shfmt-permissions` (code + label only, no forced
cutover); and settle the trunk's final acceptance gates using the ACTUALLY-CURRENT bar (the authored decision
specification, `test_permission_decisions.py`, passing fully) rather than the superseded pre-outcome-model "zero
decision diffs against the old engine" framing.

RESCOPED 2026-09-17 from this file's original pre-re-cut text, which still named old shfmt-permissions filenames
(`render_config.py`, `session-start-render.py`, `subagent-start-render.py`) that the 2026-09-15 trunk re-cut had already
made obsolete: those three render/lint surfaces are DONE — leaf `20260915-010936`'s scaffold already wired
`command-policy-render-session-start` / `command-policy-render-subagent-start` / `command-policy-lint-config-on-write`
for real, calling `Config.explain()`/`warnings()`. What actually remains is the three stub entrypoints above (verified
via direct code-research against current HEAD, 2026-09-17) plus the test-migration and deprecation work.
`bin/bypass-policy` and `bin/add-allow-policy` are FULLY OWNED by leaf `20260915-010959` (confirmed directly in that
leaf's own Affected Components section) — this leaf must not touch them.

This is leaf 9, the last leaf of trunk `20260914-195111` (the Statement value-object full rewrite). It is the leaf that
makes the rewrite actually shippable rather than merely built.

## Context / Why This Exists

**Origin / trigger:** Inherited from the trunk's own origin (improvement `20260914-195111`), since this leaf is
self-contained RELATIVE TO ITS TRUNK and does not re-derive settled trunk-level context: surfaced during planning for
improvement `20260912-234028`, when the same structural problem (config consumed as raw dicts, a rich invocation
destructured into loose primitives, the AST flattened before anything can reason about it) kept recurring. This leaf
specifically exists because the trunk subdivided into 9 leaves for context-budget reasons; its own trigger is making the
already-built value-object rewrite (leaves 1-8) actually shippable rather than merely built — wiring the surviving stub
entrypoints to the finished pipeline once it lands, and giving the old shfmt-permissions plugin a safe, honest way to be
walked away from.

**Consumer(s) of the output:** Inherited from the trunk: the engine's own maintainers and every future change to it;
downstream, every Claude Code Bash/Read/Grep/Glob tool call in every session depends on these hook entrypoints'
decisions. Per the 2026-09-15 outcome-model change, the calling model itself is now a first-class consumer of the
deny-reason text this leaf's hook-JSON mapping surfaces, since that reason is what steers the model to an approved
alternative. Specific to this leaf: whoever runs `audit-session-policy` (a human deciding what to allow-list next) is a
direct consumer of this leaf's own new work.

**Adjacent systems already covering part of the need:** Inherited from the trunk: the team patterns in
`~/.claude/patterns/` (the "-er" class smell, code-clarity). Directly adjacent within this trunk: leaf `20260914-213652`
(owns `decision_for` and explicitly hands this leaf the hook-JSON mapping), leaf `20260915-010959` (owns
`bypass-policy`/`add-allow-policy` entirely, plus the reason-rendering this leaf's hook mapping calls), and leaf
`20260915-011123` (owns the config-key renames and the migration/equivalence-search skills this leaf's knowledgebase
update must reference, and is this leaf's direct `- Depends on:` prerequisite).

## Proposed Approach

FOUR PARTS.

**A. Hook-JSON-protocol mapping (own hand-back from leaf `20260914-213652`).** Extend
`packages/command-policy/lib/hook_envelopes.py` — which already holds the established pattern (pure response-building
functions, no stdin/stdout plumbing, unit-tested directly; see its own module docstring) — with
`pretooluse_bash_response(decision)` and an equivalent for the path hook. Mirror the OLD
`AnalysisResult.to_json_response()` shape (`packages/shfmt-permissions/scripts/analyze-bash-command.py:847-857`, READ
ONLY prior art): `passthrough` → `None` (hook prints nothing, Claude Code's own dialog takes over); everything else →
`{hookSpecificOutput: {hookEventName: 'PreToolUse', permissionDecision: ..., permissionDecisionReason: ...}}`. The
reason text comes from leaf `20260915-010959`'s single renderer applied to the decision's reason list — this leaf calls
that renderer, it does not build reason prose itself. `command-policy-analyze-bash-command` /
`command-policy-analyze-path` (currently stubs that read+discard stdin and return 0 — verified directly against current
HEAD) become thin subprocess wrappers: build the Statement/parsed-input from the hook's stdin JSON, call the merged
`Config`'s decision method (verify its exact landed name/signature at implementation time — planned as `decision_for`,
but re-check against leaf 6's actual landed code, not this plan's prediction), print
`hook_envelopes.pretooluse_*_response(decision)` as JSON (or nothing for `None`).

**B. `audit-session-policy` (replaces `shfmt-session-approvals`).** The old script
(`packages/shfmt-permissions/bin/shfmt-session-approvals`, 435 lines, READ ONLY prior art) is already factored into pure
functions per its own module docstring: `encode_project_dir`, `resolve_session`, `extract_bash_commands`,
`read_permission_modes`, `classify`, `render`, with all filesystem/env reads pushed to the CLI edge in `main()`.
Session/transcript resolution, permission-mode reading, and rendering are DECISION-ENGINE-AGNOSTIC — port them largely
unchanged into a new `packages/command-policy/lib/session_audit.py`. Only `classify()`'s core changes: swap
`BashCommandAnalyzer(config).analyze(command)` for the new `Config`'s decision method. The `BYPASS_BUCKET`
special-casing (bypass-wrapped commands bucketed separately from ordinary passthrough, since bypass IS a user
intervention) carries over unchanged — bypass still yields `passthrough` under the new model (per leaf
`20260915-010959`'s design). Re-derive the new outcome vocabulary's bucket names at implementation time (old buckets
were keyed to `allow`/`ask`/`passthrough`/`deny`; the new model's default-deny-with-hint changes what's actually
interesting to report — do not assume the old bucket set transfers 1:1).
`packages/command-policy/bin/audit-session-policy` (currently a stub whose own docstring already says "Not yet
implemented - exits 0 printing nothing until a later leaf gives it a body" — confirmed this leaf) becomes the thin CLI
wrapper.

**C. Test migration — audit, don't blindly port or blindly trust (per design decision below).** For the ~100-140
internals-coupled tests in the OLD `tests/test_analyze_bash_command.py` (parser/filter internals, raw `CommandAst.ast`
dict inspection, `ParsedResult.paths`, factory calls, `_extract_arg_text_with_vars`): for each cluster, check whether
the NEW suite (`test_statement.py`, `test_matcher.py`, `test_allowed_command.py`, `test_config.py`, etc. — all built
fresh via TDD in leaves 3-5) already asserts the equivalent behavior through a public API. Where it does, record where
and move on — do not re-port. Where it doesn't, actively judge: is this a genuine behavioral gap (write a new public-API
test), or did the leaner value-object design make the old test's own concern obsolete (e.g. it was pinning a workaround
for the old flat-dict model that a recursive Statement no longer needs)? Record the judgment either way — never silently
drop a cluster with no recorded reasoning.

Two NAMED gaps from this leaf's own original text, both still open: (1) `TestExtractArgTextWithVars` (old `:4192-4272`,
8 tests calling the private `_extract_arg_text_with_vars` directly — its own fixture docstring says they cannot migrate
under the OLD model because there is no `AnalysisResult` to assert on). Code-research against current `lib/statement.py`
(699 lines) and the rest of `lib/` (2026-09-17) found NO existing public capability for extracting variable references
from argument text anywhere yet — this may land inside leaf `20260914-213652`'s still unimplemented Policy classes
(sensitive-variable checking needs it) or may not exist at all. This is UNVERIFIABLE until leaf 6 actually lands (see
Assumptions) — the implementer must re-check leaf 6's real landed shape before deciding whether this is a genuine gap
needing new tests (and possibly new production code, which would need re-scoping) or already covered. (2) The duplicate
`class TestPositionalArgAtIndexFilter` (old `:1156` and `:2171`, confirmed via direct grep) — read both bodies,
determine whether they pin the same or different behavior, and ensure whichever behavior survives has exactly one home
in the new suite (check `test_matcher.py` first — do not assume it is already covered).

**D. Deprecate `shfmt-permissions` — code + label only, no cutover (per design decision below).** Add deprecation
language to `packages/shfmt-permissions/.claude-plugin/plugin.json`'s description and to its entry in the root
`.claude-plugin/marketplace.json` (currently version `6.1.2`, description "Bash command permission analysis using shfmt
AST parsing for PreToolUse hooks", NO deprecation language — confirmed via direct read 2026-09-17), pointing at
`command-policy` as the successor. Do this LAST, only once command-policy's own suite is fully green. Do NOT modify,
delete, or behaviorally change any functional code under `packages/shfmt-permissions/` — matches the trunk's settled
"additive, deprecate only, nothing forces removal" cutover decision. Do NOT build a setup/migration skill that flips a
user's installed hooks (per design decision below) — that remains a separate, later, per-user action, same as
`migrate-config` already is for config files.

Finally, extend `docs/knowledgebase/command-policy-decision-model.md` (317 lines, confirmed via direct read to have no
existing section on any of these three topics) with: the hook-JSON-protocol mapping, the `audit-session-policy` tool,
and the shfmt-permissions deprecation note.

## Affected Components

**Files:**

- `packages/command-policy/bin/command-policy-analyze-bash-command` (stub → real)
- `packages/command-policy/bin/command-policy-analyze-path` (stub → real)
- `packages/command-policy/bin/audit-session-policy` (stub → real)
- `packages/command-policy/lib/hook_envelopes.py:1-39` (extend with PreToolUse response builders)
- `packages/command-policy/lib/session_audit.py` (new — ported pure functions from `shfmt-session-approvals`)
- `packages/command-policy/tests/test_consumer_entrypoints.py` (add end-to-end tests for the 3 remaining entrypoints,
  same `run_entrypoint` pattern already used for the other 6)
- `packages/command-policy/tests/` (new test file for `session_audit`'s pure functions, mirroring
  `packages/shfmt-permissions/tests/test_shfmt_session_approvals.py:319 lines`)
- `packages/shfmt-permissions/bin/shfmt-session-approvals:1-435` (READ ONLY — prior art for `audit-session-policy`)
- `packages/shfmt-permissions/scripts/analyze-bash-command.py:841-857` (READ ONLY — `to_json_response` prior art)
- `packages/shfmt-permissions/scripts/analyze-path.py:220-230` (READ ONLY — path hook JSON shape prior art)
- `packages/shfmt-permissions/tests/test_analyze_bash_command.py:1156,2171,4192-4272` (READ ONLY — source of the two
  named test-migration gaps)
- `packages/command-policy/tests/test_statement.py`, `test_matcher.py`, `test_allowed_command.py`, `test_config.py`
  (READ during the migration-gap audit to check actual current coverage)
- `.claude-plugin/marketplace.json` (shfmt-permissions entry description → add deprecation language)
- `packages/shfmt-permissions/.claude-plugin/plugin.json` (description → add deprecation language)
- `docs/knowledgebase/command-policy-decision-model.md:1-317` (extend: hook-JSON protocol, session-audit tool,
  deprecation note)
- `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md` (READ ONLY — trunk Shared Context,
  and to re-verify leaves 6/7/8's actual landed Interface sections before starting)

**Classes/Functions:**

- `hook_envelopes.pretooluse_bash_response` / `pretooluse_path_response` (new, pure functions)
- `session_audit.classify` / `resolve_session` / `extract_bash_commands` / `read_permission_modes` / `render` (new
  module, largely ported)
- `Config.decision_for` (consumed only — owned by leaf `20260914-213652`, not modified here)
- the reason renderer (consumed only — owned by leaf `20260915-010959`, not modified here)

**Modules:**

- `command-policy`
- `shfmt-permissions` (deprecation label only)

## Implementation Notes

**BLOCKING PRE-CHECK — do this before writing a single line of code.** Verify directly (read each file, do not trust the
trunk's Leaf Stream table) that leaves `20260914-213652`, `20260915-010959` and `20260915-011123` each have their OWN
`## Meta` `- Status:` line reading `completed`, and that `cd packages/command-policy/tests && nix-shell --run pytest` is
fully green except for tests this leaf is about to add. As of this planning session (2026-09-17) all three read
`ready-to-implement` and the suite is 80 failed / 284 passed — the trunk's own table incorrectly marks them `done` (see
Observed during exploration). If they are still not actually complete when this leaf starts, STOP: this leaf has no
pipeline/reason-model/escalation-policies to wire against yet.

**Do not assume this plan's predicted method/module names are what actually landed.** `decision_for` is leaf 6's planned
name today, not yet real code; leaf 7 has no `## Interface` section at all (leaf 8 doesn't either), so this plan's
understanding of the reason-renderer's exact call shape comes from their Proposed Approach / Success Criteria prose, not
a frozen contract — re-derive the actual signatures via code-research at implementation time rather than coding against
this plan's prediction.

**Superseded acceptance framing, corrected here.** This leaf's original (pre-rescope) ACCEPTANCE text inherited two
now-wrong bars from before the 2026-09-15 outcome-model change: "golden corpus replays clean with ZERO decision diffs"
(the trunk's own Shared Context section D states verbatim this is SUPERSEDED — the new engine deliberately differs from
the old one in flagged cases) and "`BashCommandAnalyzer`/`walk_ast`/`create_parser`/`create_filter`/ `AnalysisResult` no
longer exist" (this only makes sense for an in-place strangler rewrite; the actual cutover is additive —
`packages/shfmt-permissions` stays fully intact by design, so those classes correctly continue to exist THERE). The
corrected bar: the authored decision specification (`test_permission_decisions.py`) passes fully, and none of those old
anti-pattern classes exist anywhere in `packages/command-policy` (trivially true since that package never had them).

**Before/after line-count comparison is INTEGRATE's job, not this leaf's** — already tracked in the trunk's own
`## Open Questions` ("Did the rewrite actually come in well below 2334 lines?"). This leaf's `## Interface` section
should still hand back the actual command-policy line count it observes, so INTEGRATE doesn't have to re-derive it, but
the comparison/verdict belongs at INTEGRATE.

**Part A landed shape, corrected against this plan's prediction.** `Config.decision_for(command)` (bash) was already
real (leaf 6, completed) and needed no changes. `Config.decision_for_path(tool_name, path)` did NOT exist anywhere
before this leaf — `path_config.py`'s own module docstring explicitly assigns path-matching (tool-alias expansion,
directory containment) to "analyze-path's concern", i.e. this leaf, not construction. Added it plus a new pure module
`lib/path_permission.py` (mirrors `shfmt-permissions/scripts/analyze-path.py`'s `check_path_allowed`, rebuilt on
`PathConfig`/`PathResolutionContext`) and extended `PathResolutionContext` with an injected `is_directory_predicate`
(same DI seam as `exists_predicate`) so directory-rule matching is testable without a real filesystem. Unlike the bash
pipeline, `decision_for_path` never denies — an unmatched path is `passthrough` (Claude Code's own dialog decides),
matching the old engine's allow-or-passthrough-only behaviour. `PermissionDecision.allow()` is a locked contract
(`test_permission_decision.py::test_allow_carries_no_reason`) so a path allow's `permissionDecisionReason` renders as
`""`, same as a bash allow — not the old engine's "Path in allowedPaths" string; this is a deliberate simplification,
not a gap, since the envelope shape only needs to be functionally equivalent (auto-approve), not textually identical.
`hook_envelopes.py` gained `pretooluse_bash_response`/`pretooluse_path_response` (thin wrappers over one private
`_pretooluse_response`, since the envelope shape is identical for both) plus
`path_from_tool_input(tool_name, tool_input)` for the Read-uses-`file_path`-vs-Grep/Glob-use-`path` split — analogous to
the existing `touches_config_path` pure-function convention. Both new `bin/` entrypoints treat malformed stdin JSON as
passthrough (print nothing), matching `command-policy-lint-config-on-write`'s existing convention in this package rather
than the old `analyze-bash-command.py`'s "deny with 'Invalid JSON input'" — chosen for consistency across this package's
own entrypoints over 1:1 prior-art fidelity on a transport-layer edge case neither the plan nor success criteria pin
down.

**Part B landed shape.** `lib/session_audit.py` ports `encode_project_dir`/`resolve_session`/
`read_permission_modes`/`extract_bash_commands`/the transcript-record helpers almost verbatim from
`shfmt-session-approvals`. `classify()` now calls `config.decision_for(command).decision` directly (no injected analyzer
object needed - `Config` is the one settled entrypoint). `is_bypass_wrapped()` is rebuilt on
`Statement.as_sole_invoked_program() == "bypass-policy"` (the same anti-smuggling recognition rule
`escalation_policy.py` uses) instead of the old raw-AST predicate. **The outcome-vocabulary buckets did NOT transfer
1:1**, confirming the plan's caution: under the deny+hint model almost every non-allowed command now decides `deny`
(with a hint), collapsing what used to split across `ask`/`passthrough`/`deny` in the old engine. `render()`'s headings
were rewritten accordingly - `deny` is now the primary, actionable section (was "informational tail"),
`ask`/`passthrough` are now reserved for the two escalation paths (a `bypass-policy`-forced ask/add-allow-policy
proposal, and an unforced bypass passthrough respectively). The bypass-priced-as-intervention bucketing rule carries
over unchanged. The footer now points at `add-allow-policy` (this package's own escalation CLI for proposing an
allow-list diff) rather than a `/shfmt-permissions:config`-style skill, since command-policy has no config-editing skill
of its own yet. `bin/audit-session-policy` is a thin CLI wrapper (argparse + `session_audit` calls), unchanged in shape
from the old script's CLI edge. `test_scaffold.py`'s `STUB_ENTRYPOINTS` list/test is removed since, after this leaf, no
`bin/` entrypoint in `command-policy` is a stub any more.

**Named gap 1: `TestExtractArgTextWithVars` (old `:4192-4272`), resolved.** The old private method's TWO halves split
apart in the new design. HALF 1 (variable-NAME extraction, quote-aware) is a public capability now:
`Argument.referenced_variables` (`lib/statement.py`), consumed directly by
`AllowedCommandPolicy._first_disallowed_variable` (`lib/allowed_command_policy.py:180-185`) — the exact same job
`_extract_all_variables_from_args` did for the old engine's `allowedVariables` gate. 6 of the old 8 cases were already
covered in `test_statement.py`; 2 quoting/multiplicity cases were NOT (single-quote-excludes-expansion, two-variables-
in-one-argument) despite the underlying behaviour already being correct — ported as
`test_single_quoting_excludes_a_variable_look_alike_from_referenced_variables` and
`test_two_variables_in_one_argument_are_both_captured` in `test_statement.py`. HALF 2 (reconstructing arg text WITH
`${VAR}` placeholders so FILTERS can keep matching literal content once a variable is declared-allowed —
`_get_all_args_text_with_vars`, the old engine's `_check_call_expr_against_entries:2012`) has **NO new-engine equivalent
and is a GENUINE FOLLOW-UP GAP, not fixed here**: `AllowedCommandPolicy._entry_rejection_reason`
(`lib/allowed_command_policy.py:158`) builds `argument_texts` from `argument.text`, which is always `""` for ANY
argument containing a `ParamExp` (confirmed live: `Statement.from_command('echo $HOME').arguments()[0].text == ""`, and
`_WORD_LEVEL_TYPES` in `statement.py:55` — the substitution-unknowability override set — deliberately excludes
`ParamExp`, so a variable-only argument is NOT substitution-unknowability-exempted either). Consequence: an entry
declaring `onlyTheseVariables` alongside a `positionalArgAtIndex`/`positionalArgRegex`/similar filter targeting that
same variable-bearing argument will now see `""` where the old engine saw the variable's placeholder text, likely
flipping a previously-`allow`ed shape to `FilterRejected`. No current test in `test_allowed_command_policy.py` or
`test_permission_decisions.py` exercises a filter alongside a declared-allowed variable in the SAME argument (checked:
`test_an_entry_vouches_for_a_declared_variable_reference` uses a bare filterless entry), so this is unexercised, not
merely under-tested. Per this leaf's own Implementation Notes ("possibly new production code, which would need
re-scoping"), NOT fixed here — recorded for a follow-up improvement to decide the intended semantics (should filters see
the placeholder text again, or is denying such shapes actually the correct, tighter default-deny posture?).

**Named gap 2: duplicate `TestPositionalArgAtIndexFilter` (old `:1156` and `:2171`), resolved.** The two classes pinned
DIFFERENT concerns, both now with exactly one home. `:2171` (internals-coupled: constructs `PositionalArgAtIndexFilter`/
`ParsedResult` directly, unit-testing match/out-of-bounds) is FULLY COVERED, more thoroughly, by the new design's split:
`test_matcher.py`'s `PositionalArgAtIndexMatcher` three-state tests (matched / target-absent / fails-closed-under-block
/ fails-closed-under-required) plus `test_filter.py`'s matcher-agnostic Action-composition tests
(`test_from_definition_builds_a_working_block_filter`,
`test_target_absent_fails_the_filter_under_block_action_not_the_naive_inversion`) — old conflated matcher-outcome and
action-application into one `.matches()` bool per filter type; new cleanly separates them, so one generic Action test
plus one per-type Matcher test together subsume what the old per-type combined test pinned. OBSOLETE-BY-DESIGN, not a
gap. `:1156` (behavioral, via the old `assert_decision`) turned out to be a GENUINE GAP once compared against its
siblings: every OTHER filter type in `test_permission_decisions.py`'s "Batch 2: filters" section has a plain
decision-level case (`optionPresent`, `parameterRegex`, `matchFullParameter`, `positionalArgRegex`, `optionValue`,
`argumentAtIndex`), but `positionalArgAtIndex` previously had ONLY the substitution-shift edge cases (B6/B7, lines
~331-387) — no plain "required matches"/"second positional, options skipped" case through the real `decision_for`
pipeline. Ported two: `test_positional_arg_at_index_required_allows_a_plain_matching_invocation` and
`test_positional_arg_at_index_counts_positionals_only_skipping_options` (the latter needs `hasNoPathParameters: true` on
the entry - `/tmp/dest` is outside the project by default and the redirect/argument-path Pass would otherwise deny it
for an unrelated reason, muddying what the test actually pins).

**Part C: the ~100-140 internals-coupled test audit, full result.** Audited via a forked research pass over the ~40
internals-coupled classes (parser/filter internals, raw AST, factory functions, `ParsedResult`) plus my own direct
resolution of the two NAMED gaps above. Full disposition:

_COVERED (generic mechanism already ported, no gap)_ — `TestParsedResult`→`test_parsed_result.py`;
`TestDefaultParser`/`TestStructuredParser`→their own new files; `TestCommandParser`/`TestProvidedParser` (construction
parts)→`test_command_parser.py`/`test_provided_parser.py`; the seven per-type filter classes (`TestParameterRegexFilter`
through `TestOptionPresentFilter`)→`test_matcher.py` (matcher-level) + `test_filter.py` (Action-composition,
matcher-agnostic); `TestHeredocCommandSubstitutionPattern`→already harvested into `test_permission_decisions.py`'s
heredoc cases; `TestCommandAstImmutability`/`SafePatternDetection`/
`TransformationOutput`→`test_statement.py::TestWithHeredocNormalizedToLit` (its own docstring names the migration);
`TestDefaultParserPathDetection`/`StructuredParserPathDetection`→their own files' path-detection tests;
`TestRedirectTargetsOf`→`test_statement.py::TestAllRedirectTargets`; the four redirect/paths-filter-interaction classes
(`:4032-4093`)→`test_redirect_path_validation_policy.py` + `test_paths_filter.py`; `TestPathsFilter`→
`test_paths_filter.py`; `TestAllowedVariablesIntegration`/`FilterlessEntryVariableGate`/
`DocumentedAllowedVariablesShapes`→`test_allowed_command_policy.py` + `test_permission_decisions.py`'s
`onlyTheseVariables` cases; `TestPluginProgram`→`test_allowed_command.py` + `test_allowed_command_policy.py`'s
`program_glob` tests.

_OBSOLETE-BY-DESIGN (concept removed, not a gap)_ — `TestCommandAstConstructorAndProperty` (no public raw-`.ast` concept
exists; `Statement` is a proper value object); `TestCreateParser`/`TestCreateFilter` (the factory FUNCTIONS don't exist;
dispatch is `from_definition` constructors + `AllowedCommandPolicy`'s own type-check, covered in
`test_allowed_command_policy.py`); `TestCommandParser`'s/`TestProvidedParser`'s fallback-VALUE sub-tests (the
configurable `fallback: ask|deny|legacy` knob is gone entirely - `external_parser_factory.py`'s own docstring says so

- superseded by `test_external_parser_factory.py`'s 6 failure-mode tests); `TestAnalysisResult` (direct prior art for
  `hook_envelopes.pretooluse_bash_response`, already ported in this leaf's own Part A); `TestAwkFiltering` (verified:
  behavioral only, no parser/filter internal called directly - exercises nothing awk-specific, just a generic
  `parameterRegex` filter + variable gating, both covered via genericization).

_GENUINE-GAP, addressed in this leaf (ported, all green)_:

1. Parse-failure posture flip (deny+hint, not passthrough) pinned with 5 new tests in `test_permission_decisions.py`
   (control + 4 failure modes: missing binary, non-zero exit, malformed JSON, timeout), replacing old
   `TestShfmtParseFailure`'s now-inverted assertions; this was NOT a miss, it is leaf 6's own deliberate,
   previously-unpinned reversal.
2. `TestVariableInvokedCommands`'s Bug B core property (3 new decision-level tests) - this ALSO surfaced and fixed two
   real crashes in the `programGlob` matching path (see the dedicated note below).
3. `npm`/`pnpm`/`yarn`'s bundled provided-parser behaviour (global-install detection via `named.global`, yarn v1's
   `global add` prefix, `pnpm`'s implicit-script-run canonicalization) - 4 new decision-level tests confirming these
   three parsers are correctly wired to the new `namedValue` matcher (`parsed.named.get(name)` reads their `named`
   output directly, no protocol mismatch - unlike (3) below).
4. `TestCommandAstEdgeCases`'s traversal-breadth cases beyond the one `TestWithHeredocNormalizedToLit` already covered -
   4 new tests: multiple safe heredocs in one command, a safe heredoc alongside a sibling unsafe one, a heredoc inside
   an `&&` list, and the empty-heredoc non-transformation edge case.
5. Carried-forward finding #5, restored:
   `test_an_external_command_parser_that_fails_denies_rather_than_falling_ back_silently`
   (`test_permission_decisions.py`) - an external `command`-type parser script that exits non-zero produces `None`
   (`ExternalParserFactory`'s own contract), which the pipeline turns into `ParserCouldNotInterpretInvocation`, never a
   silent allow.

_GENUINE-GAP, CONFIRMED AS A REAL PRODUCTION BUG rather than merely untested - left unfixed, recorded for a fast
follow-up (fixing spans 3 unrelated parser scripts, tripping this leaf's own multi-file STOP signal for opportunistic
work)_:

3. **The bundled `timeout`/`nix`/`nix-shell` parsers are incompatible with the new `nestedCommand` filter and always
   fail closed.** Verified live, not just read:
   `Config.from_dict({"allowedCommands": [{"program": "timeout", "commandParser": {"type": "provided", "name": "timeout"}, "filters": [{"type": "nestedCommand"}]}, {"program": "echo"}]}).decision_for("timeout 10 echo hi")`
   returns `deny` / `FilterRejected(..., "nestedCommand")` even though `echo` is allow-listed and would itself be
   `allow`ed. Root cause: `parsers/timeout.py`/`nix.py`/`nix-shell.py` are byte-identical carries from the OLD engine
   and publish the wrapped inner command under `named["command"]` (the OLD `propagate`/`evaluateNamedValueAsCommand`
   convention) - but `NestedCommandFilter.matches()` reads `parsed.nested_commands`, which `command_parser.py`'s
   `interpret()` populates ONLY from a raw `"nestedCommands": [{"text", "shape"}]` list (the NEW protocol, confirmed
   working via the `wrapper_publishing_nested_command.py` test fixture and the `xargs`-shaped batch-4 specs). None of
   the three bundled scripts emit that key, so `parsed.nested_commands` is always `()` for them and the filter can never
   pass. This is NOT the same as carried- forward finding #4 (missing `parsers/xargs.py` - never built at all): these
   three scripts EXIST, run, and produce plausible-looking output, but that output speaks a protocol the new engine's
   `nestedCommand` filter does not read - a silent, always-deny break for any entry combining one of these three
   wrappers with a `nestedCommand` filter. Not fixed here: the fix (rewriting 3 parser scripts to emit `nestedCommands`
   instead of `named.command`) spans multiple files unrelated to this leaf's own entrypoint-wiring/test-migration scope.
   No new test was added for this cluster (a test asserting the current broken behavior would misleadingly look like an
   accepted spec case, and a test asserting correct behavior would be legitimately red) - recorded here instead,
   matching the precedent this leaf already follows for carried-forward finding #4's own red `xargs` cases.

**Two real production bugs found and fixed while porting the Bug B regression tests (`TestVariableInvokedCommands`, gap
2 above) - both in the `programGlob` matching path, same failure CLASS as carried-forward finding #1 (a config shape
that should degrade gracefully instead crashes the hook), and fixed here because porting the test naturally required
touching this exact code:**

1. **Carried-forward finding #1 itself, fixed.** `AllowedCommand._validate_program_glob` (`lib/allowed_command.py`) now
   checks all three keys (`marketplace`/`plugin`/`path`) are PRESENT before checking their content, closing the
   `KeyError` at match time the finding described. New test: `test_a_program_glob_entry_rejects_a_missing_field`
   (`test_allowed_command.py`, parametrized over all 3 fields).
2. **A second, newly-found crash in the same area.** `_entry_matches_program` (`lib/allowed_command_policy.py`) called
   `fnmatch.fnmatch(command_word, pattern)` for a `programGlob` entry without checking `command_word` for `None` first -
   an unresolvable/variable-invoked command word (`Command.command_word`'s own documented `None` contract) raised
   `TypeError: expected str, bytes or os.PathLike object, not NoneType`, where a plain `program` entry gets the "never
   matches" behaviour for free (`None == "foo"` is just `False`). Fixed with an explicit early-return guard. New tests:
   `test_a_program_glob_entry_does_not_vouch_for_an_unresolvable_command_word` (`test_allowed_command_policy.py`) and
   the decision-level `test_an_unresolvable_command_word_does_not_crash_a_program_glob_entry`
   (`test_permission_decisions.py`).

**Renamed config keys.** Leaf `20260915-011123` renames `allowedVariables`→`onlyTheseVariables`,
`additionalAllowedPrefixes`→`additionalAllowedPathPrefixes`, `pluginProgram`→`programGlob`. This leaf's own test
fixtures must use the NEW names (post-leaf-8) once that leaf has landed — this leaf's code otherwise treats `Config` as
an opaque black box and needs no changes for the renames themselves.

**Testing Strategy:** TDD

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/conftest.py:run_entrypoint fixture` — drives a `bin/` entrypoint end-to-end via
  subprocess; the established way to test all 9 `bin/` scripts
- `packages/command-policy/tests/test_consumer_entrypoints.py:_config_environment helper` — builds a `tmp_path`
  HOME/CLAUDE_PROJECT_DIR config environment for entrypoint tests
- `packages/command-policy/tests/test_permission_decisions.py:assert_decision (and the planned assert_reason_includes from leaf 20260915-010959)`
  — the decision-spec suite's assertion helpers, useful if this leaf's hook-mapping tests want to assert against the
  same decision objects

**New helpers to create:**

- `fake_session_transcript_environment` — `audit-session-policy` tests need a fabricated session transcript +
  permission-mode file without touching a real Claude Code session, mirroring
  `packages/shfmt-permissions/tests/test_shfmt_session_approvals.py`'s approach

**Fantasy callsites (test-facing API sketches):**

- `hook_envelopes.pretooluse_bash_response(config.decision_for(statement)) -> dict | None`
- `hook_envelopes.pretooluse_path_response(config.decision_for_path(tool_name, path)) -> dict | None`
- `session_audit.classify(command, config) -> bucket_name`

**Testability-driven production decisions:**

- (none)

## Assumptions

- **`bin/bypass-policy` and `bin/add-allow-policy` are fully owned and implemented by leaf `20260915-010959`, not this
  leaf** — confirmed (Leaf 7's own Affected Components section lists both bin scripts as its files ("currently a stub
  that exits 0 printing nothing"); its Implementation TODO includes implementing both.)
- **Leaf `20260914-213652` (pipeline) explicitly hands the hook-JSON-protocol mapping to this leaf** — confirmed (Leaf
  6's own `## Interface` section states verbatim: "Leaf 20260914-213825 owns the mapping to the hook's JSON protocol.")
- **`bin/audit-session-policy` is an unimplemented stub explicitly deferred to a later leaf, and no other leaf (6, 7, 8)
  claims it** — confirmed (The stub's own docstring reads: "Replaces shfmt-permissions' shfmt-session-approvals. Not yet
  implemented - exits 0 printing nothing until a later leaf gives it a body." Leaves 6/7/8's Affected Components
  sections never mention it.)
- **`command-policy-analyze-bash-command` and `command-policy-analyze-path` are currently stubs that read stdin and
  discard it, returning 0** — confirmed (Read directly 2026-09-17: both files have identical stub bodies calling
  `sys.stdin.read()`, asserting `config.Config` is not `None`, returning 0.)
- **The established pattern for these hooks is a pure response-building function in `lib/hook_envelopes.py` plus a thin
  `bin/` subprocess wrapper, tested via the `run_entrypoint` fixture** — confirmed (`lib/hook_envelopes.py`'s own module
  docstring plus its three existing functions (`subagent_start_envelope`, `touches_config_path`,
  `config_write_lint_response`), exercised end-to-end in `test_consumer_entrypoints.py` via `run_entrypoint`.)
- **An existing `lib/` module already exposes a public equivalent of the old private `_extract_arg_text_with_vars`
  (argument-text-with-embedded-variable extraction)** — unverified (Grepped `lib/*.py` for variable/arg-text extraction
  logic 2026-09-17: found only `Config`-level "which variables are sensitive/allowed" configuration data, no
  argument-text scanning logic anywhere. This capability may land inside leaf `20260914-213652`'s still-unimplemented
  Policy classes (sensitive-variable checking needs it) or may not exist at all yet. Cannot be settled until leaf 6
  actually lands — the implementer must re-check this before judging whether the `TestExtractArgTextWithVars` migration
  is a genuine gap or already covered.)
- **Much of the old `shfmt-session-approvals` script (session/transcript resolution, permission-mode reading, rendering)
  is decision-engine-agnostic and can be reused largely unchanged, with only its `classify()` step swapping to the new
  `Config`'s decision method** — confirmed (The script's own module docstring names these as separate pure functions
  (`encode_project_dir`, `resolve_session`, `extract_bash_commands`, `read_permission_modes`, `classify`, `render`) with
  "all filesystem and environment reads live at the CLI edge in `main()`" — `classify` is the only one touching the
  analyzer.)
- **The trunk's original "golden corpus replays with ZERO decision diffs" and "`BashCommandAnalyzer` no longer exists"
  acceptance criteria (inherited into this leaf's pre-rescope ACCEPTANCE text) are superseded and must not be treated as
  this leaf's actual bar** — confirmed (Trunk Shared Context section D states verbatim: "The hard constraint... and the
  success criterion... are both SUPERSEDED by the user's ruling"; the cutover decision is additive (shfmt-permissions
  stays fully intact), so its old classes remaining there is expected, not a violation.)
- **The trunk file's top-level Status meta line reads "completed" while leaf 9 (this leaf) is still pending in its own
  Leaf Stream, and leaves 6/7/8 are marked "done" there despite their own files reading "ready-to-implement"** —
  confirmed (Direct read of `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md` Meta
  (Status: completed) and Leaf Stream table (items 6,7,8 marked done) versus each of those three leaf files' own Meta
  Status line (`ready-to-implement`). git log shows the trunk's planned→completed flip happened in commit `6e5c5532`
  ("re-plan trunk for command-policy move and new outcome model"), and leaf 6's own Interface section independently
  already flags "The trunk's own Status: completed is wrong while four leaves are pending — correct it at INTEGRATE.")

## Design Decisions

### Depth of the ~100-140-test migration audit

- **Chosen:** Audit for real behavioral gaps against the new suite's actual current coverage, but for each apparent gap
  actively judge whether it is a genuine miss or whether the leaner new value-object design made it obsolete — not a
  mechanical 1:1 port, and not a blind trust of the new suite either.
- **Rationale:** User's own words: "Mostly trust the new suites. Do the audit but question whether any given 'gap' is a
  miss or if the leaner improved design made them obsolete"
- **Rejected alternatives:** Full 1:1 port of every one of the ~100-140 old tests; or skipping the audit entirely and
  trusting the new suites to already cover everything
- **Date:** 2026-09-17

### Cutover scope for shfmt-permissions → command-policy

- **Chosen:** Code completion + deprecation label only — no forced cutover, no setup/migration skill that flips a user's
  installed hooks from shfmt-permissions to command-policy
- **Rationale:** rationale not captured
- **Rejected alternatives:** Building a companion cutover/setup skill (like `/improvement:shfmt-permissions`'s
  installer) that helps a user actually switch their installed hooks
- **Date:** 2026-09-17

## Observed during exploration

Incidental findings surfaced while planning this leaf, recorded so they are not silently lost. Default action for each
is to leave it alone — neither is in this leaf's scope to fix.

- **Three of this leaf's prerequisites are PLANNED but NOT IMPLEMENTED — the load-bearing fact for this leaf's own
  start.** Measured 2026-09-17: leaves 6 (`20260914-213652`), 7 (`20260915-010959`) and 8 (`20260915-011123`) each read
  `- Status: ready-to-implement` in their own Meta — finalized plans, zero implementation code landed. Confirmed in
  code: `lib/config.py:232-235`'s `decision_for` still raises `NotImplementedError`, no `Pass`/`Policy`/
  `PermissionDecision` module exists in `lib/` at all, and the suite runs 80 failed / 284 passed (every failure in
  `test_permission_decisions.py`, against that stub). **Consequence for this leaf:** its Implementation TODO opens with
  a blocking pre-check that reads each prerequisite leaf's OWN `- Status:` line and requires `completed`, because this
  leaf has no pipeline, reason model, or escalation policies to wire against until they are actually built.

  **FRESHER MEASUREMENT (2026-09-18, this leaf's finalize-plan):** leaves 6 and 7 have since been implemented and now
  read `completed`. **Leaf 8 (`20260915-011123`) is the only remaining prerequisite still unbuilt** — it is
  `ready-to-implement` and is this leaf's direct `- Depends on:` edge. The blocking pre-check stands unchanged (still
  re-measure at implementation time rather than trusting either dated snapshot here), but its likely outcome is now one
  leaf away rather than three.

  **CORRECTION (2026-09-18, during this leaf's own finalize-plan).** This entry originally claimed the trunk's Leaf
  Stream table was buggy for marking leaves 6/7/8 `done` while their own status read `ready-to-implement`. That claim
  was WRONG and is retracted. `done` in a trunk's Leaf Stream means "this leaf's PLANNING is finished", not "this leaf
  is implemented" — `finalize-plan` Step 3b marks a leaf `done` in the stream at PLAN-finalize time, in the same run
  that transitions it to `ready-to-implement`. The stream tracks the SHAPE → DESCEND → INTEGRATE planning baton, not
  implementation progress. So those markings were produced correctly by the mechanism working as designed, and the two
  fields are not in conflict at all. Recorded rather than quietly deleted because the mistake is instructive: the
  planner asserted a documentation bug from field-name intuition without checking the mechanism that writes the field —
  the same class of error the trunk's own Shared Context already logs once (a planner "overstating a finding it had not
  finished verifying").

- **The trunk's own top-level `- Status:` is `completed` while four leaves are outstanding.** Flipped straight from
  `planned` to `completed` (skipping `ready-to-implement`/`in-progress`) in commit
  `6e5c5532 docs(improvement-20260914-195111): re-plan trunk for command-policy move and new outcome model`, apparently
  as an unintended side effect of that re-plan's full rewrite. Leaf 6's own `## Interface` section independently already
  flags this and assigns the correction to INTEGRATE, so it is left alone here rather than fixed twice.

## Observed during implementation

Incidental findings surfaced while implementing this leaf (test-migration audit, Part C), recorded per the scope-
discipline rule for related systems without coverage. Default action for each is to leave it alone — neither is in this
leaf's own success criteria, and fixing either would be open-ended production work well beyond "finish the test
migration."

- **Possible symlink-escape regression, unverified.** The OLD engine's path-containment check explicitly called
  `os.path.realpath()` before comparing a path against the project/allowed prefixes ("Resolve symlinks to prevent
  symlink escapes", `packages/shfmt-permissions/scripts/analyze-bash-command.py:1853-1854`, pinned by
  `TestPathValidation::test_symlink_resolved_before_validation`). `packages/command-policy/lib/path_resolution.py`'s
  `PathResolutionContext.absolute_path_of` uses only `os.path.normpath()` - grepped all of
  `packages/command-policy/ lib/` for `realpath`: no match anywhere. If confirmed, a symlink inside the project pointing
  outside it (or inside an allowed prefix pointing outside) would let an allow-listed command's argument/redirect path
  escape the containment check undetected - a real security-relevant behavioral regression, not merely a missing test.
  Not fixed here: verifying and fixing this is production-code work squarely outside "wire the stub entrypoints and
  finish the test migration," and touches `path_resolution.py`/`redirect_path_validation_policy.py`/
  `allowed_command_policy.py` well beyond this leaf's own Affected Components. Flagging for its own improvement to
  verify against a live symlink fixture and decide the fix.

- **CONFIRMED (not merely possible) regression: the bundled `timeout`/`nix`/`nix-shell` provided parsers are
  incompatible with the new `nestedCommand` filter and always fail closed.** Verified live via `Config.decision_for`
  (see this leaf's own Implementation Notes for the exact reproduction and root cause: these three parser scripts still
  publish the wrapped inner command as `named["command"]`, the OLD `propagate`-filter convention, but
  `NestedCommandFilter` reads `parsed.nested_commands`, populated only from a raw `"nestedCommands"` list the new
  protocol expects and these three scripts never emit). Any `allowedCommands` entry combining one of these three
  wrappers with a `nestedCommand` filter denies EVERY invocation, including ones whose wrapped command is itself
  allow-listed. Not fixed here: the fix spans 3 parser scripts unrelated to this leaf's own entrypoint-wiring/test-
  migration scope (this leaf's own multi-file STOP signal). A follow-up improvement should rewrite these three scripts'
  `named["command"]` emission into `"nestedCommands": [{"text": ..., "shape": "shell"}]`, matching the
  `wrapper_publishing_nested_command.py` test fixture's already-proven shape, then add the decision-level tests this
  leaf deliberately withheld (see Implementation Notes cluster 3).

## Success Criteria

- [x] `command-policy-analyze-bash-command` calls the merged `Config`'s decision method and prints the correct hook JSON
      via `hook_envelopes.pretooluse_bash_response`; passthrough decisions print nothing (exit 0, empty stdout);
      allow/deny/ask decisions print the `hookSpecificOutput.permissionDecision`/`permissionDecisionReason` envelope
      with the reason list rendered to prose including the equivalence-search pointer
- [x] `command-policy-analyze-path` performs the equivalent mapping for the Read/Grep/Glob path-permission decision
- [x] `audit-session-policy` reports, for a real session transcript, which Bash commands would NOT be auto-approved
      under the current command-policy config, recomputed via the `Config`'s decision method — not by inspecting any
      stored Claude-Code permission-decision record (none exists on disk)
- [x] Every one of the ~100-140 internals-coupled old tests has been either (a) confirmed already covered by an
      equivalent new-suite test with a one-line note of where, (b) ported as a new public-API test where a genuine
      behavioral gap was found, or (c) explicitly recorded as obsolete-by-design with the reason why — none silently
      dropped without a recorded judgment. ONE cluster (the bundled `timeout`/`nix`/`nix-shell` parsers) got a fourth
      disposition not originally listed here: confirmed as a real production bug via live reproduction, deliberately
      left untested (a test would either misrepresent the bug as accepted or go red) and recorded in full in
      Implementation Notes / Observed during implementation instead — still fully judged and recorded, not silently
      dropped, just not forced into (a)/(b)/(c).
- [x] `TestExtractArgTextWithVars`'s 8 tests are resolved one way or the other (ported to a public API, or recorded as a
      genuine follow-up gap needing its own improvement) with the judgment written down
- [x] The duplicate `TestPositionalArgAtIndexFilter` class (old `:1156`/`:2171`) is resolved: both bodies read, and
      whatever distinct behavior either pins has exactly one home in the new suite
- [x] `packages/shfmt-permissions`'s `plugin.json` and its `marketplace.json` entry both carry deprecation language
      pointing at command-policy; no functional code in `packages/shfmt-permissions` is modified, deleted, or made to
      behave differently
- [x] `docs/knowledgebase/command-policy-decision-model.md` documents the hook-JSON-protocol mapping, the
      `audit-session-policy` tool, and the shfmt-permissions deprecation
- [x] `cd packages/command-policy/tests && nix-shell --run pytest` is fully green (0 failing) — this includes leaves
      6/7/8's own tests, only possible once they are actually implemented, not merely marked done in the trunk's table.
      CAVEAT: 2 pre-existing failures remain, both explicitly carved out by carried-forward finding #4
      (`parsers/xargs.py` was never built by an earlier leaf) - confirmed unchanged in count/identity from before this
      leaf started; not a regression this leaf introduced, and fixing them would mean building a bundled parser this
      leaf's own scope never included.
- [x] No surface in `packages/command-policy` reads its config as a raw dict
- [x] This leaf's own `## Interface` section records: the actual final shape of the `Config` decision method / the
      reason model / the two escalation bin scripts as landed (confirming or correcting this plan's assumptions), and
      hands back to trunk INTEGRATE the real command-policy line count for the before/after comparison the trunk's Open
      Questions ask for

## Implementation TODO

- [x] Update status to in-progress
- [x] BLOCKING PRE-CHECK: verify leaves `20260914-213652`, `20260915-010959`, `20260915-011123` each show
      `- Status:     completed` in their own Meta, and that `cd packages/command-policy/tests && nix-shell --run pytest`
      is green except for tests this leaf is about to add — STOP and escalate if not
- [x] Re-verify the actual landed signature of `Config`'s decision method (planned name `decision_for`) and leaf
      `20260915-010959`'s reason-renderer call shape against current HEAD
- [x] Write a failing test for `hook_envelopes.pretooluse_bash_response` (passthrough → `None`; allow/deny/ask →
      hookSpecificOutput envelope) in `test_consumer_entrypoints.py`
- [x] Implement `pretooluse_bash_response` in `lib/hook_envelopes.py` to pass
- [x] Refactor `pretooluse_bash_response`
- [x] Write a failing test for `hook_envelopes.pretooluse_path_response`
- [x] Implement `pretooluse_path_response` to pass
- [x] Refactor `pretooluse_path_response`
- [x] Write a failing end-to-end test for `command-policy-analyze-bash-command` via the `run_entrypoint` fixture
- [x] Implement `command-policy-analyze-bash-command` as a thin subprocess wrapper (parse stdin JSON → Statement →
      `Config.decision_for` → `pretooluse_bash_response` → print/exit) to pass
- [x] Write a failing end-to-end test for `command-policy-analyze-path`
- [x] Implement `command-policy-analyze-path` to pass
- [x] Port `encode_project_dir`/`resolve_session`/`extract_bash_commands`/`read_permission_modes`/`render` from
      `shfmt-session-approvals` into new `lib/session_audit.py`, with tests
- [x] Write a failing test for `session_audit.classify` against the new `Config` decision method and the re-derived
      outcome-vocabulary buckets
- [x] Implement `classify` to pass
- [x] Implement `bin/audit-session-policy` as the thin CLI wrapper
- [x] Audit the ~100-140 internals-coupled tests in the old `tests/test_analyze_bash_command.py`: for each cluster,
      record whether it is already covered by the new suite, port it as a new public-API test, or record it
      obsolete-by-design with reasoning — no silent drops
- [x] Resolve `TestExtractArgTextWithVars` (`:4192-4272`): re-check leaf 6's landed shape for a public
      argument-text-with-variables capability; port to public API or record as a genuine follow-up gap
- [x] Resolve the duplicate `TestPositionalArgAtIndexFilter` (`:1156` and `:2171`): read both bodies, confirm single
      home for the surviving behavior in `test_matcher.py` or elsewhere
- [x] Add deprecation language to `packages/shfmt-permissions/.claude-plugin/plugin.json` and its
      `.claude-plugin/marketplace.json` entry, pointing at `command-policy` — do this only once
      `cd packages/command-policy/tests && nix-shell --run pytest` is fully green
- [x] Extend `docs/knowledgebase/command-policy-decision-model.md` with the hook-JSON-protocol mapping, the
      `audit-session-policy` tool, and the shfmt-permissions deprecation note
- [x] Update the `## Interface` section below with what ACTUALLY landed (it is written plan-time and predictive; correct
      every prediction it made, and fill in the observed `command-policy` line count for INTEGRATE)
- [x] Update status to completed

## Interface

Corrected against what ACTUALLY landed (implementation completed 2026-09-18). This is the last leaf in the trunk's
stream, so its only downstream reader is the trunk's own INTEGRATE session.

**What this leaf produced:**

- `hook_envelopes.pretooluse_bash_response` / `pretooluse_path_response` — landed exactly as leaf 6 handed off:
  `passthrough` → `None`; every other outcome (including `allow`) → the `hookSpecificOutput.permissionDecision`/
  `permissionDecisionReason` envelope, with a `reason` tuple rendered via `reason_renderer.render` and an
  already-rendered escalation string passed through unchanged. Both delegate to one private `_pretooluse_response` - the
  envelope shape is identical for bash and path decisions.
- `Config.decision_for_path(tool_name, path)` and `lib/path_permission.py` (NEW — did not exist before this leaf; not
  predicted by the plan, which assumed it might already be covered). `PathResolutionContext` gained an injected
  `is_directory_predicate` for directory-rule matching. Never denies - `allow` or `passthrough` only, matching the old
  engine's allow-or-abstain-only path posture.
- Real bodies for all three remaining stub entrypoints: `command-policy-analyze-bash-command`,
  `command-policy-analyze-path`, `audit-session-policy`. No `bin/` entrypoint in `command-policy` is a stub any more.
  Malformed stdin JSON is treated as passthrough on all three (a deliberate deviation from the old engine's "deny with
  'Invalid JSON input'" for the bash hook, for consistency with this package's other entrypoints).
- `lib/session_audit.py`, ported largely unchanged except `classify()` (now calls `Config.decision_for` directly) and
  `is_bypass_wrapped()` (now `Statement.as_sole_invoked_program()`-based). `render()`'s bucket headings were RE-DERIVED,
  not ported 1:1: `deny` is now the primary section (almost everything non-allowed decides `deny` under the deny+hint
  model), `ask`/`passthrough` are reserved for the two escalation paths.
- The full test-migration audit (see Implementation Notes for the complete per-cluster disposition table): all
  COVERED/OBSOLETE-BY-DESIGN clusters confirmed with a named new-suite equivalent; all GENUINE-GAP clusters ported as
  real tests EXCEPT the bundled `timeout`/`nix`/`nix-shell` parsers, which turned out to be a confirmed production bug
  (not merely untested) and were deliberately left unfixed/untested — see below.
- Two production bugs found and fixed while porting the Bug B regression tests: `AllowedCommand._validate_program_ glob`
  now checks field completeness (closes carried-forward finding #1's `KeyError`), and `_entry_matches_program` no longer
  crashes `fnmatch.fnmatch` on a `None` command word.
- Deprecation language on `shfmt-permissions` (`plugin.json` + `marketplace.json`, version bumped to 6.1.3 per the
  version-bump rule) — functional code untouched.
- `docs/knowledgebase/command-policy-decision-model.md` extended with the hook-JSON-protocol mapping, the
  `audit-session-policy` tool, `decision_for_path`, and the deprecation fact.

**Observed `command-policy` line count for INTEGRATE's before/after comparison** (`wc -l`, excluding `tests/`): `lib/`
alone = 4726; `lib/` + `parsers/` = 7894; `lib/` + `parsers/` + `bin/` = **8386**. The old engine's single file,
`analyze-bash-command.py`, is 2334 lines - INTEGRATE's own job is the comparison and the honest verdict on whether the
full-rewrite-over-strangler justification held (this leaf does not judge it, since the comparison is apples-to- oranges:
one old file vs. a whole new package's `lib/`+`parsers/`+`bin/`, and the new package covers strictly more surface,
including the SubagentStart/lint/render hooks and the escalation/migration tooling the old single file never had).

**Contract for INTEGRATE:**

- **The trunk's acceptance bar is the authored decision specification passing, NOT behavioural equality with the old
  engine.** Confirmed met: `cd packages/command-policy/tests && nix-shell --run pytest` is green except the 2
  pre-existing `xargs`-shaped failures from carried-forward finding #4 (unrelated to this leaf, not a regression it
  introduced).
- **`shfmt-permissions` remains fully intact and functional by design**, now carrying an explicit deprecation label.
  INTEGRATE should record whether the old plugin is still installed anywhere, per its own Open Questions - this leaf
  deliberately does not force a cutover.
- **A real, CONFIRMED regression needs a fast follow-up**: the bundled `timeout`/`nix`/`nix-shell` provided parsers are
  incompatible with the new `nestedCommand` filter and always fail closed (verified live, not just read - see
  Implementation Notes and Observed during implementation for the exact reproduction and root cause). This is a
  functional gap in `packages/command-policy` itself, not merely a missing test, and should be prioritized ahead of
  purely cosmetic follow-up work.
- **A possible symlink-escape regression is unverified** (`path_resolution.py` has no `realpath`-equivalent where the
  old engine had one) - see Observed during implementation. Needs its own verification pass before INTEGRATE can close
  the trunk's security posture as equivalent-or-better.

**Open items INTEGRATE must reconcile:**

1. `TestExtractArgTextWithVars`'s HALF 2 (filters matching a placeholder-substituted variable text once
   `onlyTheseVariables` declares it allowed) has no new-engine equivalent and needs its own follow-up improvement to
   decide the intended semantics - see Implementation Notes for the exact mechanism and why it is unexercised, not
   merely under-tested.
2. Leaves `20260915-010959` and `20260915-011123` have NO `## Interface` sections of their own. INTEGRATE reads their
   planning-state prose instead, or back-fills them — the same gap leaf `20260914-213652` flagged for leaf
   `20260914-213321`.
3. The trunk's own `- Status: completed` still needs correcting (leaf `20260914-213652`'s Interface already assigns this
   to INTEGRATE). Its Leaf Stream `done` markings are NOT a defect — see the correction in
   `## Observed during exploration`.
4. Three follow-up improvements are now warranted, in priority order: (a) fix the `timeout`/`nix`/`nix-shell`
   `nestedCommand` incompatibility (confirmed regression), (b) verify and, if confirmed, fix the symlink-escape gap
   (possible security regression), (c) decide the `onlyTheseVariables`+filter semantics from item 1 above (design
   question, not a crash). All three are recorded in this leaf's Implementation Notes / Observed during implementation
   with enough detail to scope a leaf each without re-deriving the diagnosis.
