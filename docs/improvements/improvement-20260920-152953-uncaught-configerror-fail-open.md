# Improvement 20260920-152953: Catch `ConfigError` at command-policy's load-time and match-time entrypoints

## Meta

- Related Ticket: None
- Status: planned
- Created: 2026-09-20
- Updated: 2026-09-20
- Plan started: 2026-09-20T15:27:34+02:00
- Depends on: 20260920-131722

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

- [ ] Update status to in-progress
- [ ] (To be determined)
- [ ] Update status to completed

## Related Past Improvements

- improvement-20260920-131722: the dependency this improvement builds on — introduced the `StructuredParser` path
  candidacy work whose independent review surfaced the narrow match-time `ConfigError` gap that motivates this
  improvement.
- improvement-20260913-124952: the shfmt-permissions predecessor of this exact defect class — a structurally malformed
  entry crashing `render_config.py` instead of degrading gracefully. Relevant prior art for the degradation-contract
  decision this improvement also has to make, in the newer `command-policy` engine instead.
