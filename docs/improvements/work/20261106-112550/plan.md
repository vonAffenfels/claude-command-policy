# Improvement 20261106-112550: bypass-policy escalates commands whose arguments contain a substitution

## Meta

- Related Ticket: None
- Status: planned
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T11:26:00+01:00
- Merge target: main

## This Improvement's Objective

A bypass-policy invocation whose wrapped arguments contain a command or process substitution is recognised as the escape
hatch and escalated (allow, passthrough or ask) instead of falling through to the ordinary pipeline and dead-ending as a
deny.

## Context / Why This Exists

The orchestrator reported that `bypass-policy git commit -m "$(echo msg)"` is DENIED. Measured (2026-11-06, live user
config, `Config.decision_for`):

| Command                                     | Decision    |
| ------------------------------------------- | ----------- |
| `bypass-policy git commit -m "msg"`         | allow       |
| `bypass-policy ls "$X"`                     | passthrough |
| `bypass-policy ls "$(echo x)"`              | **deny**    |
| `bypass-policy ls <(echo x)`                | **deny**    |
| `bypass-policy git commit -m "$(echo msg)"` | **deny**    |

The deny reason is `bypass-policy: an argument whose value cannot be known at analysis time occupies a path operand` —
i.e. the user's own `bypass-policy [no parser]` allowedCommands entry objecting in the ORDINARY pipeline. The escape
hatch never ran.

**Root cause — recognition, not ordering.** The operator's intuition was "the bypass check should be very early". It is
not early (`bypass_transform` is a result transformer applied after the ordinary pipeline in `Config.decision_for`,
`lib/config.py:392`), but ordering is not the problem: the transformer replaces the ordinary decision whenever it
applies. The problem is that it does not apply. `bypass_transform` recognises the wrapper via
`Statement.as_sole_invoked_program()` (`lib/statement.py:167`), which returns `None` whenever the Command has ANY
`sub_statements()` — and a `CmdSubst`/`ProcSubst` inside an argument is one. So a substitution in the wrapped arguments
makes the line "not the wrapper", and the ordinary decision (deny) is returned unmodified.

**Why this is a defect, not intent.**

- The knowledgebase (`docs/knowledgebase/command-policy-decision-model.md`, `bypass_transform` bullet) says the
  transformer combines "anything a raw-text scan of the whole line finds — sensitive paths/variables, command
  substitution" with the wrapped decision: substitution handling for the wrapper was designed, but is unreachable.
- A `$VAR` and a `$(...)` are "unknowable in exactly the same sense" (same article), yet `$VAR` already escalates
  (passthrough) and `$(...)` denies — `as_sole_invoked_program()` only sees `CmdSubst`/`ProcSubst` because a `ParamExp`
  is not a `Statement`.
- "Denying more is not safer": a deny on an explicit `bypass-policy` dead-ends the one escalation route, pointing at
  alternatives that by definition the caller has already given up on.
- No test, KB passage or past plan records excluding substitutions from bypass deliberately (searched `tests/`, `docs/`,
  `lib/`).

**The stricter recognition stays right for `add-allow-policy`.** Its `shell_touched` grammar violation relies on
`as_sole_invoked_program()` rejecting substitutions, because the persisted entry/examples must be literal. That caller
must keep today's behaviour.

## Implementation Notes

### Observed during exploration

- `git commit -m "$(echo msg)"` (no wrapper) denies with `FilterUnprovable` on the git entry's `subcommand` rule, even
  though `commit` is a literal pinned AHEAD of the substitution — the KB's "the shift bites only forward" rule says such
  a value stays provable. Likely the parser-backed `value` filter treats the whole invocation as unprovable once any
  argument is unknowable. Out of scope here; worth its own improvement.

## Assumptions

- **bypass_transform does not apply when the wrapped arguments contain a command or process substitution, because Statement.as_sole_invoked_program() returns None for any Command with sub_statements()** — confirmed (lib/statement.py:181; Config.decision_for on the live config: bypass-policy ls with a quoted command substitution -> deny, with a process substitution -> deny, with a quoted variable -> passthrough)
