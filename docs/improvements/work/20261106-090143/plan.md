# Improvement 20261106-090143: Filters explain what an invocation must look like

## Meta

- Related Ticket: None
- Status: in-review
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T09:01:49+01:00
- Plan finished: 2026-11-06T10:49:01+01:00
- Impl started: 2026-11-06T11:01:46+01:00
- Impl finished: 2026-11-06T11:08:19+01:00
- Merge target: main

## This Improvement's Objective

Make explain-policy (and the SessionStart/SubagentStart rendering built from the same Config.explain) state, per
allowedCommands entry, what an invocation must look like to be auto-approved, instead of only the filter count, by
having each filter render its own requirement as short prose.

## Context / Why This Exists

`explain-policy` and the SessionStart / SubagentStart hooks all print `Config.explain()`. Today each allowedCommands
entry renders through `AllowedCommand.explain()` (`lib/allowed_command.py:129`) as either
`- {program}: no filters — permits every invocation.` or `- {program}: must pass {n} filter(s).` (counted from the RAW
`filters` definitions). The reader (Claude in the session, and the `find-auto-allowed-command` agent, which reasons ONLY
over this rendered text) learns that a filter exists but not what it demands, so it cannot construct an auto-approved
shape without guessing or escalating. Example from the operator's live config: `git: must pass 1 filter(s).` hides that
only the subcommands `status|log|diff|…|merge` are allowed; `d2: must pass 6 filter(s).` hides six block patterns.

Findings while researching (2026-11-06):

- Every built filter kind ALREADY has an `explain()`: `Filter.explain()` → `Matcher.explain(action)`
  (`lib/matcher.py:33`, e.g. `"parameterRegex block pattern '--force'"`; `OptionPresentMatcher` overrides it),
  `PathsFilter.explain()` and `NestedCommandFilter.explain()`. `InvalidFilter` has none. None of these are called from
  `AllowedCommand.explain()` — they are only exercised by `tests/test_matcher.py`. Likewise `derive_alternative()`
  exists on every filter kind and has no production caller.
- The existing matcher `explain()` wording is a config-schema echo (type name + action + raw pattern), not prose saying
  what the command must do. Index (`argumentAtIndex`/`positionalArgAtIndex`), `namedValue`'s name and `optionValue`'s
  option are not even rendered.
- The entry's `commandParser` is not rendered either, although what a filter sees depends on it (a
  `namedValue subcommand` filter is only meaningful because the `git` provided parser publishes `subcommand`).
- A denial's `FilterRejected` reason (`lib/reason_renderer.py:111`) names only program + filter type ("a namedValue
  filter rejected this invocation") — same information gap at deny time.
- The rendered text is injected into every session's context at SessionStart, so its size is a real cost (the operator's
  config has entries with long regexes, e.g. `list-improvements`, `git`).
- Live example during planning: `python3 <probe>.py` was denied with "python3: a positionalArgAtIndex filter rejected
  this invocation"; the actual rule (`positional argument 0 must match ^parsers/[a-z-]+\.py$`, from the PROJECT config)
  was only discoverable by opening the config file.

## Proposed Approach

- Every filter kind renders ONE line stating its rule mechanically: the target it reads, the direction (must / must
  not), and the pattern verbatim in backticks. No attempt at "friendlier" paraphrase of a regex — operator: it would
  cost more tokens to say exactly the same thing.
- `AllowedCommand.explain()` lists those lines under the entry instead of `must pass N filter(s)`.
- The parser itself is NOT rendered. Instead, an entry WITHOUT a `commandParser` (and without `hasNoPathParameters`)
  carries a warning that every argument that looks like a path — options included — is treated as one and checked
  against the path rules. Operator's reasoning: a rule like "the `subcommand` must match …" is self-explanatory under
  its entry; path rejection is something the plugin always does, so what the reader needs is the warning where it bites
  hardest (no parser → no argument is ruled out as a path), not a statement of which parser judges paths. The warning is
  stated ONCE in the AUTO-ALLOWED COMMANDS header, and each affected entry carries a short `[no parser]` tag (≈50 of the
  operator's 69 entries have no parser; a full sentence per entry would add ~1.5k tokens to every session start).
- The header also states, ONCE and for EVERY entry (not as part of the `[no parser]` note), the unknowable-content rules
  as measured (`experiments/probe_unknowable.py`, 2026-11-06, operator's live config):
  - a `$VAR` reference denies on any entry unless the entry lists that variable (`onlyTheseVariables`, already rendered
    as "only variables permitted") — `grep $HOME README.md` → `DisallowedVariableReferenced`.
  - a `$(...)` must itself be auto-allowed, and its result is unknown: the command denies if that result sits where a
    path could be or where a rule must inspect it. Consequently a `[no parser]` entry ALWAYS denies a `$(...)` argument
    (`rg $(echo pat) README.md`, `echo $(echo hi)` → `UnknowablePathArgument`), while an entry whose parser rules the
    slot out allows it (`grep $(echo pat) README.md`, `chmod $(echo 755) bin/x` → allow) and so does a
    `hasNoPathParameters` entry (`spawn-claude $(echo name)` → allow). A rule-inspected slot denies
    (`git commit -m "$(echo msg)"` → today `FilterRejected` on `subcommand`, after this change `FilterUnprovable`).
- The deny reason renders the same rule line for the filter that rejected, so the hint names exactly which requirement
  failed. Rejection is split by cause: `FilterRejected(program, filter)` when the rule failed on the visible text,
  `FilterUnprovable(program, filter)` when it could not be proven because the invocation contains `$VAR`/`$(...)` — the
  latter's hint says to run the value-producing command first and write the value literally. Without the split, the hint
  would show a rule the command visibly satisfies.

## Affected Components

- `lib/matcher.py` — `Matcher.explain(action)` rewritten per subclass into the rule-line wording below; value equality
  (`__eq__`/`__hash__` over type + pattern + index/name/option); `derive_alternative()` deleted (no production caller).
- `lib/action.py` — already has equality; gains the must / must-not wording helper the matchers use.
- `lib/filter.py` — `Filter` equality (matcher + action); `InvalidFilter` gains `explain()` and equality;
  `derive_alternative()` deleted.
- `lib/paths_filter.py`, `lib/nested_command_filter.py` — new `explain()` wording, equality, `derive_alternative()`
  deleted.
- `lib/allowed_command.py` — `explain()` renders the `[no parser]` tag and one indented rule line per BUILT filter; "any
  arguments" instead of "no filters — permits every invocation".
- `lib/config.py` — `_explain_allowed_commands()` header: the composition rule, the `[no parser]` note, the `$VAR` and
  `$(...)` rules.
- `lib/reason.py` — `FilterRejected(program, filter)` (replaces `filter_type`); new `FilterUnprovable(program, filter)`
  added to `NEAR_MISS_REASON_TYPES`.
- `lib/allowed_command_policy.py` — `_filter_passes`/`_required_filter_passes` become a rejection-returning
  `_filter_rejection(...)` → `None | FilterRejected | FilterUnprovable` (same "never a bool" style as
  `_entry_rejection_reason`).
- `lib/reason_renderer.py` — clauses for both, calling `reason.filter.explain()`.
- Tests: `tests/test_matcher.py`, `tests/test_filter.py`, `tests/test_paths_filter.py`, `tests/test_allowed_command.py`,
  `tests/test_config.py`, `tests/test_reason_renderer.py`, `tests/test_allowed_command_policy.py` (3 `FilterRejected`),
  `tests/test_permission_decisions.py` (14 `FilterRejected`), `tests/test_escalation_policy.py`.
- `docs/knowledgebase/command-policy-decision-model.md` — Reason list (`FilterUnprovable`), the "Known limit on how far
  the recognition rule can be followed from the rendered rules alone" paragraph (~line 926, now obsolete), the worked
  example citing `FilterRejected(program='git', filter_type='namedValue')`.
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — version 0.7.0 → 0.8.0 in the same commit as the
  plugin-content change.

## Implementation Notes

### Rendered shape (target)

```
AUTO-ALLOWED COMMANDS — a command is auto-allowed when ONE entry for its program accepts it; every rule under that entry must hold.
Any $VAR denies unless the entry lists it as a permitted variable. A $(...) must itself be auto-allowed; its result is unknown, so the command denies if that result lands where a path could be or where a rule must inspect it.
[no parser] = the entry has no command parser, so every argument that looks like a path, options included, is treated as one and must stay inside the project or an allowed prefix; such an entry therefore always denies a $(...) argument.
- rg [no parser]: any arguments.
- cat: any arguments.
- spawn-claude: any arguments; takes no path arguments.
- git:
  - value `subcommand` must be present and match `^(status|log|…)$`
- d2 [no parser]:
  - the arguments, joined by spaces, must not match `(^| )--watch`
```

Header wording may be tightened during implementation; the facts it states may not change.

### Rule line per filter kind

| Kind                   | Line                                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| `parameterRegex`       | the arguments, joined by spaces, must [not] match `P`                                          |
| `matchFullParameter`   | required: one argument must be exactly `P` · block: no argument may be exactly `P`             |
| `positionalArgRegex`   | the positional arguments, joined by spaces, must [not] match `P`                               |
| `argumentAtIndex`      | argument N (from 0, options counted) must be present and [not] match `P`                       |
| `positionalArgAtIndex` | positional argument N (from 0, options skipped) must be present and [not] match `P`            |
| `namedValue`           | value `name` must be present and [not] match `P`                                               |
| `optionValue`          | option `O` must be given and its value must [not] match `P`                                    |
| `optionPresent`        | option `O` must [not] be given                                                                 |
| `paths`                | every path argument, if any, must be one of: `a`, `b` (empty list: must have no path argument) |
| `nestedCommand`        | every wrapped command must itself be auto-allowed (at least one required[; max depth N])       |
| `InvalidFilter`        | broken rule, this entry never applies: <problem>                                               |

"must be present" is rendered under BOTH actions for index/named/optionValue kinds: `TARGET_ABSENT` fails the filter
regardless of action (`lib/action.py:44`).

- `[no parser]` is decided by `entry.command_parser is None and not entry.has_no_path_parameters`; a
  `hasNoPathParameters` entry renders "takes no path arguments" instead.
- Deny clauses: `FilterRejected` → `{program}: rejected by the rule: {filter.explain()}`; `FilterUnprovable` →
  `{program}: could not prove the rule {filter.explain()} because the invocation contains $VAR or $(...) - run the value-producing command first and write its value literally`.
- `FilterUnprovable` is returned exactly where `_filter_passes` today returns `False` because of knowability (block /
  nestedCommand with `defeats_absence_proof()`, a required index filter at/after the first shifting position, the
  external-parser no-re-parse case) — NOT when the knowable-only re-parse ran and the rule genuinely failed on it (that
  stays `FilterRejected`).
- `escalation_policy.py` classifies near-miss vs categorical by `NEAR_MISS_REASON_TYPES` — adding `FilterUnprovable`
  there keeps `bypass-policy` routing it to `passthrough`.

### Observed during exploration

- A `structured` parser that declares no `path: false` slot is, for path candidacy, exactly as strict as no parser, but
  will not carry the `[no parser]` tag. Accepted: the tag is literal, and the header's `$(...)` rule still states the
  behaviour. Not changed here.

## Test Architecture

`cd tests && nix-shell --run pytest` (CLAUDE.md). TDD via the `tdd` skill, one test at a time. No new fixtures needed —
every layer is already testable from constructed values:

- Rule lines: unit tests per kind in `tests/test_matcher.py` (replacing the 2 schema-echo `explain` tests and the
  `derive_alternative` tests), `tests/test_paths_filter.py`, `tests/test_filter.py` (`Filter`, `InvalidFilter`,
  `NestedCommandFilter` — via `Filter.from_definition`). One required + one block case per kind where the action changes
  the wording.
- Equality: `Filter.from_definition(d) == Filter.from_definition(d)` and inequality on a differing pattern/index.
- Entry/header: `tests/test_allowed_command.py` (`[no parser]` tag, `hasNoPathParameters` wording, indented rule lines;
  replaces `test_a_filtered_entry_explains_its_filter_count`), `tests/test_config.py` (header facts present once).
- Verdicts — fantasy callsites in `tests/test_permission_decisions.py` (spec suite, structural reason assertions):

  ```python
  subcommand_rule = Filter.from_definition({"type": "namedValue", "name": "subcommand",
                                            "pattern": "^(status|commit)$", "action": "required"})
  assert_reason_includes(git_config.decision_for("git push"), FilterRejected("git", subcommand_rule))
  assert_reason_includes(git_config.decision_for('git commit -m "$(echo msg)"'), FilterUnprovable("git", subcommand_rule))
  assert_reason_includes(echo_config.decision_for("echo $(echo x)"), FilterUnprovable("echo", forbidden_flag_rule))
  ```

  The existing 17 `FilterRejected(program, "type")` assertions are migrated to carry the built filter; each one whose
  case is driven by unknowable content (e.g. the `nestedCommand`/external-parser cases) is re-checked and becomes
  `FilterUnprovable` where that is the true cause.

- Rendering: `tests/test_reason_renderer.py` — both clauses contain the rule line; the unprovable clause names `$VAR`/
  `$(...)` and the decomposition route.
- Bypass routing: `tests/test_escalation_policy.py` — a `FilterUnprovable`-only denial under `bypass-policy` is
  `passthrough`.
- `tests/test_skill_drift.py` — run; it guards skill/docs drift and may need the new reason type.

## Assumptions

- **Every built filter kind (Filter via Matcher, PathsFilter, NestedCommandFilter) already has
  explain()/derive_alternative(), but no production code calls them; AllowedCommand.explain renders only the raw filter
  count** — confirmed (grep of lib/ and bin/ for explain/derive_alternative callers: only tests/test_matcher.py
  exercises them; lib/allowed_command.py:129-137)
- **A FilterRejected denial can be caused by unknowable content (a variable or substitution) rather than by the rule
  failing on literal text, and \_filter_passes returns only a bool so the two cases are currently indistinguishable** —
  confirmed (lib/allowed_command_policy.py lines 341-368: block and nestedCommand filters return False when knowability
  defeats absence proof; required index filters return False past the first shifting position; external-parser required
  filters fail closed. KB worked example: a commit message given via substitution denies as FilterRejected on the git
  namedValue filter although the subcommand matches)

## Design Decisions

### Scope: explain output AND the FilterRejected denial

- Chosen: per-filter rule lines in `Config.explain()` and the same line in the `FilterRejected` deny reason.
- Rationale: operator — "good point the rejection should also render the explanation".
- Rejected alternatives: explain only (denials handled later); additionally an author-written `description` field per
  filter/entry (schema change; operator: a friendlier text "would just cost more tokens to say exactly the same thing").
- Date: 2026-11-06

### Rule wording: mechanical, regex verbatim

- Chosen: target + must/must not + pattern verbatim.
- Rationale: operator — "there is no way to build anything 'friendlier' without huge amount of work - and in the end it
  would just cost more tokens to say exactly the same thing".
- Rejected alternatives: paraphrasing regexes into natural language.
- Date: 2026-11-06

### Parser: warn on its absence instead of naming it

- Chosen: entries without `commandParser` get a warning that any argument looking like a path is treated as one and
  evaluated against the path rules; entries with a parser get no parser line.
- Rationale: operator — a filter line like "the `git` subcommand must match …" is clear from context without saying how
  it is read; path rejection is something the plugin always does, so warn where no parser exists rather than saying
  "parser x judges which parameter is a path".
- Rejected alternatives: rendering a "parsed by provided parser 'x'" line per entry.
- Date: 2026-11-06

### No-parser warning placement: shared note + tag

- Chosen: the warning text once in the header, a `[no parser]` tag per affected entry.
- Rationale: operator — "shared + no parser please".
- Rejected alternatives: a full warning sentence on each of ~50 entries (~1.5k tokens per session start).
- Date: 2026-11-06

### Denials from unknowable content are distinguishable

- Chosen: filter evaluation yields passed / failed / unprovable; the deny reason renders "could not be proven because of
  `$VAR`/`$(...)`" for the unprovable case.
- Rationale: operator — "yes please make it ditinguishable".
- Rejected alternatives: always rendering just the rule (misleading when the literal text satisfies it).
- Date: 2026-11-06

### Variable/substitution rules are general, not part of the `[no parser]` note

- Chosen: state the `$VAR` and `$(...)` rules once in the header for all entries; the `[no parser]` note only adds the
  consequence that such an entry always denies a `$(...)` argument.
- Rationale: operator — "Having variables or invocations inside a command makes it unparsable regardless whether the
  command has a parser or not". Measurement refined it: variables deny everywhere (unless `onlyTheseVariables`), but
  `$(...)` is allowed with a parser that rules the slot out, or with `hasNoPathParameters`.
- Rejected alternatives: the sketch's original attachment of the `$VAR`/`$(...)` sentence to the `[no parser]` note.
- Date: 2026-11-06

### Deny reason carries the built filter; unknowable case is its own Reason type

- Chosen: `FilterRejected(program, filter)` and `FilterUnprovable(program, filter)`, rendered via `filter.explain()` in
  `reason_renderer`; filters get value equality.
- Rationale: operator — "I agree" (with the recommendation: keeps the knowledgebase rule that a Reason carries facts and
  prose lives only in the renderer; mirrors the existing `UnknowablePathArgument` vs `ArgumentPathOutsideAllowedPaths`
  split).
- Rejected alternatives: keep `filter_type` and add a pre-rendered `rule: str` plus `provable: bool` (prose inside a
  Reason, a flag where the design uses distinct types; less test churn).
- Date: 2026-11-06

## Success Criteria

- `explain-policy` against the operator's config shows, for every filtered entry, one line per filter stating target,
  must/must-not and the pattern verbatim (e.g. git's `subcommand` regex, all six `d2` block patterns); no
  `must pass N filter(s)` remains.
- Entries without `commandParser` and without `hasNoPathParameters` carry `[no parser]`; the header explains it once and
  states the `$VAR` / `$(...)` rules once, for all entries.
- `python3 x.py` against the project config denies with a reason naming
  `positional argument 0 … must be present and match ^parsers/[a-z-]+\.py$`.
- `git commit -m "$(echo msg)"` denies with `FilterUnprovable` whose rendered clause says the rule could not be proven
  because of `$VAR`/`$(...)`; `git push` denies with `FilterRejected` naming the subcommand rule.
- `bypass-policy` still turns a `FilterUnprovable`-only denial into `passthrough`.
- Full test suite green; knowledgebase no longer claims explain renders only a filter count; version 0.8.0 in both
  manifests.

## Implementation TODO

<!-- Implementation note: in tests, the "cannot be evaluated" cases (unknown type/action, optionValue on an option the
parser never populates, nestedCommand under a parser that publishes nothing) reject through an `InvalidFilter`, so the
migrated assertions use `assert_rejected_by_filter(result, program, FilterClass)`; only rule-centred cases compare the
built filter itself. `pytest` is not auto-allowed under `nix-shell --run`, so the suite was run with a one-off
`bypass-policy`. Durable proposal for the operator: add-allow-policy --scope project --intent "Run the pytest suite" --example "nix-shell --run pytest" '<nix-shell entry allowing pytest>'. -->

- [x] Update status to in-progress
- [x] Rule lines per matcher kind + matcher value equality; delete `derive_alternative` — `lib/matcher.py`,
      `lib/action.py`, `tests/test_matcher.py`
- [x] `Filter`/`InvalidFilter`/`PathsFilter`/`NestedCommandFilter` `explain()` + equality; delete `derive_alternative` —
      `lib/filter.py`, `lib/paths_filter.py`, `lib/nested_command_filter.py`, `tests/test_filter.py`,
      `tests/test_paths_filter.py`
- [x] `AllowedCommand.explain()` renders `[no parser]` / "takes no path arguments" / "any arguments" and indented rule
      lines from `built_filters` — `lib/allowed_command.py`, `tests/test_allowed_command.py`
- [x] AUTO-ALLOWED COMMANDS header (composition rule, `$VAR`/`$(...)` rules, `[no parser]` note) — `lib/config.py`,
      `tests/test_config.py`
- [x] `FilterRejected(program, filter)` + new `FilterUnprovable(program, filter)` in `NEAR_MISS_REASON_TYPES`; renderer
      clauses — `lib/reason.py`, `lib/reason_renderer.py`, `tests/test_reason_renderer.py`
- [x] Replace `_filter_passes`/`_required_filter_passes` with `_filter_rejection` returning
      `None | FilterRejected | FilterUnprovable`; migrate the 17 existing `FilterRejected` assertions and add the
      git/echo verdict cases — `lib/allowed_command_policy.py`, `tests/test_allowed_command_policy.py`,
      `tests/test_permission_decisions.py`
- [x] Bypass routing check: a `FilterUnprovable`-only denial under `bypass-policy` is `passthrough` —
      `tests/test_escalation_policy.py`
- [x] Full suite (`cd tests && nix-shell --run pytest`, incl. `test_skill_drift.py`); run `bin/explain-policy` and
      compare against the Success Criteria
- [x] Knowledgebase: Reason list gains `FilterUnprovable`, replace the "Known limit … rendered rules alone" paragraph,
      update the git worked example — `docs/knowledgebase/command-policy-decision-model.md`
- [x] Bump version 0.8.0 → 0.9.0 (0.8.0 had already shipped on main) in `.claude-plugin/plugin.json` and
      `.claude-plugin/marketplace.json` in the same commit as the plugin-content change
- [ ] Update status to completed