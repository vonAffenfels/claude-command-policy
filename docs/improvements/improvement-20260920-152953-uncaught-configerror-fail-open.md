# Improvement 20260920-152953: Catch `ConfigError` at command-policy's load-time and match-time entrypoints

## Meta

- Related Ticket: None
- Status: completed (via absorption — see note below; never separately implemented)
- Created: 2026-09-20
- Updated: 2026-09-25
- Plan started: 2026-09-20T15:27:34+02:00
- Depends on: 20260920-131722

## Absorbed by improvement-20260925-120037 (2026-09-25)

This improvement's own Proposed Approach was never written (`(To be determined)` below is the state it was left in). Its
whole problem class — `Config.from_dict`/`Config.decision_for` raising an uncaught `ConfigError` for an
`allowedCommands` defect, reaching every `bin/` entrypoint as an unhandled exception — was resolved as a side effect of
improvement `20260925-120037`'s value-object refactor, not by implementing a catch at the entrypoints this file proposed
to add one to. That improvement's Proposed Approach named this file explicitly: "This absorbs the decision-time half and
the `programGlob` load-time half of planned improvement `20260920-152953`."

**What actually happened, in full — broader than the "decision-time half and `programGlob` load-time half" the other
improvement's own approach text anticipated:** every `ConfigError` raise site this improvement's Objective names (a
retired `commandParser` key, an `optionValue` filter naming an option its parser never populates, an unrecognised filter
type/action, a `nestedCommand` filter on a parser that cannot publish sub-commands, an unrecognised `commandParser`
type, a malformed `programGlob` entry) no longer raises reachably at all — `AllowedCommand.from_entry`,
`Filter.from_definition`, and `lib/parser_factory.py`'s `build_parser` convert every one of these into a construction-
time PROBLEM (`AllowedCommand.problems()`) instead. The two `ConfigError` raise sites that remain in the codebase
(`Action.from_definition` for an unrecognised action, `StructuredParser.from_definition` for a retired key) are both
caught by their own direct callers (`Filter.from_definition`, `lib/parser_factory.py`'s `_build_structured`
respectively) before ever reaching `Config.from_dict`/`decision_for` — confirmed live:
`grep -rn "raise ConfigError" lib/` returns exactly those two sites, neither reachable from any `bin/` entrypoint. **No
separate "catch it at the entrypoints" implementation was ever needed or written** — there is nothing left to catch. See
that improvement's own Success Criteria ("No `ConfigError` escapes `decision_for` for any `allowedCommands` defect...")
and its knowledgebase update (`docs/knowledgebase/command-policy-decision-model.md`, "Load-Time Rejection Superseded by
Construction-Time Problems") for the design this file's TODO would otherwise have needed to build.

The `Path('.')` vs. `os.getcwd()` project-directory fallback divergence this file's Objective also raised as a loose
thread was NOT addressed by that work and remains open if it still matters - re-measure before assuming it is still
true, since `PathResolutionContext.for_project()` (new in `20260925-120037`) is now the single place that fallback lives
(`os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())`), which may already have changed the shape of that divergence.

## This Improvement's Objective

`command-policy`'s PreToolUse/SessionStart/SubagentStart/PostToolUse hook entrypoints and user-facing CLIs
(`explain-policy`, `audit-session-policy`) all call into `Config.from_dict` / `Config.decision_for` /
`Config.decision_for_path`, which can raise `ConfigError` for a config no author could have meant (a retired
`commandParser` key, an `optionValue` filter naming an option its parser never populates, an unrecognised filter
type/action, a `nestedCommand` filter on a parser that cannot publish sub-commands, an unrecognised `commandParser`
type, or a malformed `programGlob` entry). Today NONE of these entrypoints catch `ConfigError`: it propagates as an
uncaught Python exception, the process exits 1 with an empty stdout and a traceback on stderr, and Claude Code treats a
non-zero non-2 PreToolUse exit as non-blocking — so the engine gives NO verdict for the affected command and it falls
through to Claude Code's own permission rules (a deny-by-default engine failing open, the one direction it cannot
tolerate), while SessionStart/SubagentStart/PostToolUse hooks silently lose their advisory output entirely with no
visible signal to the operator.

This was originally found (independent review of improvement `20260920-131722`, which this improvement depends on) as a
narrow match-time case (a retired `StructuredParser` key denies verdicts only for commands matching the defective
entry); further research during this planning session found a second, much broader load-time case
(`AllowedCommand.from_entry`'s `programGlob` validation raises inside `Config.from_dict` itself, before any command is
considered, breaking EVERY `command-policy` `bin/` entrypoint for the ENTIRE config — verified by running the real
`bin/` scripts against an isolated fake config). This improvement designs and implements a uniform, legible catch for
`ConfigError` at both the load-time and match-time points in the call chain, across every affected `bin/` entrypoint, so
a defective config produces an actionable signal (naming the offending layer/entry/key and what to change) instead of a
silent abstention or an invisible loss of advisory context.

It also decides whether the `config_loader.py` `Path('.')` vs. `config.py` `os.getcwd()` project-directory fallback
divergence (a related silent-failure-mode loose thread found by a separate review) belongs in this improvement's scope.

## Context / Why This Exists

**Origin / trigger:** The independent review of improvement `20260920-131722` found the unhandled-`ConfigError` seam and
deliberately deferred it to its own improvement. It is PRE-EXISTING, not a regression: the reviewer reconstructed the
tree at commit `503e192` and reproduced the identical exit-1 traceback there via a different already-reachable
`ConfigError` (an `optionValue` filter naming an option the parser cannot consume). `20260920-131722` neither introduced
nor widened it — it added one more trigger for a seam that was already there, and deliberated the placement explicitly
(its Design Decision "What happens to a config still carrying a retired key" chose match-time over load-time to match
the established split). The broader load-time `programGlob` variant was found during this planning session's own
research and measurement.

**Consumer(s) of the output:** Claude (the agent) first, the operator second. The reason text lands in Claude's
PreToolUse result, so Claude reads it, relays it to the operator, and may offer to edit the config file directly; the
operator is the one who ultimately fixes the JSON. The wording therefore has to work as an agent-actionable routing
signal AND as human diagnostics.

**Adjacent systems already covering part of the need:** All three of the existing diagnostic surfaces —
`Config.warnings()` / `lib/warning_value.py` (structured `Warning` values carrying layer provenance, the channel that
already handles the RECOVERABLE defects by degrading rather than raising), `bin/command-policy-lint-config-on-write`
(PostToolUse re-lint of the merged config after any write touching `command-policy.json`), and `Config.explain()` plus
the SessionStart/SubagentStart renderers (which surface the warnings block every session). The design should route into
that existing vocabulary and those surfaces wherever it can, rather than standing up a second, parallel diagnostic
channel.

## Proposed Approach

(To be determined)

## Affected Components

**Files:**

- (To be determined)

**Classes/Functions:**

- (To be determined)

## Implementation Notes

(To be determined)

## Success Criteria

- [ ] (To be determined)

## Implementation TODO

- [x] Update status to in-progress (skipped in practice — absorbed before ever starting; see the absorption note above)
- [x] (To be determined) — resolved by absorption into improvement-20260925-120037, never separately implemented
- [x] Update status to completed

## Related Past Improvements

- improvement-20260920-131722: the dependency this improvement builds on — introduced the `StructuredParser` path
  candidacy work whose independent review surfaced the narrow match-time `ConfigError` gap that motivates this
  improvement.
- improvement-20260913-124952: the shfmt-permissions predecessor of this exact defect class — a structurally malformed
  entry crashing `render_config.py` instead of degrading gracefully. Relevant prior art for the degradation-contract
  decision this improvement also has to make, in the newer `command-policy` engine instead.
