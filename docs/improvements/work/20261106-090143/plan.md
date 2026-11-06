# Improvement 20261106-090143: Filters explain what an invocation must look like

## Meta

- Related Ticket: None
- Status: planned
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T09:01:49+01:00
- Merge target: main

## This Improvement's Objective

Make explain-policy (and the SessionStart/SubagentStart rendering built from the same Config.explain) state, per
allowedCommands entry, what an invocation must look like to be auto-approved, instead of only the filter count, by
having each filter render its own requirement as short prose.

## Proposed Approach

(Design mode, still being shaped.)

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
  as measured (experiments/probe_unknowable.py, 2026-11-06, operator's live config):
  - a `$VAR` reference denies on any entry unless the entry lists that variable (`onlyTheseVariables`, already rendered
    as "only variables permitted") — `grep $HOME README.md` → `DisallowedVariableReferenced`.
  - a `$(...)` must itself be auto-allowed, and its result is unknown: the command denies if that result sits where a
    path could be or where a rule must inspect it. Consequently a `[no parser]` entry ALWAYS denies a `$(...)` argument
    (`rg $(echo pat) README.md`, `echo $(echo hi)` → `UnknowablePathArgument`), while an entry whose parser rules the
    slot out allows it (`grep $(echo pat) README.md`, `chmod $(echo 755) bin/x` → allow) and so does a
    `hasNoPathParameters` entry (`spawn-claude $(echo name)` → allow). A rule-inspected slot denies
    (`git commit -m "$(echo msg)"` → `FilterRejected` on `subcommand`).
- The `FilterRejected` denial reason renders the same rule line for the filter that rejected, so the deny hint names
  exactly which requirement failed. `_filter_passes` returns a three-way verdict (passed / failed / unprovable) instead
  of a bool, and an UNPROVABLE rejection renders differently: the rule could not be proven because the invocation
  contains `$VAR`/`$(...)` — run the value-producing command first and write the value literally. Without this, the hint
  would show a rule the command visibly satisfies.

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

- Chosen: `_filter_passes` yields passed / failed / unprovable; the deny reason renders "could not be proven because of
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
