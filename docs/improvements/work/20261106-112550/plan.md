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

### Reframing (operator, 2026-11-06): should bypass analyse the wrapped command at all?

The operator questioned the premise of `bypass_transform`'s re-analysis rather than its recognition gap:

- `bypass-policy "$(rm -Rf /)"` runs `rm` outside the wrapper, but the operator sees the whole command line in Claude
  Code's prompt; accepting it is an informed choice.
- The categorical `ask` floor (blocked command, sensitive path, redirect outside the boundary) is trivially sidestepped,
  e.g. `bypass-policy bash -c 'ROOT=/ ; rm -Rf $ROOT/.'` — so it is a best-effort floor, not a guarantee.
- `bypass-policy` exists only as the workaround for a deny whose guidance toward an auto-allowed command did not pan
  out. Anything other than `passthrough` is questionable for it.

Measured context for this user: `~/.claude/settings.json` has `defaultMode: "default"` and NO rule auto-approving
`bypass-policy`; no project settings exist. So today `passthrough` already ends in Claude Code's own prompt, and the
forced `ask` differs from it observably only (a) in the reason text shown in the prompt and (b) under a permissive
settings rule or permission mode — which the KB's original design names as the case it guards ("the worst outcome").
Dropping the floor reverses that recorded design decision and requires rewriting the KB's outcome table and
`bypass_transform` passage.

The operator settled it (see Design Decisions): bypass is ALWAYS `passthrough`. "The command literally exists to allow
commands we do not recognize or don't want auto allowed but do actually need them this once."

## Proposed Approach

`bypass-policy` becomes a pure escape hatch: when the line is one invocation of the wrapper, the engine returns
`passthrough` WITHOUT analysing anything — no ordinary pipeline run, no re-analysis of the wrapped words. This makes the
operator's original intuition literally true: the bypass check runs early, before the passes, so nothing deeper (an
unknowable path operand, a substitution, a filter) can catch it.

**Recognition** — what counts as "the line is one invocation of the wrapper":

- the top-level statement is a single `Command` (no `;`/`&&`/`||` list, pipeline, subshell, control flow), not
  backgrounded, whose command word is `bypass-policy`;
- command/process substitutions INSIDE its words (and its assignments) are allowed — the calling shell runs them, but
  the operator sees the whole line in Claude Code's prompt;
- redirects on the wrapper are allowed (same reasoning);
- `! bypass-policy …` still counts (unchanged).

`bypass-policy true && rm -rf /` stays unrecognised and faces normal analysis — the `rm` is not something the wrapper
runs, and the chained-command carve-out is the one anti-laundering rule that survives.

This needs a second, looser `Statement` query beside `as_sole_invoked_program()`, which `add-allow-policy` (literal
entry/examples required) and `allowed_command_policy.py` (nested-command handling) keep using unchanged:

```python
# lib/statement.py
def as_single_command_program(self):
    """The program this line's one top-level command invokes, else None.

    Unlike `as_sole_invoked_program()`, a command/process substitution
    inside that command's words does not disqualify it: the line still
    hands its argv to exactly this one program. A list, pipeline,
    subshell, control flow or backgrounding still does."""
    if not isinstance(self, Command) or self.is_backgrounded:
        return None
    return self.command_word
```

```python
# lib/escalation_policy.py
def is_bypass_invocation(statement):
    return statement.as_single_command_program() == BYPASS_WRAPPER_PROGRAM


def bypass_passthrough(statement):
    """None unless the line is one bypass-policy invocation; then passthrough,
    unanalysed - bypass is the deliberate escape from every objection."""
    if not is_bypass_invocation(statement):
        return None
    return PermissionDecision.passthrough(PASSTHROUGH_REASON)
```

```python
# lib/config.py — Config.decision_for
add_allow = add_allow_policy_transform(...)
if add_allow is not None:
    return add_allow

bypass = bypass_passthrough(statement)
if bypass is not None:
    return bypass

ordinary = self._decision_for_statement(statement, command, depth=0, max_nested_depth=max_nested_depth)
hinted = bypass_chain_hint(statement, ordinary)
return hinted if hinted is not None else ordinary
```

`add_allow_policy_transform` stays first: `_mentions_program` only matches a command WORD, so
`bypass-policy add-allow-policy …` is not an add-allow line (verified by reading `_mentions_program`, which compares
`command_word`), while `bypass-policy x "$(add-allow-policy …)"` keeps denying as `shell_touched`.

**Removed with the re-analysis:** `bypass_transform`, `_wrapped_source_text`, `Command.arguments_source_text` (its only
production caller), and the `NEAR_MISS_REASON_TYPES` filtering in escalation_policy (the tuple itself stays in
`reason.py` — the KB's classification still uses it).

`session_audit.is_bypass_wrapped` delegates to `escalation_policy.is_bypass_invocation`, removing its duplicate
`BYPASS_WRAPPER_PROGRAM` constant — one recognition rule, one place.

## Affected Components

- `lib/statement.py` — add `as_single_command_program()`; remove `Command.arguments_source_text`.
- `lib/escalation_policy.py` — replace `bypass_transform`/`_wrapped_source_text` with `is_bypass_invocation` +
  `bypass_passthrough`; `bypass_chain_hint` uses `is_bypass_invocation`; rewrite the module docstring's bypass half;
  drop the now-unused `NEAR_MISS_REASON_TYPES`/`render` imports if nothing else uses them.
- `lib/config.py` — `decision_for` wiring (bypass before the ordinary pipeline); its docstring.
- `lib/session_audit.py` — `is_bypass_wrapped` delegates; module docstring's "bypass-policy-forced ask" sentence.
- `lib/escalation_policy.py` `bypass_chain_hint` — drop the "only when a forcing categorical reason is present"
  condition: any denied line that mentions the wrapper without being a bypass invocation gets the hint. With it,
  `_FORCES_ASK_REASON_TYPES` and the `BlockedCommandInvoked`/`SensitivePathReferenced`/`RedirectOutsideAllowedPaths`
  imports become unused — remove them.
- `lib/reason.py` — `NotEscalatedByAnUnrelatedBypassWrapper` docstring: it accompanies ANY objection on a chained line,
  not only a categorical one, and "escalates" now means passthrough. `lib/reason_renderer.py`'s clause ("bypass-policy
  appears on this line but does not wrap this command - wrap it explicitly to escalate it") stays accurate — no change.
- `bin/bypass-policy` — docstring outcome mapping.
- `skills/config/SKILL.md` (§4 categorical/near-miss paragraphs ~L112-121, escape-hatch reference ~L295-300).
- `docs/knowledgebase/command-policy-decision-model.md` — outcome table (L42-43), the "one guard bypass-policy cannot
  lift" paragraph (L83-91), the `bypass_transform` bullet (L139-152), the `shell_touched` row's "the same way
  `bypass_transform` is" (L192), `.text` readers list mentioning `bypass_transform` (~L551, ~L570), the recognition
  asymmetry note (~L578-581), ~L986-988.
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — version 0.9.0 → 0.10.0 (behaviour change).
- `README.md` already describes the passthrough-only behaviour ("let it fall through to claude-codes own command
  approval system") — no change.

## Implementation Notes

### Observed during exploration

- `git commit -m "$(echo msg)"` (no wrapper) denies with `FilterUnprovable` on the git entry's `subcommand` rule, even
  though `commit` is a literal pinned AHEAD of the substitution — the KB's "the shift bites only forward" rule says such
  a value stays provable. Likely the parser-backed `value` filter treats the whole invocation as unprovable once any
  argument is unknowable. Out of scope here; worth its own improvement.

## Test Architecture

Suite: `cd tests && nix-shell --run pytest`. All engine tests build a `Config.from_dict(...)` and call `decision_for` —
no filesystem config needed (`assert_decision` helper in `tests/test_permission_decisions.py`).

- **Decision spec suite** (`tests/test_permission_decisions.py`, Batch 5 + `MATCHING_BRANCH_COVERAGE`):
  - keep `test_the_bypass_wrapper_yields_passthrough_rather_than_allow`, the double-quoted-inner-command test, the
    chained-alongside test, the two-escape-hatches test;
  - REWRITE `test_the_bypass_wrapper_escalates_a_blocked_command_to_a_human_decision` → blocked command wrapped yields
    `passthrough`;
  - REWRITE `test_the_shell_performed_redirect_veto_is_never_waived_but_escalates_to_a_human` → a redirect on the
    wrapper yields `passthrough`; rename branch `redirect_veto_overrides_bypass` accordingly;
  - ADD: command substitution in the wrapped args → `passthrough`; process substitution → `passthrough`; a wrapped
    command that is itself auto-allowed → `passthrough` (not `allow`); a substitution on a CHAINED line
    (`bypass-policy echo "$(echo x)" && rm …` with `rm` blocked) → still `deny`. New coverage branches for each.
- `tests/test_escalation_policy.py` — replace the seven `bypass_transform` unit tests (L25-101) with
  `bypass_passthrough` tests (recognised → passthrough; substitution → passthrough; chained/piped/backgrounded → None;
  other program → None). Chain-hint: `test_bypass_chain_hint_is_none_for_an_ordinary_near_miss` flips to "augments an
  ordinary near-miss on a chained line"; the other chain-hint tests stay. Spec suite gains a case:
  `bypass-policy echo hi && some-unlisted-tool` denies AND carries `NotEscalatedByAnUnrelatedBypassWrapper`.
- `tests/test_statement.py` — add `as_single_command_program` cases beside the `as_sole_invoked_program` ones
  (~L378-410): substitution in args → program; process substitution → program; list/pipeline/subshell/background → None.
  Delete the `arguments_source_text` tests (~L607-627).
- `tests/test_config.py` — delete the three re-analysis tests (L500-516); the spec suite covers the behaviour.
- `tests/test_session_audit.py` — add `is_bypass_wrapped` with a substitution in the args → True.
- `tests/test_hook_envelopes.py:101` — replace the stale `"bypass-policy cannot escalate this"` sample reason with a
  neutral one.

## Assumptions

- **bypass_transform does not apply when the wrapped arguments contain a command or process substitution, because
  Statement.as_sole_invoked_program() returns None for any Command with sub_statements()** — confirmed
  (lib/statement.py:181; Config.decision_for on the live config: bypass-policy ls with a quoted command substitution ->
  deny, with a process substitution -> deny, with a quoted variable -> passthrough)
- **add-allow-policy recognition is unaffected by checking bypass first: \_mentions_program matches only a command word,
  so bypass-policy add-allow-policy ... is not an add-allow line** — confirmed (lib/escalation_policy.py
  \_mentions_program compares Command.command_word and recurses only into sub_statements)
- **Command.arguments_source_text has no production caller other than escalation_policy.\_wrapped_source_text** —
  confirmed (rg arguments_source_text over lib bin tests: lib/statement.py definition, lib/escalation_policy.py:151,
  tests/test_statement.py only)
- **README already describes bypass-policy as falling through to Claude Code's own approval system, so it needs no
  change** — confirmed (README.md:49-51)

## Design Decisions

### Bypass outcome model

- **Chosen:** `bypass-policy` always yields `passthrough`; the wrapped command is never analysed.
- **Rationale:** "The command literally exists to allow commands we do not recognize or don't want auto allowed but do
  actually need them this once." The categorical `ask` floor is trivially sidestepped
  (`bypass-policy bash -c 'ROOT=/ ; rm -Rf $ROOT/.'`) and the operator sees the full line in Claude Code's prompt
  anyway; "if they want it they want it".
- **Rejected alternatives:** (B) `allow` when the wrapped command is auto-allowed, else `passthrough` — keeps the
  re-analysis and its recognition problems for a case that should not be bypassed in the first place; (C) keep
  allow/ask/passthrough and only widen recognition to substitutions — keeps a best-effort floor whose only observable
  effect is under a permissive settings rule/mode. This REVERSES the 2026-09-17 decision of leaf 20260915-010959
  (blocked command / sensitive path / out-of-bounds redirect force `ask` under bypass).
- **Date:** 2026-11-06

### Bypass recognition tolerates substitutions, redirects and assignments on the wrapper

- **Chosen:** the line is a bypass when its single top-level `Command` (not backgrounded) has the command word
  `bypass-policy`, whatever its words contain; a new `Statement.as_single_command_program()` expresses this.
- **Rationale:** the operator: `bypass-policy "$(rm -Rf /)"` "would run `rm -Rf /` outside the bypass-policy wrapper but
  if the Operator is crazy enough to accept that command then he actively wanted that to happen."
- **Rejected alternatives:** loosening `as_sole_invoked_program()` itself — `add-allow-policy`'s `shell_touched`
  violation depends on it rejecting substitutions (the persisted entry must be literal); a `startswith` prefix check —
  would launder `bypass-policy true && rm -rf /`.
- **Date:** 2026-11-06

### Chain hint fires for every denial on a line the wrapper appears on but does not cover

- **Chosen:** `bypass_chain_hint` adds `NotEscalatedByAnUnrelatedBypassWrapper` to any `deny` whose line mentions
  `bypass-policy` without being a bypass invocation — not only to categorical denials.
- **Rationale:** rationale not captured (operator accepted the recommendation: since wrapping now escalates every
  objection, "wrap it explicitly to escalate it" is the right pointer for any denied chained command).
- **Rejected alternatives:** keep it categorical-only — a chained command that is merely not allow-listed would get no
  pointer to the fix.
- **Date:** 2026-11-06

## Success Criteria

- `bypass-policy git commit -m "$(echo msg)"`, `bypass-policy ls <(echo x)`, `bypass-policy rm x` with `rm` blocked, and
  `bypass-policy echo x > /outside/file` all decide `passthrough`.
- A wrapped command that is itself auto-allowed decides `passthrough`, not `allow`.
- `bypass-policy true && rm -rf /` (and the same with a substitution on the line) still faces normal analysis and denies
  when `rm` is not allowed.
- `add-allow-policy` behaviour is unchanged (its whole test batch passes untouched).
- `session_audit` counts a substitution-carrying bypass line as a bypass.
- `bypass-policy echo hi && some-unlisted-tool` denies and its reason carries the chain hint.
- KB, `skills/config/SKILL.md` and `bin/bypass-policy` describe passthrough-only bypass; no mention of a bypass-forced
  `ask` remains outside `docs/improvements/`.
- Version 0.10.0 in both `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, in the same commit as the
  behaviour change.
- `cd tests && nix-shell --run pytest` is green.

## Implementation TODO

- [ ] Update status to in-progress
- [ ] `Statement.as_single_command_program()` test-first (`tests/test_statement.py`, `lib/statement.py`)
- [ ] Spec suite: rewrite the blocked-command and redirect bypass cases to `passthrough`, add the substitution /
      process-substitution / already-allowed / chained-with-substitution cases and their `MATCHING_BRANCH_COVERAGE`
      branches (`tests/test_permission_decisions.py`) — red
- [ ] Replace `bypass_transform` with `is_bypass_invocation` + `bypass_passthrough`, rewrite its unit tests
      (`lib/escalation_policy.py`, `tests/test_escalation_policy.py`); `bypass_chain_hint` uses `is_bypass_invocation`
- [ ] Widen `bypass_chain_hint` to every denial: flip its near-miss unit test, add the spec case
      (`bypass-policy echo hi && some-unlisted-tool` → deny + hint), remove `_FORCES_ASK_REASON_TYPES` and its
      now-unused imports, reword the `NotEscalatedByAnUnrelatedBypassWrapper` docstring (`lib/escalation_policy.py`,
      `lib/reason.py`, `tests/test_escalation_policy.py`, `tests/test_permission_decisions.py`)
- [ ] Wire `bypass_passthrough` before the ordinary pipeline in `Config.decision_for`; delete the three re-analysis
      tests (`lib/config.py`, `tests/test_config.py`) — spec suite green
- [ ] Remove `Command.arguments_source_text` and its tests; drop unused imports in `lib/escalation_policy.py`
      (`lib/statement.py`, `tests/test_statement.py`)
- [ ] `session_audit.is_bypass_wrapped` delegates to `is_bypass_invocation`, add the substitution case, fix the module
      docstring (`lib/session_audit.py`, `tests/test_session_audit.py`)
- [ ] Neutral sample reason in `tests/test_hook_envelopes.py:101`; docstring in `tests/test_consumer_entrypoints.py:281`
      (points at `PASSTHROUGH_REASON`, still valid — verify only)
- [ ] Docs: `bin/bypass-policy` docstring, `skills/config/SKILL.md` (§4 ~L112-121, escape hatches ~L295-300),
      `docs/knowledgebase/command-policy-decision-model.md` (L42-43, L83-91, L139-152, L192, ~L551/570, ~L578-581,
      ~L986-988), escalation_policy / config / reason docstrings
- [ ] Bump version 0.9.0 → 0.10.0 in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (same commit as
      the behaviour change)
- [ ] Full suite green: `cd tests && nix-shell --run pytest`
- [ ] Update status to completed
