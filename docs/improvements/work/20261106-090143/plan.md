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
