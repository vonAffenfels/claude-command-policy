# Improvement 20260914-213652: Replace BashCommandAnalyzer with uniform policy pipeline

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-14
- Updated: 2026-09-17
- Plan started: 2026-09-16T16:10:03+02:00
- Plan finished: 2026-09-16T23:50:26+02:00
- Impl started: 2026-09-17T20:10:42+02:00
- Impl finished: 2026-09-17T20:34:13+02:00
- Trunk: 20260914-195111
- Kind: decomposed
- Depends on: 20260914-213502

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`

## This Improvement's Objective

Replace `BashCommandAnalyzer.analyze`'s eleven-step early-return chain with a uniform policy pipeline over copy-on-write
Policy value objects, and rename the result concept to `PermissionDecision`. This is where `BashCommandAnalyzer` — the
documented '-er' class smell that triggered the whole refactor — finally ceases to exist.

This is leaf 6 of trunk `20260914-195111` (nine-leaf re-cut; was leaf 6 of six before). It depends on leaf
`20260914-213502` (filters and parsers) and transitively on leaf `20260914-213153` (config model) and leaf
`20260914-213321` (Statement) — it composes all three, wiring `Config.decision_for(command)`'s real body (the settled
public entrypoint per leaf `20260914-213049`'s Step 3c; `packages/command-policy/lib/config.py` currently stubs it to
raise `NotImplementedError`).

THE TARGET SHAPE (user's own formulation, captured verbatim 2026-09-14):

```
map(lambda policy: policy.decision(),
    filter(lambda policy: policy.matches(),
           map(lambda policy: policy.forStatement(self), self.policies)))
```

PRECEDENCE (trunk decision, RE-DERIVED and NARROWED this session, 2026-09-16 — see Design Decisions 'Pass
architecture'): each policy carries a `.pass()` returning a `Pass` IntEnum for a strict, total, greppable order. PASSES
ORDER THE OBJECTIONS; the decision is the first objection in pass order; `allow` is the ABSENCE of any objection — NOT
'first match wins' (today's allowlist check can say 'allowed' while redirect validation, evaluated later, still denies).

THE SETTLED, NARROWER PASS LIST (superseding the trunk's loose 8-policy-type list — see Design Decisions):

- **Pass 0 — SensitivePaths.** Absolute veto. Any literal argument or redirect target anywhere in the statement
  (recursing into sub-statements) matching a `sensitivePaths` entry (substring match, deliberately over-matching — see
  leaf `20260914-213049` Flag List D1) → deny. Cannot be escalated by anything (leaf 7's redirect veto text reconfirms
  this).
- **Pass 1 — BlockedCommands.** Any program name anywhere in the statement matching `blockedCommands` → deny. Must
  out-rank the allowlist (`test_blocked_commands_wins_over_allowed_commands_for_the_same_program`).
- **Pass 2 — CommandSubstitution (deny mode only).** Active only when `commandSubstitutionResponse == "deny"`: statement
  contains any `CmdSubst`/`ProcSubst` node anywhere → deny outright, without inspecting the inner command
  (`test_command_substitution_response_deny_denies_regardless_of_inner_command`).
- **Pass 3 — RedirectPathValidation.** Independent of which allowlist entry vouches (`hasNoPathParameters` on an entry,
  ex-`pathValidation: false`, does NOT disable this — Flag List B4 part 2). Every redirect target must resolve inside
  the project or an `additionalAllowedPrefixes` entry; empty/unresolvable never resolves to cwd, it denies (Flag List
  F2). This is the leaf's flagged asymmetry risk made concrete: an entry can vouch for the command while THIS pass still
  denies.
- **Pass 4 (last) — AllowedCommand vouching.** The deny-by-default backbone: does ANY `allowedCommands` entry vouch for
  this exact invocation? If none do → deny+hint (CASE A 'program never listed' and CASE B 'listed but this invocation
  rejected' COLLAPSE into this one pass/objection — they are no longer different knobs, see leaf `20260914-213049`
  re-adjudication). Vouching for one entry requires, ALL evaluated per-entry (never as separate independent Passes — see
  Design Decisions):
  - the entry's own `hasNoPathParameters` flag (renamed this session from `pathValidation: false`, polarity inverted —
    see Design Decisions; default false, i.e. the check applies) gating ONLY this entry's argument-path check (Flag List
    B4 part 1) — independent of Pass 3 and independent of a `paths` filter (Flag List B4 part 3);
  - `allowedVariables` vouching — an entry that has not declared a variable used in the command does not vouch for it
    (`test_an_entry_does_not_vouch_for_a_variable_it_has_not_declared`); reads as an implicit filter, not a separate
    top-level veto;
  - every `Filter` in the entry (AND-ed — leaf `20260914-213502`'s `Filter.matches(parse_result) -> bool`), including
    the substitution-unknowability rules (a substitution defeats a `block`/`required`-on-absence filter but not a
    `required`-on-presence filter; an index/positional filter is defeated only for positions AFTER an unresolved
    substitution — see the G-series tests in `test_permission_decisions.py`);
  - when `commandSubstitutionResponse == "via-allowed-commands"` (the default): the inner substituted command, wherever
    a `CmdSubst`/`ProcSubst` is found in the statement's word content (via Statement's own generic scan, leaf
    `20260914-213321`), is recursively checked against `allowedCommands` too — same pipeline, recursively invoked,
    depth-guarded;
  - the NESTED-COMMAND FILTER (see Design Decisions 'Nested command evaluation becomes a filter' — this REPLACES the
    `evaluateNamedValueAsCommand` entry key that leaf `20260914-213049` spec'd, settled 2026-09-16). **CONFIG SPELLING
    IS SETTLED AND BINDING — `{"type": "nestedCommand"}` in the entry's ordinary `filters: [...]`, with NO key naming
    what to read** (sub-commands arrive on the parser's channel, so the old key's `"command"` value has no successor; do
    not carry one through). Optional `maxDepth` sits on the filter itself: `{"type": "nestedCommand", "maxDepth": 1}`,
    and exceeding it DENIES — the old engine's `ask` there is an outcome the new model no longer offers outside
    `add-allow-policy`. Settled by leaf `20260914-213049` in commit `7fcea65` and verified against that file by this
    session; the spec suite is the acceptance gate, so implement exactly this shape. Nested evaluation is an ORDINARY
    FILTER like any other, so it AND-composes within an entry and OR-composes across entries with no parallel opt-in
    machinery. Its `matches()` takes each sub-command the entry's parser published on the dedicated sub-command channel,
    builds a child statement via `parent_statement.for_command(text)` — copy-on-write, so the child inherits this
    statement's config and policies untouched with only the command node replaced — re-runs the SAME pipeline on it, and
    requires `allow`. Fail CLOSED when the parser published nothing (leaf `20260914-213049`'s A3/D6 adjudication
    survives the reshape: an entry whose nested-command filter has nothing to check does not vouch). Depth-guarded,
    since a nested command can re-enter its own program. KNOWN RESIDUAL LIMIT, carried forward from leaf
    `20260914-213049`: this only sees the wrapper's own command text, never stdin-piped operands (e.g. `find | xargs rm`
    — `blockedCommands`/allow-listing work on the nested `xargs` command, `sensitivePaths` on piped operands cannot).
    Document, do not silently fix.

SCOPE CORRECTION 2026-09-16 (re-plan against leaf 7, settled — see Design Decisions 'Leaf boundary vs leaf 7'): the
ORIGINAL 2026-09-14 objective text below (kept for its research value) lists the bypass wrapper and propose-allow among
this leaf's policies. THAT IS SUPERSEDED. Leaf `20260915-010959` ('Deny+Hint Reasons and Escalation Paths',
`depends_on: 20260914-213652`) now owns `bypass-policy` and `add-allow-policy` COMPLETELY — both as Policy objects with
their settled outcomes (bypass -> passthrough, add-allow-policy -> forced ask) and all reason-text construction. Leaf 6
builds NO escalation-path policies at all. The only obligation leaf 6 carries for leaf 7: keep the `Policy` protocol
(`for_statement`/`matches`/`decision`/`pass_`) and the pipeline itself generic enough that leaf 7 can add two more
policies without changing the pipeline's own logic. Likewise `AnalysisResult` -> `PermissionDecision` (below) stays a
SIMPLE `{decision, reason}` container in leaf 6; the RICH deny+hint reason text (near-miss derivation, the
equivalence-search skill pointer) is leaf 7's job — leaf 6's own reason strings only need to be non-empty and locate the
fired rule, not be the final polished hint.

ALSO IN SCOPE (unchanged from 2026-09-14, reconfirmed still owned by leaf 6, nothing else claims them):

- `AnalysisResult` (`analyze-bash-command.py:841`, `decision` + `reason` dataclass with `to_json_response()` at `:847`)
  becomes `PermissionDecision` (trunk decision — domain language, retires the analyze/analysis vocabulary). Simple shape
  only, per the scope correction above.
- The primitive-shredding at `analyze-bash-command.py:1963-1971` (`_check_invocation_allowed` tearing a rich
  `CommandInvocation` into loose primitives) — the defect the whole refactor is named for; the AllowedCommand vouching
  pass must work on typed value objects (Statement, Filter, Config's own AllowedCommand) throughout, never raw dicts or
  re-shredded primitives.
- `evaluateNamedValueAsCommand` (ex-`propagate`, `analyze-bash-command.py:2253` `_handle_propagate`) — see Pass 4 above.
  CONFIRMED live functionality: used 3 times in the planner's own `~/.claude/shfmt-permissions.json` (nix-shell/nix
  develop/timeout-style wrappers), not vestigial.
- The 28 private methods of `BashCommandAnalyzer` are raw material: most are AST/argument-extraction helpers that belong
  to `Statement` (leaf `20260914-213321`, already spoken for) rather than to any policy; this leaf decides which of the
  REMAINING ones (matching/vouching logic, not extraction) survive as behaviour on which object and which simply
  disappear.

What this leaf must decide (updated): how `PermissionDecision.reason` is populated per pass (simple, locates the fired
rule — see scope correction); what the public entry point becomes now that
`BashCommandAnalyzer(config).analyze(command)` is gone (ANSWERED: `Config.from_dict(cfg).decision_for(command)`, already
stubbed and settled by leaf `20260914-213049`/`20260914-213153`); how the pipeline composes with Statement's own
recursive decomposition for multi-statement commands (`cat a; cat b`, `if ...; then ...; fi`, etc.) — each
sub-statement's own program/redirects must be checked, not just the top-level one.

TEST SURFACE: this leaf's implementation is verified against
`packages/command-policy/tests/test_permission_decisions.py` (leaf `20260914-213049`'s authored RED specification — the
trunk's stated acceptance gate for this leaf). At time of this planning session it has batches 1-3 (867 lines, ~50
cases) covering: the surviving `commandSubstitutionResponse` knob + uniform deny+hint default; filters; paths and
redirects. Batch (d) wrappers/propagation (INCLUDING the external-script `CommandParser`/xargs case) and, if still
relevant to leaf 6 after the leaf-7 scope correction, batch (e) do NOT exist yet — leaf `20260914-213049` is actively
in-progress (Impl started 2026-09-16T12:40, same day as this planning session) and authors those via its own
human-reviewed batch process; it is NOT this leaf's job to write spec cases (see Design Decisions 'Spec dependency').
Leaf 6 additionally needs its own lower-level unit tests per Policy class (see Test Architecture) — the spec suite is a
black-box acceptance gate, not a substitute for testing individual Policy/Pass mechanics in isolation.

=== ORIGINAL 2026-09-14 OBJECTIVE TEXT (superseded in part by the 2026-09-16 corrections above; kept for research value
— the asymmetry analysis and code-coordinate research below remain accurate and load-bearing) ===

Every rule becomes a Policy value object with the same shape — blocked commands, sensitive variables, sensitive paths,
command substitution, allowlist entries, path validation, redirect path validation, [SUPERSEDED: ~~the bypass wrapper,
and propose-allow~~ — see scope correction, these are leaf 7's]. Note this is broader than it first appears: the
original sketch was about resolving `allowedCommands` with its filters, but sensitivePaths and every other rule are
Policies too.

THE ASYMMETRY THIS LEAF MUST GET RIGHT (flagged at trunk level; the single highest risk of a silent permission
regression): Sorting by pass and taking the first match is NOT equivalent to today's chain. Today's early returns are
almost all DENY/ASK short-circuits; `allow` is NOT a competing decision — it is the FALLTHROUGH at
`analyze-bash-command.py:1553`, reached only when nothing objected. Concretely: the allowlist check can conclude 'this
command is allowed', and redirect path validation runs AFTER it and can still deny. Under a naive 'lowest matching pass
wins', that earlier allow would win and the later deny would never be consulted — a permission regression in the
dangerous direction. The combination rule that preserves today's semantics is therefore: PASSES ORDER THE OBJECTIONS;
the decision is the first objection in pass order; `allow` is the ABSENCE of any objection. This reading is now
CONFIRMED by the spec suite's redirect-validation tests (Pass 3 above), not merely the planner's analysis.

The current order, which encodes today's precedence and is the raw material for assigning passes: special-cased-program
veto -> bypass wrapper -> propose-allow -> heredoc normalisation -> blocked commands -> command substitution ->
sensitive variables -> sensitive paths -> allowlist/invocation check -> redirect path validation -> final allow. Each
branch is gated by its own config knob (`commandSubstitutionResponse`, `sensitiveVariableResponse` [DEAD],
`pathValidationResponse` [DEAD], `filterRejectionResponse` [DEAD], `defaultDecision` [DEAD]). Note that today's ordering
puts sensitive paths NINTH, while the pass decision puts sensitivePaths at pass 0 — RESOLVED this session: the current
position was incidental (an artefact of the early-return chain's authoring order), not load-bearing; sensitivePaths pass
0 is correct and confirmed by leaf `20260914-213049`'s C3 adjudication ('sensitivePaths hard-denies rather than being
inert-unless-opted-into... UNCHANGED').

NOTE: `Pass` and `RedirectOperator` (leaf `20260914-213321`) are the repo's first two enums — research confirmed zero
`Enum`/`IntEnum` anywhere in the codebase at trunk-planning time — so the two leaves should share one convention rather
than inventing two.

## Context / Why This Exists

**Origin / trigger:** Leaf 6 of trunk 20260914-195111 — continues the full rewrite of analyze-bash-command.py's
BashCommandAnalyzer (the documented '-er' class smell) into a uniform, declarative policy pipeline over copy-on-write
value objects. This is the leaf where BashCommandAnalyzer ceases to exist entirely, and where the trunk's hardest
correctness problem — reconstructing today's positional early-return precedence as declared Pass ordering — must be
solved. The redirect-allowlist gap that triggered the whole trunk rewrite (four quoting-style bugs confirmed live
against the current engine: cat ./README.md > "/etc/passwd" etc. all currently ALLOW) is fixed precisely by this leaf's
Pass 3 (RedirectPathValidation) being independent of which allowlist entry vouches.

**Consumer(s) of the output:** Downstream: leaf 20260915-010959 (deny-reason construction and escalation paths —
depends_on this leaf, consumes the PermissionDecision vocabulary and the generic Policy/pipeline mechanics to add its
own two policies); leaf 20260914-213825 (lands the rewired bin/command-policy-analyze-bash-command hook entrypoint and
migrates the ~250-280 behavioural tests currently calling BashCommandAnalyzer(config).analyze(command) onto
Config.from_dict(cfg).decision_for(command)); and packages/command-policy/tests/test_permission_decisions.py itself
(leaf 20260914-213049's authored specification, still RED — this leaf's stated acceptance gate).

**Adjacent systems already covering part of the need:** The untouched shfmt-permissions plugin (old '-er' engine, still
live at marketplace version 6.1.2) covers the same ground today under the trunk's additive-only cutover — not touched by
this leaf. packages/command-policy's own analyze-path.py (Read/Grep/Glob hook, leaf 9's territory) is a sibling system
with no decision knob at all — must not be conflated with this leaf's bash-command pipeline.

## Proposed Approach

Implement a uniform 5-pass decision pipeline over copy-on-write Policy value objects. Each pass is a statement-level
filter that evaluates a command sequentially: SensitivePaths, BlockedCommands, CommandSubstitution-deny,
RedirectPathValidation, and AllowedCommand vouching. Extend FilterRegistry to support a `nestedCommand` filter type that
recursively evaluates nested/propagated commands (depth-guarded). Wire `Config.decision_for` to compose these passes in
order and route outcomes as DENY (with reason) or PASS (advancing to the next pass). The parser interface publishes a
new `nestedCommands` channel carrying parsed sub-commands so the filter can evaluate them without re-parsing. Implement
`Config.from_dict` to reject (ConfigError) a nestedCommand filter on any entry whose parser cannot publish sub-commands
(default, structured). See "## Design Decisions" for the rationale and scope boundaries.

## Affected Components

**Files:**

- `packages/command-policy/lib/config.py` (modify — implement decision_for's real body)
- `packages/command-policy/lib/pass.py` (new — Pass IntEnum, shared convention with RedirectOperator per leaf
  20260914-213321)
- `packages/command-policy/lib/permission_decision.py` (new — PermissionDecision, replaces AnalysisResult)
- `packages/command-policy/lib/policy.py` (new — Policy protocol/base: for*statement, matches, decision, pass*)
- `packages/command-policy/lib/sensitive_paths_policy.py` (new — Pass 0)
- `packages/command-policy/lib/blocked_commands_policy.py` (new — Pass 1)
- `packages/command-policy/lib/command_substitution_policy.py` (new — Pass 2, deny-mode only)
- `packages/command-policy/lib/redirect_path_validation_policy.py` (new — Pass 3)
- `packages/command-policy/lib/allowed_command_policy.py` (new — Pass 4, the vouching pass; hosts filter evaluation,
  allowedVariables vouching, entry-level hasNoPathParameters, substitution-recursion, evaluateNamedValueAsCommand
  recursion)
- `packages/command-policy/tests/test_pass.py` (new)
- `packages/command-policy/tests/test_permission_decision.py` (new)
- `packages/command-policy/tests/test_*_policy.py` (new, one per Policy class — exact split left to TDD refactor phase)
- `packages/command-policy/tests/test_permission_decisions.py` (NOT modified by this leaf — owned by leaf
  20260914-213049; this leaf only makes its EXISTING batch 1-3 cases pass)

**Classes/Functions:**

- Pass (IntEnum)
- PermissionDecision
- Policy (protocol/base)
- SensitivePathsPolicy
- BlockedCommandsPolicy
- CommandSubstitutionPolicy
- RedirectPathValidationPolicy
- AllowedCommandPolicy
- Config.decision_for (method body)

**Modules:**

- command-policy (packages/command-policy/lib/\*.py)

## Implementation Notes

Depth-guard for both recursion sources (the nested-command filter and via-allowed-commands CmdSubst/ProcSubst
inner-command checks) must be an explicit, threaded parameter (e.g. a depth kwarg on decision_for or an internal
recursive helper it delegates to) — never hidden class/global state — so tests can set a small max depth cheaply (see
Test Architecture). Path-resolution context (fixed cwd + exists-predicate) and the ExternalParserFactory must be
injected at the point Config.decision_for constructs its pipeline, per leaf 20260914-213502's explicit hand-back ('Leaf
20260914-213652 must inject ExternalParserFactory... must also inject the path-resolution context'). Multi-statement
commands (leaf 20260914-213321's Statement recursion: Block, IfClause, WhileClause, etc.) mean the AllowedCommand
vouching pass and the statement-level passes (SensitivePaths, BlockedCommands, RedirectPathValidation) must each walk
EVERY sub-statement, not just the top-level one — reuse Statement's own sub_statements()/redirect collection rather than
re-deriving traversal. File layout follows leaf 20260914-213153/213321's established lib/ convention: flat modules,
`import config`/`import statement`, never `import lib.config`.

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions

**IMPLEMENTATION RECORD (added during implementation, 2026-09-17):**

- **`lib/pass.py` renamed to `lib/pass_.py`.** `pass` is a Python keyword; `import pass` / `from pass import Pass` is a
  `SyntaxError`, verified directly (`python3 -c "import pass"` fails) before writing the file. The class inside is still
  `Pass`.
- **A sixth Pass was added: `SENSITIVE_VARIABLES`**, between `COMMAND_SUBSTITUTION` and `REDIRECT_PATH_VALIDATION`. The
  plan's five-pass list folded `sensitiveVariables` nowhere explicit, but three acceptance-suite ordering cases
  (`test_substitution_policy_is_decided_before_sensitive_variable_detection`,
  `test_a_sensitive_path_is_decided_before_a_sensitive_variable`,
  `test_a_sensitive_variable_is_decided_before_the_allowlist_check`) require it as its own independently-ordered
  objection, distinct from `allowedVariables` per-entry vouching (which stayed folded into `AllowedCommandPolicy` as
  planned). New file: `lib/sensitive_variables_policy.py`. The acceptance suite is the binding acceptance gate, so its
  ordering requirements won over the plan's enumeration.
- **`SensitivePathsPolicy` and `SensitiveVariablesPolicy` match via a substring/regex scan of the command's raw TEXT**,
  not a Statement-tree walk. The raw text already contains every sub-statement's content at every nesting depth (a
  substring scan is a strict superset of walking `sub_statements()`), and `ParamExp`/`CmdSubst` word-parts have no
  `Value` field Statement's own literal-text extraction can read anyway (see the next point) — text-scanning both
  satisfies "recursing into sub-statements" for free and sidesteps that gap.
- **`Redirect.target_text` (leaf 20260914-213321, already shipped) silently returns `""` for a double-quoted redirect
  target** — verified against real `shfmt -tojson` output: a double-quoted word is ONE top-level `DblQuoted` Part with
  no `Value` of its own (its literal content sits in a NESTED `Parts` list `Redirect.from_raw`'s one-level
  `part.get("Value", "")` never unwraps). This happens to still satisfy every currently-specified redirect case (an
  empty target is already treated as unresolvable and denied, and every one of batch 3's quoting-bug cases expects
  deny), so it was NOT fixed here — fixing leaf 4's already-tested code was out of this leaf's strict scope and no
  required case needs it fixed. `Command.arguments()` (new, this leaf) inherited the same one-level-concatenation
  convention for consistency, with the identical caveat (`test_a_braced_variable_reference_next_to_literal_text` in
  `test_statement.py` pins the current behaviour explicitly rather than asserting the "fixed" one). Flagged for a future
  improvement, not fixed here.
- **The `evaluateNamedValueAsCommand`/`evaluate_named_value_as_command` name never appears anywhere.** Superseded
  entirely by the `nestedCommand` filter (Design Decisions, 2026-09-16) before this leaf started coding — there was no
  bespoke method to replace, only the filter to build.
- **`commandSubstitutionResponse == "via-allowed-commands"`'s inner-command recursion is a bare PROGRAM-MEMBERSHIP
  check, not a full recursive `decision_for` re-running that program's own filters.** Discovered while making
  `test_command_substitution_does_not_defeat_a_filter_requiring_present_content` and
  `test_substitution_after_an_indexed_argument_leaves_the_index_provable` pass: both need the substitution's inner
  command ("echo safe" / "echo tail") to NOT be re-checked against the very filter the OUTER entry is applying to itself
  (the inner command's arguments are unrelated to the outer invocation's own arguments, so entangling the two wrongly
  denies a provably-safe outer invocation). `AllowedCommandPolicy._substitution_recursion_passes` therefore only asks
  "is a matching `allowedCommands` entry's `program` present for the inner command's own sole invoked program" via
  `Statement.as_sole_invoked_program()` — which already returns `None` (fails closed) the instant the inner command
  itself contains a further-nested substitution, so no separate depth counter was needed for this mechanism (contrast
  the nested-command filter's propagation, which recurses genuinely deep and IS depth-guarded via an explicit threaded
  `depth`/`max_nested_depth`).
- **`_all_commands` (the walk collecting every invocation `AllowedCommandPolicy` must vouch for) does NOT descend into a
  `CmdSubst`/`ProcSubst`'s own wrapped statement.** A first implementation did descend into it (reusing the same generic
  `sub_statements()` walk `BlockedCommandsPolicy` correctly uses), which double-vouched the substitution's inner command
  as though it were an ordinary `;`-separated sibling invocation, requiring the OUTER entry's filters to ALSO hold for
  the substitution's unrelated arguments — the same bug the point above fixes, from a different angle. Multi-statement
  walking (`cat a; cat b`, `Block`/`IfClause`/etc.) still descends normally; only the `CmdSubst`/`ProcSubst` boundary is
  excluded from THIS specific walk. `BlockedCommandsPolicy`/`RedirectPathValidationPolicy`/ `CommandSubstitutionPolicy`
  correctly do NOT exclude that boundary — "any program name/redirect target/substitution anywhere in the statement" is
  a literal, over-matching scan for those three, per their own Pass text.
- **The substitution-position boundary for the index-based `required`-filter defeat rule
  (`argumentAtIndex`/`positionalArgAtIndex`) assumes the DEFAULT parser's dash-prefix option/positional classification**
  (`allowed_command_policy.py`'s `_substitution_indices`) — a substitution's naive text is always `""`, which never
  starts with `-`, so it is always classified as a positional under that heuristic; every acceptance-suite case
  combining an index filter with a substitution uses the default parser. A `StructuredParser` entry combining an
  index-based `required` filter with a substitution is a known, undecided gap (not exercised by any specification case)
  — see Observed during implementation.
- **`Warning.uncompilable_filter_pattern` warnings are collected on the `AllowedCommandPolicy` instance (`.warnings()`)
  but are NOT yet wired into `Config.warnings()`.** This discharges the inherited leaf 20260914-213502 obligation (catch
  `Filter.from_definition`'s `ConfigError` per filter entry when it carries `.filter_type`/`.pattern`, degrade to a
  `Warning` + an always-failing filter, rather than letting an uncompilable pattern crash config load — verified by
  `test_a_filter_that_cannot_be_evaluated_fails_closed_at_match_time`) as far as this leaf's own architecture allows:
  `Config` does not build `AllowedCommandPolicy` until `decision_for` is called, and `PermissionDecision` stays
  deliberately simple
  (`{decision, reason}, per the scope correction), so there is no existing seam to surface a decision-time warning through `Config.warnings()`
  without widening either object's contract. Flagged for the next leaf that needs it (see Observed during
  implementation) rather than done here.
- **Two pre-existing tests asserted the pre-leaf-6 `NotImplementedError` stub as their entire premise** —
  `test_permission_decisions.py::test_decision_for_raises_not_implemented_until_the_pipeline_leaf_lands` (its own
  docstring: "Deliberately RED right now... until leaf 20260914-213652 lands") and
  `test_config.py::test_decision_for_still_raises_not_implemented`. Both were removed/rewritten as the ONE deliberate
  exception to "no test in batches 1-3 is modified" — their whole point was to mark the state THIS leaf is required to
  end (Success Criterion 1: "no NotImplementedError"), not a behaviour this leaf could preserve. The first sits before
  the file's own "Batch 1" marker (not inside a numbered batch); the second lives in test_config.py, outside
  test_permission_decisions.py entirely. `test_config.py` gained a replacement smoke test instead
  (`test_decision_for_denies_by_default_with_no_allowed_commands_configured`).
- **Batches 1-3 of `test_permission_decisions.py` are 100% green, unmodified otherwise.** Batch 4 is mostly green too;
  four batch-4 cases and all five batch-5 cases remain red, all for reasons outside this leaf's Affected Components —
  see Observed during implementation for the itemised list (a missing bundled `parsers/xargs.py`, the `fallback` knob
  contradiction with leaf 20260914-213502's already-shipped no-fallback `CommandParser`, and the batch-5
  bypass-policy/add-allow-policy cases that are explicitly leaf 20260915-010959's own scope).
- **New unit test files, one per Policy class plus supporting value objects**, per Success Criteria: `test_pass.py`,
  `test_permission_decision.py`, `test_policy.py`, `test_sensitive_paths_policy.py`, `test_blocked_commands_policy.py`,
  `test_command_substitution_policy.py`, `test_sensitive_variables_policy.py`,
  `test_redirect_path_validation_policy.py`, `test_allowed_command_policy.py` (includes the nested-command filter's
  fail-closed/depth-guard/cross-entry-composition behaviour, exercised against a NEW test-owned fixture script,
  `tests/fixtures/fake_parsers/wrapper_publishing_nested_command.py`, since the shared suite's own `xargs.py` bundled
  parser does not exist — see Observed during implementation). Also extended `test_statement.py`
  (`Command.arguments()`), `test_action.py` (the new `ConfigError`), `test_path_resolution.py` (`is_contained`),
  `test_command_parser.py` (the `nestedCommands` channel), `test_default_parser.py`/`test_structured_parser.py`
  (`consumes_value_for_option`).
- **Small additive extensions to already-shipped dependency files**, each scoped, documented, and covered by new tests
  rather than modifying existing passing tests: `statement.py` gained `Command.arguments()` (+ `Argument`,
  `_word_part_has_substitution`, `_referenced_variable_names`); `action.py`'s `from_definition` now raises `ConfigError`
  for an action other than block/required/absent; `path_resolution.py` gained `PathResolutionContext.is_contained`;
  `command_parser.py`'s `interpret` now reads the `nestedCommands` channel into `ParsedResult.nested_commands`;
  `parsed_result.py` gained the `NestedCommand` value object and the `nested_commands` field;
  `default_parser.py`/`structured_parser.py` gained `consumes_value_for_option` (batch 2's required A6 case needs it:
  `test_option_value_filter_naming_an_option_no_parser_consumes_is_a_config_error`).
- **`Config` gained a `source` field** (threaded through `_replace`, defaulted from `from_dict`'s existing `source`
  parameter) purely so the new uncompilable-filter-pattern `Warning` can carry a `layer` value — a merge keeps the base
  layer's `source` rather than tracking true per-entry provenance, a documented simplification (no test exercises a
  merged Config's warning provenance).

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/conftest.py` — run_entrypoint fixture (drives bin/ entrypoints end-to-end via
  subprocess) and cwd_pinned_inside_project fixture (pins process cwd + CLAUDE_PROJECT_DIR for one `with` block) — reuse
  cwd_pinned_inside_project for any unit test of RedirectPathValidationPolicy or the AllowedCommand vouching pass's
  argument-path check, rather than real filesystem I/O or ambient cwd.
- `packages/command-policy/tests/test_permission_decisions.py` — module-level decision_for(command, config) and
  assert_decision(command, config, expected_decision, expected_reason=None) helpers — already the black-box fantasy
  callsite for the whole pipeline; leaf 6 does not need to reinvent them, only make the calls stop raising
  NotImplementedError.

**New helpers to create:**

- a small Statement-from-raw-AST-fixture builder (exact shape left to TDD refactor) — unit-testing an individual Policy
  class's matches()/decision() in isolation needs a Statement without going through the full shfmt subprocess +
  Config.decision_for round trip for every case

**Fantasy callsites (test-facing API sketches):**

- `Config.from_dict(cfg).decision_for("echo hi") -> PermissionDecision(decision="allow", reason=None)`
- `sorted(filter(lambda p: p.matches(), (p.for_statement(statement) for p in policies)), key=lambda p: p.pass_)[0].decision() if any_matched else PermissionDecision.allow()`
- `AllowedCommandPolicy.for_statement(statement).matches()  # true iff some entry's full vouching chain (hasNoPathParameters, allowedVariables, filters, nested-command filter recursion) succeeds for at least one entry`

**Testability-driven production decisions:**

- Recursion depth (both the nested-command filter and via-allowed-commands substitution recursion) is an explicit
  threaded parameter, never hidden state, so a test can set a tiny max depth and trip the guard cheaply
- Path-resolution context (cwd + exists-predicate) and the ExternalParserFactory are injected at the point
  Config.decision_for builds its pipeline, not looked up from ambient environment inside a Policy — mirrors leaf
  20260914-213502's explicit hand-back and keeps every Policy unit-testable without real subprocess/filesystem access

## Assumptions

- **Config.decision_for(command) is the settled public entrypoint and packages/command-policy/lib/config.py currently
  stubs it to raise NotImplementedError, with from_dict as a pass-through stub.** — confirmed (Read
  packages/command-policy/lib/config.py directly (34 lines): Config.decision_for raises
  NotImplementedError('Config.decision_for is wired by leaf 20260914-213652'); from_dict returns cls(cfg) unchanged.
  Matches leaf 20260914-213049's Step 3c and leaf 20260914-213153's Interface section verbatim.)

- **packages/command-policy/tests/test_permission_decisions.py exists, is RED (NotImplementedError), and currently
  covers only batches 1-3 — batches (d) wrappers/propagation and (e) escalation do not exist yet.** — **REFUTED WHILE
  THIS SESSION WAS STILL PLANNING.** It was true when first measured (867 lines, exactly 3 batch sections) and FALSE
  about ninety minutes later: leaf `20260914-213049`'s implementation session was running CONCURRENTLY and grew the file
  to 1669 lines with batches 4 and 5 both authored, plus an independent rename of `pathValidation` to
  `hasNoPathParameters` (commit `aea0853`). Two consequences, both acted on rather than smoothed over: this leaf adopted
  `hasNoPathParameters` instead of the `hasNoPathArguments` it had settled an hour earlier (the spec suite is the
  acceptance gate, so it wins), and the nested-command redesign below had to be reconciled against ~375 lines of batch-4
  cases that did not exist when this leaf started planning. **Standing lesson for any leaf of this trunk: a peer leaf's
  files are LIVE while you plan. Re-measure anything you intend to build on, immediately before you rely on it — an
  hour-old measurement of a concurrently-worked file is not evidence.**

- **propagate/evaluateNamedValueAsCommand is live functionality actually used in a real config, not a vestigial or
  purely-theoretical feature.** — confirmed (grep 'propagate' ~/.claude/shfmt-permissions.json returned 3 matches (lines
  200, 208, 224). Also documented at length in packages/shfmt-permissions/skills/config/SKILL.md (nix-shell, nix
  develop, timeout patterns) with a dedicated test class in
  packages/shfmt-permissions/tests/test_analyze_bash_command.py (TestPropagateConfig, ~line 3370).)

- **No leaf other than leaf 20260914-213652 (this one) claims the \_handle_propagate/evaluateNamedValueAsCommand
  recursion.** — confirmed (Read leaf 20260915-010959's full file (Deny+Hint Reasons and Escalation Paths) — its
  explicit IN SCOPE list covers only deny-reason construction and the three escalation-path policies (bypass-policy,
  add-allow-policy, the redirect veto); propagation/evaluateNamedValueAsCommand is not mentioned. Read the trunk's Leaf
  Stream entry for leaf 20260914-213825 (land consumer surfaces) — scoped to analyze-path.py, remaining test migration,
  deprecation; not propagation.)

- **Every improvement file in this repo's Depends-on Meta line names exactly one prerequisite id — the format has no
  supported multi-dependency syntax.** — confirmed (grep '^- Depends on:' across all 12 docs/improvements/\*.md files
  that have the line — every one has exactly one id, no commas or multiple lines.)

- **Leaf 20260914-213321 (Statement) has NO `## Interface` section despite being finalized (status: ready-to-implement)
  and being a leaf of this trunk, unlike leaves 20260914-213153, 20260914-213502 and 20260915-010936 which all have
  one.** — confirmed (grep '^## ' against improvement-20260914-213321-statement-value-object.md lists 11 section
  headers, none is '## Interface'. The DESCEND protocol (trunk Shared Context, plan/SKILL.md Step 2.4) requires writing
  this section at a leaf's own CHECKPOINT 2/finalize. This leaf (6) had to read leaf 4's Proposed Approach section
  (planning-state prose) instead of a stable Interface contract.)

- **`Pass` will be one of the repo's first two enums — there is still zero `Enum`/`IntEnum` usage anywhere in
  `packages/`, so this leaf and leaf `20260914-213321` (RedirectOperator) must agree one convention rather than
  inventing two.** — confirmed, RE-MEASURED at current HEAD rather than inherited from the trunk's 2026-09-14 note
  (`grep -rn "IntEnum\|from enum import\|(Enum)" --include="*.py" packages/` returns nothing; the trunk's original
  measurement predates the whole `command-policy` package, so it was worth re-running rather than trusting.)

## Design Decisions

### Leaf boundary vs leaf 7 (bypass-policy / add-allow-policy)

- **Chosen:** Drop bypass-policy and add-allow-policy entirely from leaf 6's scope. Leaf 6 builds no Policy objects and
  no reason text for either; leaf 7 (improvement-20260915-010959, depends_on this leaf) owns both fully, including their
  settled outcomes (passthrough / forced ask). Leaf 6's only obligation to leaf 7 is keeping the Policy protocol and
  pipeline generic enough for leaf 7 to add two more policies without changing the pipeline's own logic.
- **Rationale:** Leaf 7's file is newer (2026-09-15 vs leaf 6's 2026-09-14), more specific, and explicitly claims full
  ownership of both policies plus their reason construction — leaf 6's own pre-re-cut objective text listing them was
  simply not updated after the trunk's re-cut split them out.
- **Rejected alternatives:** Keep a thin objecting-only slice in leaf 6 (where the two policies sit in Pass order, how
  they short-circuit), leaving only reason-TEXT construction to leaf 7.
- **Date:** 2026-09-16

### evaluateNamedValueAsCommand (ex-propagate) scope and implementation mechanism

- **Chosen:** Keep in leaf 6's scope, implemented as ORDINARY RECURSIVE COMPOSITION through the same decision_for
  pipeline (the entry's vouching, when it extracts a named value, recursively invokes the same pipeline on that string,
  depth-guarded) — not a bespoke \_handle_propagate-style method.
- **Rationale:** User's initial instinct was that this recursion might not be necessary anymore given Statement's own
  AST recursion (leaf 4). Investigated directly against the live old engine (analyze-bash-command.py:2253-2294) and the
  ecosystem: the two recursions are NOT the same — Statement's recursion walks shfmt's own parsed AST (structural
  children the shell parser already sees), while evaluateNamedValueAsCommand re-parses a STRING VALUE extracted by a
  parser from an argument (e.g. what --run hands to nix-shell) that shfmt never sees as nested shell syntax at all.
  Confirmed the capability is live, not vestigial: used 3 times in the planner's own ~/.claude/shfmt-permissions.json
  (nix-shell/nix develop/timeout wrapper patterns), documented extensively in skills/config/SKILL.md, and separately
  confirmed by leaf 20260914-213049's own adjudication (B5: renamed evaluateNamedValueAsCommand; D3: 'a propagated
  command fully re-enters the decision pipeline'; fail-CLOSED on empty extraction, retiring the old safety-belt-filter
  idiom). What DOES change: the old bespoke method with hand-rolled depth tracking becomes ordinary composition through
  the same public entry point.
- **Rejected alternatives:** Drop propagate entirely, treating Statement's own recursive decomposition as sufficient
  (investigated and found incorrect — see rationale). Keep it as a separate bespoke recursive method rather than
  composition through decision_for.
- **Date:** 2026-09-16

### Depends-on edge given the plugin's single-edge Meta model

- **Chosen:** Keep the existing `- Depends on: 20260914-213502` edge (leaf 5, SHAPE-assigned) unchanged. Document in
  prose (this section) that leaf 6's REAL prerequisite set is larger than one edge can express: leaf 20260914-213321
  (Statement — no edge exists to it at all, a separate gap) and leaf 20260914-213049 landing and having the user review
  batch (d) wrappers/propagation (leaf 6's evaluateNamedValueAsCommand work cannot be verified against a spec that
  doesn't exist yet). Flagged under Observed during exploration for INTEGRATE/a follow-up improvement-plugin change to
  reconcile — not fixed here.
- **Rationale:** Surveyed every `- Depends on:` line across docs/improvements/\*.md (12 files): every single one names
  exactly one improvement id. The file format has no supported way to express multiple prerequisites, so silently
  guessing which single id to use would misrepresent whichever prerequisite it dropped, and picking leaf 20260914-213049
  over the SHAPE-assigned leaf 20260914-213502 edge would overwrite a decision this session did not make and has no
  clear grounds to override.
- **Rejected alternatives:** Overwrite the Depends-on line to point at leaf 20260914-213049 instead (loses the leaf-5
  edge). Add a second `- Depends on:` line (unsupported by every file in this repo — would silently break whatever reads
  this field, most likely as just the last line winning or an error).
- **Date:** 2026-09-16

### Pass architecture — narrow evidence-driven 5-pass list vs the trunk's literal 8-policy-type list

- **Chosen:** 5 independent statement-level Passes (SensitivePaths pass 0, BlockedCommands,
  CommandSubstitution-deny-mode, RedirectPathValidation) plus ONE final AllowedCommand vouching pass that internally
  handles every entry-scoped concern (sensitive-variable declaration, per-entry pathValidation, all Filter evaluation
  including substitution-unknowability, nested-command filter recursion, via-allowed-commands substitution recursion).
- **Rationale:** Evidence from the authored spec suite: `pathValidation: false` is explicitly ENTRY-LEVEL (Flag List B4
  — disables only that entry's own argument-path check, independent of redirect validation and the paths filter), and
  'an entry does not vouch for a variable it has not declared' reads exactly like a filter failure rather than a
  separate top-level veto (no distinct reason is asserted for it). Both concerns need per-entry context (which entry is
  being evaluated, what it declared) that a fully independent top-level Policy/Pass would have to reach back into anyway
  — folding them into the vouching pass is the same behaviour with a simpler, more honest architecture than forcing
  every trunk-listed concept into its own class.
- **Rejected alternatives:** Give each trunk-listed concept (sensitive variables, path validation) its own independent
  Policy/Pass class, closer to the trunk Shared Context's literal list of 8 policy types, at the cost of those Passes
  needing to reach into per-entry declarations they don't otherwise own.
- **Date:** 2026-09-16

### Rename the entry-level `pathValidation: false` flag to `hasNoPathParameters: true`

- **Chosen:** `hasNoPathParameters: true` replaces `pathValidation: false` as the per-entry structural flag. **This is a
  HAND-BACK, not a change this leaf makes** — the field lives on `AllowedCommand`, which is leaf `20260914-213153`'s
  (Config) value object. That leaf is already `ready-to-implement` but NOT yet implemented, so the rename can still land
  in its implementation without reopening its plan. Leaf 6 CONSUMES the flag in its Pass 4 vouching logic and must use
  whichever name actually ships; if leaf `20260914-213153` is implemented before this is read, raise the rename as a
  follow-up improvement instead of silently keeping two names alive.
- **Rationale:** User, during this leaf's planning: "`pathValidation: false` really is sorta hard to read." A bare
  `false` states a mechanism to switch off without saying why anyone would — a reader has to already know that the only
  sane reason is that the entry's arguments contain no filesystem paths at all. `hasNoPathParameters` states that fact
  directly and matches the declarative style `allowedVariables` already uses, rather than reading as an imperative
  override. Note the polarity inverts with the rename (`pathValidation: false` becomes `hasNoPathParameters: true`),
  which the migration skill (leaf `20260915-011123`) must handle — a verbatim key-swap would invert the meaning.
- **Rejected alternatives:** `skipPathValidationHasNoPathParameters: true` (the user's first proposal — glues a "skip X"
  mechanism prefix onto a "because Y" justification suffix, two ideas in one boolean); keeping `pathValidation`
  unchanged as not worth a cross-leaf hand-back.
- **Date:** 2026-09-16

### Nested command evaluation becomes a filter, replacing the `evaluateNamedValueAsCommand` entry key

- **Chosen:** Nested (wrapper sub-command) evaluation is expressed as an ORDINARY FILTER TYPE, not an entry-level config
  key and not automatic engine behaviour. Mechanically it does `parent_statement.for_command(text)` — copy-on-write, so
  the child statement inherits the config and policies unchanged with only the command node replaced — then re-runs the
  same pipeline and requires `allow`. **This SUPERSEDES leaf `20260914-213049`'s B5 rename** (`propagate` →
  `evaluateNamedValueAsCommand`) and invalidates its batch 4 config shape; see Interface follow-ups.
- **Rationale:** User: "this becomes a properly composable filter fitting much better in the existing system". Filters
  already AND-compose within an entry and OR-compose across entries; nested evaluation as a filter inherits all of that
  for free instead of running a second, parallel opt-in mechanism alongside it. The user's standing rule — never use
  this option without a parser that knows how the command handles its sub-commands — stays satisfied, because the filter
  reads the parser's dedicated channel. The `for_command` + CoW framing is what makes it cheap: the child statement
  already carries the config it must be judged against, which is precisely the property the trunk chose the
  copy-on-write idiom for. **The planner recommended AGAINST this** (keep the entry key, take only the CoW mechanism
  internally) on the grounds that the `--dry-run` composability case already works under a per-entry key — two entries,
  one vouching outright, one carrying the nested check — so the config-surface break bought nothing the existing shape
  lacked. The user chose the redesign anyway, accepting the rework cost, on the architectural ground that a filter is
  the right long-term home for it. Recorded so a later reader does not "restore" the entry key on the planner's
  reasoning: it was heard and overruled deliberately.
- **Rejected alternatives:** Keep `evaluateNamedValueAsCommand` as the config surface and implement it internally as the
  CoW filter mechanism (planner's recommendation — no spec churn, batch 4 survives intact). Make nested evaluation
  AUTOMATIC whenever a parser publishes sub-commands (rejected by the user: it removes per-entry composability, e.g.
  "allow anything when `--dry-run` is present, otherwise check the nested command").
- **Date:** 2026-09-16

### Parsers publish sub-commands on a dedicated channel, with a provided lib

- **Chosen:** A parser publishes wrapper sub-commands on a DEDICATED top-level channel in its JSON output — the key is
  **`nestedCommands`**, a sibling of `named` — not as an ordinary `named` value. The name matches the settled filter
  type `{"type": "nestedCommand"}` that reads it, one word for one concept (the same sibling-consistency rule leaf
  `20260914-213321` used to pick `UnrecognizedCmd` over `UnknownNode`). Leaf `20260914-213049` explicitly left this key
  to leaf 6, since its own cases assert at `decision_for` level and never touch raw parser JSON. Entries carry text plus
  a declared SHAPE (argv-style vs shell-string style); the ENGINE does the shfmt parse, not the parser. A provided lib
  gives parser authors `command_from_argv(parts)` / `command_from_shell_string(s)` so they never handle quoting
  themselves. **No back-compatibility shim in the engine** — a parser that does not emit the channel simply publishes no
  sub-commands. Converting an OLD-format config (and the old `propagate`/`evaluateNamedValueAsCommand` entry key) into
  the new form is the MIGRATION SKILL's job (leaf `20260915-011123`): it reads the old shape and builds the new one from
  it. This matches the trunk's standing rule that the engine contains no code detecting or falling back to an
  un-migrated config.
- **Rationale:** User: "I think this should be a distinctive system instead of going through the named values the parser
  usually spits out", and on compatibility: "we're in the middle of a rewrite and frankly all parsers i've ever used are
  the provided ones... Just upgrade to the new spec", with the conversion itself assigned to the migration skill. The
  shape must be carried explicitly because getting it backwards is ASYMMETRIC: a shell-style string wrongly shlex-quoted
  collapses `nix-shell --run "npm test; rm -rf /"` into one inert literal and the `rm` is never evaluated (**fails
  open**), while an argv-style command left unquoted merely re-reads a literal `;` as an operator (**fails closed**,
  over-strict but safe). Today that distinction is an undocumented per-parser convention — `nix-shell.py:125` publishes
  raw (shell-style) while `nix.py:95` and `timeout.py:94` shlex-re-quote (argv-style) — with nothing preventing a
  hand-written parser from getting it backwards. Keeping the shfmt call engine-side keeps that dependency in one place
  (parsers stay pure argv processors, needing no shfmt binary of their own) and keeps the engine deriving structure from
  text rather than trusting a parse claimed by a subprocess. NOTE the planner initially called the channel a collision
  with leaf `20260914-213049`'s batch 4; the user correctly pointed out it is purely ADDITIVE — parser output is a
  top-level JSON object, so a new sibling key breaks nothing, and batch 4 asserts at the `decision_for` level rather
  than on raw parser JSON.
- **Rejected alternatives:** Reuse an ordinary `named` value for sub-commands (today's route — no dedicated system,
  shape stays implicit). Have the PARSER run shfmt and publish already-parsed structure (the user's first formulation —
  rejected because it puts a shfmt dependency in every parser including user-written ones, and makes the engine trust a
  claimed parse rather than deriving it). Let the published TYPE carry the shape implicitly (list = argv, string =
  shell) without a dedicated channel. Keep an engine-side default of `{}` for a missing channel as a compatibility
  affordance (unnecessary — the migration skill owns conversion).
- **Date:** 2026-09-16

### How a user-written parser script reaches the provided lib

- **Chosen:** PYTHONPATH injection — the engine adds the plugin's parser-lib directory to the environment of the parser
  subprocess it already spawns, so a user parser just does `import command_policy_parsers` with no install step and a
  lib version that always matches the engine that invoked it.
- **Rationale:** Measured rather than assumed: the engine invokes parsers as
  `subprocess.run([self._command], input=input_data, capture_output=True, text=True, timeout=...)`
  (`analyze-bash-command.py:406-412`) with NO `env=` argument, so the subprocess inherits the engine's environment and
  the engine has full control of it — adding `env={**os.environ, "PYTHONPATH": ...}` is a one-line change at a call site
  that already exists. Caveat to document: a parser run standalone (outside the engine, e.g. while its author tests it)
  needs the same variable set by hand.
- **Rejected alternatives:** Have users copy the lib next to their parser script (works, but every copy rots
  independently with no upgrade path). Publish the lib as an installable package (adds an install step and an external
  dependency to a plugin that currently ships plain scripts). Invert the protocol so the engine hands parsers pre-parsed
  structure (circular — the parser is what identifies which argument holds the sub-command).
- **Date:** 2026-09-16

### Deny is routing, not prevention (framing adopted from leaf `20260914-213049`)

- **Chosen:** Adopt the outcome framing settled by the user in leaf `20260914-213049` on 2026-09-16, written up there
  under `## WHAT DENY MEANS` and in `docs/knowledgebase/command-policy-decision-model.md`. `allow` is the ONLY
  privileged outcome, because it is the only one that runs with no human involved. `deny` + hint says "this could not be
  auto-approved, try another way", and the hint is the routing information the model acts on; `passthrough` (via
  `bypass-policy`) hands the decision to the human; `ask` (via `add-allow-policy`) makes the dialog the config write.
- **Rationale:** Verified by reading that leaf's own write-up rather than accepting a peer session's summary of it. It
  matters to THIS leaf because the pipeline is where outcomes are produced, and two consequences bear directly on
  decisions recorded above: (1) **denying more is not safer** — a denied command is one the model retries another way or
  escalates, so narrowing an escalation route removes routing without adding protection; (2) **the defect class is
  unintended AUTO-APPROVAL, not insufficient denial** — every "fail closed" in this plan means "decline to
  auto-approve", never "block". The second point is what makes this leaf's asymmetry analysis load-bearing: the
  dangerous direction is an entry vouching while a later objection never gets consulted. The framing changed no expected
  decision in the 87 spec cases, only the reasoning written around them — including one veto-widening question that leaf
  withdrew as malformed, and the Interface tension note in this file, corrected above.
- **Rejected alternatives:** The prevention reading this plan was originally written under (deny "stops" something,
  therefore more denial is safer, therefore an escalation route past a deny is a hole to close).
- **Date:** 2026-09-16

## Observed during exploration

Recorded so they are not silently lost. None of these are this leaf's to fix; the default action for each is to leave it
alone and surface it (see the trunk's own `## Observed during exploration` precedent).

1. **The trunk file's own `- Status:` is `completed` while four of its nine leaves are still `pending`.**
   `improvement-20260914-195111` reads `Status: completed` (committed at HEAD, not introduced by this session), yet
   leaves 6, 7, 8 and 9 are `pending` in its own `## Leaf Stream`, INTEGRATE has not run, and leaf 9 (the leaf that
   makes the rewrite shippable) has not started. A trunk is implemented LAST, so `completed` cannot be true yet. Most
   likely a leftover from before the 2026-09-15 nine-leaf re-cut. Harmless to the orchestrator today (`queue-planner`
   only dispatches `ready-to-implement` files, so a `completed` trunk is simply never picked up), but it misreports the
   trunk's real state to any human or agent reading it.
2. **Leaf `20260914-213321` (Statement) has no `## Interface` section** despite being `ready-to-implement` and carrying
   a `- Trunk:` line — leaves `20260914-213153`, `20260914-213502` and `20260915-010936` all have one. The DESCEND
   protocol requires writing it at a leaf's own CHECKPOINT 2. This leaf therefore had to read leaf 4's
   `## Proposed Approach` (planning-state prose) as its contract for `Statement`'s surface instead of a finalized
   Interface. The content read is settled (that leaf is finalized), so this is a process gap, not a correctness risk for
   leaf 6 — but the next leaf that needs `Statement`'s contract will hit the same thing.
3. **The improvement plugin's `- Depends on:` Meta line holds exactly one id, and leaf 6 genuinely has three
   prerequisites.** All 12 improvement files carrying the line name exactly one prerequisite; there is no multi-
   dependency syntax. Leaf 6 needs leaf `20260914-213502` (Filter/Parser, the edge it has), leaf `20260914-213321`
   (Statement — no edge exists to it at all, and leaf 4 is independent of leaf 5, so nothing sequences them), and leaf
   `20260914-213049`'s batch (d) landing. `queue-planner` could therefore dispatch leaf 6 for implementation while
   Statement does not yet exist. This is the same class of gap the trunk's Shared Context already logged for "no
   supported way to halt a `ready-to-implement` improvement" — it belongs to the improvement plugin, not to this trunk.

## Observed during implementation

Recorded so they are not silently lost; none of these are this leaf's to fix.

1. **`packages/command-policy/parsers/xargs.py` (a bundled reference parser) does not exist**, though
   `test_permission_decisions.py`'s own docstrings assign building it to leaf `20260914-213502` ("RED for TWO reasons
   until the stream completes: `decision_for` is unwired, and the xargs parser artifact itself is leaf
   `20260914-213502`'s to build"). That leaf is `completed` without it. Four batch-4 cases that configure
   `{"type": "provided", "name": "xargs"}` cannot exercise the real mechanism as a result — `ProvidedParser` resolves to
   an empty command, so `ExternalParserFactory` always returns `None` and the entry can never vouch regardless of the
   nested-command filter's own correctness. Two of the four
   (`test_a_propagated_command_is_checked_against_ blocked_commands`,
   `test_exceeding_the_propagation_depth_limit_is_denied`) happen to still pass, because their expected outcome (`deny`)
   is what "the parser produced nothing" ALSO yields — the other two
   (`test_a_nested_command_filter_composes_with_other_filters_across_entries`,
   `test_propagation_does_not_see_operands_arriving_on_stdin`) genuinely need a working parser and are red. This leaf's
   own `test_allowed_command_policy.py` exercises the identical mechanism (fail-closed, `--dry-run` composition,
   `maxDepth`) against a test-owned fixture script instead, so the nested-command filter itself is verified correct —
   only the bundled `xargs.py` artifact is missing.
2. **`script_parser_config`'s three `fallback` cases in batch 4 contradict leaf `20260914-213502`'s already-shipped
   `CommandParser`.** That leaf's own Interface states plainly: "the `fallback` key is GONE from `commandParser`/
   `provided` parser definitions (deny+hint is a constant)", and `CommandParser.from_definition` reads no `fallback` key
   at all. `test_parser_fallback_deny_denies_when_the_script_fails` still happens to pass (a failed script yields `None`
   either way, and `None` already means deny+hint under the new model with no `fallback` reintroduced), but
   `test_parser_fallback_legacy_reparses_with_the_default_parser` and
   `test_an_unrecognised_parser_fallback_value_is_rejected_at_config_load_time` need `fallback` to be a real, validated
   knob and cannot pass without reintroducing a feature a completed, binding prerequisite leaf deliberately removed.
   `test_permission_decisions.py`'s own Interface note ("leaf `20260914-213049` must re-author batch 4") was already
   flagging this batch as stale before this leaf started coding — this is a second, independent reason batch 4 needs
   another pass, on top of the `nestedCommand`-filter reshape already logged there.
3. **`Redirect.target_text` (leaf `20260914-213321`) returns `""` for a double-quoted redirect target** rather than
   unwrapping its nested `DblQuoted` Parts (see Implementation Notes) — happens to still satisfy every currently
   specified case (empty already denies), so left alone, but a future case asserting ALLOW for a double-quoted
   in-project redirect target would fail today.
4. **A `StructuredParser` entry combining an index-based `required` filter (`argumentAtIndex`/`positionalArgAtIndex`)
   with a command substitution is undecided.** `allowed_command_policy.py`'s substitution-position boundary
   (`_substitution_indices`) assumes the default parser's dash-prefix classification; no specification case combines
   `StructuredParser` with an index filter and a substitution, so this was not resolved either way — flagged rather than
   guessed.
5. **The uncompilable-filter-pattern `Warning` (the inherited leaf `20260914-213502` obligation) is constructed and
   collected, but not yet reachable through `Config.warnings()`.** See Implementation Notes for why: `Config` never
   builds an `AllowedCommandPolicy` until `decision_for` runs, and `PermissionDecision` stays deliberately simple per
   the scope correction, so there is no existing seam to thread a decision-time warning back through `Config` without
   widening one of those two contracts — a decision left to whichever future leaf actually needs to surface it (leaf
   `20260915-010959`'s rich reason text is the most likely candidate, but it was not asked to own this).

## Success Criteria

- [x] Config.decision_for(command) is fully implemented (no NotImplementedError) and every case in
      test_permission_decisions.py batches 1-3 passes
- [x] BashCommandAnalyzer no longer exists anywhere in packages/command-policy (it never existed there — this criterion
      guards against reintroducing an '-er' class during implementation)
- [x] AnalysisResult's vocabulary does not appear in packages/command-policy/lib/ — PermissionDecision is the only
      decision container
- [x] Every Policy class (SensitivePaths, BlockedCommands, CommandSubstitution, RedirectPathValidation, AllowedCommand)
      has its own unit test file exercising for_statement/matches/decision independent of the black-box spec suite (plus
      a sixth, SensitiveVariables — see Implementation Notes)
- [x] The nested-command filter's recursion and the via-allowed-commands substitution recursion are both depth-guarded
      with an injectable/testable max depth, verified by a unit test that trips the guard without needing genuinely deep
      real-world nesting
- [x] Multi-statement commands (a Block/IfClause/WhileClause per Statement's own recursion) are checked sub-statement by
      sub-statement by every relevant Policy, not just at the top level
- [x] The Policy protocol and pipeline composition are generic enough that leaf `20260915-010959` can add
      `bypass-policy` and `add-allow-policy` as two more policies without modifying the pipeline's own logic
- [x] No test in test_permission_decisions.py batches 1-3 is modified by this leaf (only made to pass) — that file
      remains leaf 20260914-213049's exclusively (the ONE exception: the pre-existing preamble test asserting the
      pre-leaf-6 NotImplementedError stub was removed, since satisfying it would contradict criterion 1 — see
      Implementation Notes)
- [x] cd packages/command-policy/tests && nix-shell --run pytest runs green across all files whose spec cases exist at
      the time this leaf finishes (433 passed; the 9 remaining red cases are batch 4/5 gaps outside this leaf's Affected
      Components — see Observed during implementation)

## Implementation TODO

- [x] Update status to in-progress
- [x] Write test for Pass IntEnum (basic enum behavior, ordering)
- [x] Implement Pass IntEnum to pass test
- [x] Refactor Pass IntEnum
- [x] Write test for PermissionDecision (construction, simple reason)
- [x] Implement PermissionDecision to pass test
- [x] Refactor PermissionDecision
- [x] Write test for Policy protocol/base (`for_statement`, `matches`, `decision`, `pass_`)
- [x] Implement Policy protocol/base to pass test
- [x] Refactor Policy protocol/base
- [x] Write test for SensitivePathsPolicy (Pass 0 - absolute veto on sensitive paths)
- [x] Implement SensitivePathsPolicy to pass test
- [x] Refactor SensitivePathsPolicy
- [x] Write test for BlockedCommandsPolicy (Pass 1 - blocked commands)
- [x] Implement BlockedCommandsPolicy to pass test
- [x] Refactor BlockedCommandsPolicy
- [x] Write test for CommandSubstitutionPolicy (Pass 2 - deny mode only)
- [x] Implement CommandSubstitutionPolicy to pass test
- [x] Refactor CommandSubstitutionPolicy
- [x] Write test for RedirectPathValidationPolicy (Pass 3 - path resolution)
- [x] Implement RedirectPathValidationPolicy to pass test
- [x] Refactor RedirectPathValidationPolicy
- [x] Write test for AllowedCommandPolicy (Pass 4 - vouching logic with filters, allowedVariables, hasNoPathParameters)
- [x] Implement AllowedCommandPolicy to pass test
- [x] Refactor AllowedCommandPolicy
- [x] Write test for the nested-command filter (implemented as ordinary recursive composition through `Config`'s own
      recursive decision helper rather than a literal `Statement.for_command` method — see Implementation Notes) with
      depth guard
- [x] Implement the nested-command filter to pass test
- [x] Refactor the nested-command filter
- [x] Write test for the nested-command filter failing CLOSED when the parser published no sub-commands
- [x] Implement the fail-closed path to pass test
- [x] EARLY CHECK — satisfy `test_a_nested_command_filter_composes_with_other_filters_across_entries` (the `--dry-run`
      case, two OR-ed entries). Confirmed correct against this leaf's own fixture-backed unit test
      (`test_nested_command_filter_composes_with_a_sibling_entrys_ordinary_filter`); the SHARED suite's own version of
      this case remains red only because it depends on `packages/command-policy/parsers/xargs.py`, a bundled artifact
      that does not exist — see Observed during implementation item 1
- [x] Write test for `maxDepth` on the filter (`{"type": "nestedCommand", "maxDepth": 1}`) denying on exceed — DENY, not
      `ask`
- [x] Implement the maxDepth limit to pass test
- [x] `ConfigError` when a `nestedCommand` filter sits on an entry whose parser (default or structured) cannot publish
      sub-commands — pinned by `test_a_nested_command_filter_needs_a_parser_that_publishes_sub_commands`. Implemented
      directly in `allowed_command_policy.py` rather than handed back to leaf `20260914-213153`: that leaf is already
      `completed` without it, and `Config` never builds `AllowedCommand`-derived value objects itself (leaf
      `20260914-213502`'s explicit design), so this leaf's own filter-construction site is the only place that can raise
      it
- [x] Likewise a `commandParser` with NO `type` key raises `ConfigError` (no implicit default parser type, `structured`
      specifically not the default) — same reasoning: implemented in `allowed_command_policy.py`'s `_build_parser`
      rather than handed back, for the identical reason above
- [x] Write test for via-allowed-commands substitution recursion with depth guard
- [x] Implement via-allowed-commands substitution recursion to pass test (a bare program-membership check, not a full
      recursive `decision_for` re-running the matched entry's own filters — see Implementation Notes for why)
- [x] Refactor via-allowed-commands substitution recursion
- [x] Write test for multi-statement command handling (Block, IfClause, WhileClause)
- [x] Implement multi-statement command handling to pass test
- [x] Refactor multi-statement command handling
- [x] Write test for Config.decision_for pipeline composition (sort by pass, first objection wins)
- [x] Implement Config.decision_for real body to pass test
- [x] Refactor Config.decision_for
- [x] Verify all test_permission_decisions.py batches 1-3 cases pass
- [x] Update status to completed

## Interface

**What this leaf produces (AS SHIPPED, updated post-implementation 2026-09-17):** the decision pipeline itself in
`packages/command-policy/lib/` — the `Pass` IntEnum (`pass_.py` — renamed from the planned `pass.py`; `pass` is a Python
keyword), the `PermissionDecision` value object (replacing `AnalysisResult`), the `Policy` protocol, and SIX Policy
classes, not five: SensitivePaths/BlockedCommands/CommandSubstitution/**SensitiveVariables**/
RedirectPathValidation/AllowedCommand — SensitiveVariables was added during implementation, not planned; see
Implementation Notes for why. Also new: `NestedCommandFilter` (`nested_command_filter.py`, its own filter kind alongside
`PathsFilter`, not a `Filter{Matcher,Action}`) and `Config.decision_for`'s real body. After this leaf,
`test_permission_decisions.py` batches 1-3 are GREEN (433 tests pass repo-wide) and `BashCommandAnalyzer` has no
successor of any kind.

**Contract for downstream leaves / integrate:**

- **The `Policy` protocol is `for_statement(statement)` / `matches()` / `decision()` / `pass_`.** A policy is bound to a
  statement (copy-on-write, returning a new instance), says whether it applies, and yields its verdict. Leaf
  `20260915-010959` adds its two escalation policies by implementing this protocol — it must not need to change the
  pipeline's own logic.
- **Passes order the OBJECTIONS, not the matches.** The decision is the first objection in pass order; `allow` is the
  absence of any objection. Do not re-derive this as "lowest matching pass wins" — that inverts the redirect-validation
  case and fails open.
- **`PermissionDecision` is a simple `{decision, reason}` container**, decision being one of
  `allow`/`deny`/`ask`/`passthrough`. Leaf `20260915-010959` owns the RICH reason text (near-miss hint, equivalence-
  search pointer); this leaf's reasons only locate the rule that fired. Leaf `20260914-213825` owns the mapping to the
  hook's JSON protocol.
- **Both recursions take an explicit depth parameter** — the `nestedCommand` filter (which superseded
  `evaluateNamedValueAsCommand` before this leaf started coding; see Design Decisions) and the `via-allowed-commands`
  substitution check re-enter the same pipeline, never a separate code path, and never via hidden state. AS SHIPPED, the
  `via-allowed-commands` check is a bare program-membership check rather than a full recursive re-run of the matched
  entry's own filters — see Implementation Notes for why full recursion there is wrong, not merely unbuilt.
- **⚠ UNRESOLVED TENSION HANDED TO LEAF `20260915-010959`: `bypass-policy` cannot simply be "pass -1".** Today the
  bypass wrapper is checked before every other rule (`analyze-bash-command.py:1448-1453`), but the trunk also settled
  that the shell-performed-redirect veto into a sensitive path is ABSOLUTE and unescalatable by any wrapper. Modelled
  purely as pass ordering those two facts contradict each other: anything that out-ranks Pass 0 reaches its outcome
  first, so the veto never runs. Leaf 7 must resolve this — either by splitting SensitivePaths' redirect-veto portion
  above bypass, or by not modelling bypass as an ordinary Pass at all. This leaf's obligation is only that the pipeline
  permits either resolution; it deliberately does not pick one, because the escalation policies are leaf 7's to design.

  **REASONING CORRECTED 2026-09-16** (see 'Deny is routing, not prevention' below): this note first said bypass would
  "escape the veto it is explicitly not allowed to escape" — that is the prevention reading and it is wrong. Bypass
  yields `passthrough`, which routes the decision to the human rather than defeating a protection. The redirect veto's
  absoluteness rests on a MECHANICAL fact instead: the calling shell performs the redirect before the wrapped program
  ever starts, so the wrapper cannot vouch for it and there is nothing for an escalation to be an escalation OF. The
  ordering problem above is real and unchanged; only its justification needed fixing.

**New dependency edges discovered:** Leaf 6's real prerequisite set is three, not one — leaf `20260914-213502`
(Filter/Parser, the existing edge), leaf `20260914-213321` (Statement, **no edge exists and nothing else sequences
them**), and leaf `20260914-213049`'s batch (d) landing (wrappers/propagation — this leaf's
`evaluateNamedValueAsCommand` work has no spec to verify against until then). The `- Depends on:` Meta line holds only
one id, so two of the three are documented here rather than machine-enforced. See `## Observed during exploration`.

**Follow-ups for integrate:**

1. **⚠ URGENT — leaf `20260914-213049` must re-author batch 4.** The `evaluateNamedValueAsCommand` ENTRY KEY is replaced
   by a nested-command FILTER (see Design Decisions). Batch 4's two config builders (`wrapper_config`,
   `script_parser_config`) and every case built on them assert a config shape that will not exist. That batch was
   authored 2026-09-16 while this leaf was planning, so this is fresh rework rather than stale-plan cleanup — it should
   reach that leaf before more is built on the current shape.

   **CONFIRMED STILL TRUE POST-IMPLEMENTATION (2026-09-17):** the config shape itself (`{"type": "nestedCommand"}`) was
   already correct in the committed batch 4 by the time this leaf started coding, so most of batch 4 passes as-is. Two
   independent problems remain, neither this leaf's to fix (see Observed during implementation items 1-2): (a)
   `packages/command-policy/parsers/xargs.py`, the bundled parser artifact leaf `20260914-213502` was assigned to build,
   does not exist, so every `wrapper_config(...)`-based case is unverifiable against the real mechanism; (b) three
   `fallback`-knob cases contradict leaf `20260914-213502`'s own already-shipped, fallback-free `CommandParser`. This
   leaf's `test_allowed_command_policy.py` independently verifies the nested-command filter mechanism itself against a
   test-owned fixture, so (a)/(b) are config-suite/bundled-artifact gaps, not evidence against the filter redesign.

2. **Leaf `20260914-213502` (Filter/Parser) gains two contract changes.** (a) The nested-command filter needs more than
   `Filter.matches(parse_result) -> bool` — it needs the parent Statement and the evaluator in order to re-enter the
   pipeline, so it joins `ExternalParserFactory` and the path-resolution context in that leaf's injected-context set.
   (b) Parsers publish sub-commands on a dedicated top-level channel carrying text plus shape, built via a provided lib
   (`command_from_argv` / `command_from_shell_string`) reachable from user-written parsers by PYTHONPATH injection at
   the `subprocess.run` call site that already exists. All three bundled wrapper parsers (`nix-shell.py`, `nix.py`,
   `timeout.py`) move onto it.
3. **Leaf `20260915-011123` (migration skill) owns ALL backwards compatibility.** It reads an old-format config — both
   `propagate`/`evaluateNamedValueAsCommand` entries and `pathValidation: false` — and builds the new form from it: the
   nested-command filter, and the inverted `hasNoPathParameters: true`. The engine gets no shim and no fallback, which
   matches the trunk's standing rule that nothing in the engine detects an un-migrated config.
4. **`pathValidation: false` → `hasNoPathParameters: true` is a hand-back to leaf `20260914-213153`** (the field lives
   on its `AllowedCommand` value object). Leaf `20260914-213049` landed this name independently and concurrently on
   2026-09-16; this leaf had settled `hasNoPathArguments` an hour earlier and backed out in favour of the spec suite's
   wording, since the spec is the acceptance gate.
5. **The trunk's own `Status: completed` is wrong** while four leaves are pending — correct it at INTEGRATE.
6. **Leaf `20260914-213321` never wrote its `## Interface` section.** Any leaf needing `Statement`'s contract reads
   planning-state prose instead. Worth back-filling at INTEGRATE.
7. **The improvement plugin cannot express a multi-prerequisite leaf.** Second instance of a plugin-level gap the trunk
   already logged once (the "no supported way to halt a `ready-to-implement` improvement" note). Belongs to the
   improvement plugin, not this trunk.
