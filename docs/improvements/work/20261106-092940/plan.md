# Improvement 20261106-092940: Agent-initiated bypass-policy and add-allow-policy proposals

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T09:29:46+01:00
- Plan finished: 2026-11-06T10:48:55+01:00
- Impl started: 2026-11-06T10:49:26+01:00
- Impl finished: 2026-11-06T10:59:22+01:00
- Merge target: main

## This Improvement's Objective

Make sessions use bypass-policy on their own when no auto-allowed command fits (instead of asking the operator to run
!command), and use add-allow-policy to propose durable rules — up front when a task will need many bypasses, or at
session end when workarounds piled up (handed to the operator when the session is part of a wider process) — with
guidance that produces correct rules.

## Context / Why This Exists

Operator's account (2026-11-06), working in this plugin's own repository (work here does not change the installed plugin
until released):

- **bypass-policy, today:** when a session concludes no auto-allowed command does the job, it prints something like "No
  command allows me to do X. Please run `!{command} {parameters}`" and hands the work to the operator. **Expected:** it
  runs the non-auto-allowed command itself, wrapped: `bypass-policy ls -d bin` (argv form — see Design Decisions).
  `bypass-policy` is not "ask the operator": it is a statement TO THE PLUGIN — "I know no command-policy entry allows
  this, and I am aware of it". command-policy denies every non-auto-allowed command only to GUIDE the session towards a
  similar auto-allowed one; that denial is not a security mechanism meant to shut out Claude Code's other allow
  mechanisms (operator, 2026-11-06).
- **add-allow-policy** (the operator called it "add-command-policy"), **today:** never used unless the operator asks;
  when asked, the written rule is often broken afterwards — the tool takes a literal entry and nothing tells the session
  how to build one properly. **Expected:** used on the session's own initiative to
  - propose a rule UP FRONT when a task will need many bypass-policy invocations — collapsing many operator prompts into
    one;
  - propose a rule AT THE END of a session in which a lot of workaround was necessary that a few (ideally one) rules
    would have collapsed — at the end, so the automated task finishes first. When the session is one step of a wider
    process (e.g. "implement, then hand over to an operator"), the proposal is handed to the operator in that hand-off
    instead of being run.

### What the code does today (measured 2026-11-06)

- **No guidance tells a session to run bypass-policy itself.** SessionStart/SubagentStart render `Config.explain()`
  (`lib/config.py`), whose static tail is `_DECOMPOSITION_ADVISORY` and `_ADD_ALLOW_POLICY_ADVISORY` — neither says
  "when nothing auto-allowed works, run `bypass-policy` instead of asking the operator to run it". The only place both
  routes are explained is the `find-auto-allowed-command` agent's step 4 (`agents/find-auto-allowed-command.md`), which
  describes them but does not direct the caller to act.
- **`bypass-policy` runs argv, not a script string.** `bin/bypass-policy` does `os.execvp(argv[0], argv)`, so
  `bypass-policy ls -d bin` and `bypass-policy echo "some long text"` run exactly as the shell split them, while
  `bypass-policy 'ls -d bin'` exits 127. The argv form is the intended one; the single-string form is not supported.
- **bypass ANALYSIS loses the quoting execution keeps.** `bypass_transform` (`lib/escalation_policy.py`) re-analyses
  `" ".join(argument.text for argument in statement.arguments())`, so a quoted `;`/`>`/`&&` inside one argument
  re-parses as shell syntax. Measured (`experiments/bypass_quoting.py`, allowedCommands `[echo]`, blockedCommands
  `[rm]`): `echo "a; rm x"` → allow, but `bypass-policy echo "a; rm x"` → ask (phantom blocked `rm`), and
  `bypass-policy echo "a > /etc/foo"` → ask (phantom redirect). It only over-escalates, but with sessions bypassing
  routinely it produces wrong prompts with wrong reasons.
- **The canonical add-allow-policy form invites a broken rule.** `ADD_ALLOW_POLICY_CANONICAL_FORM`
  (`lib/reason_renderer.py`) and every doc spell it `… "<command>"`, but the argument is an ENTRY (a bare program name
  or a JSON entry object — `proposal_validation.parse_entry`). A whole command is accepted as a program name:
  `proposal_problems('git status --short', …)` returns `()`, and a config holding that entry DENIES
  `git status --short`. Validation catches only static/described problems, never "this entry does not allow what it was
  written for".
- **Passthrough is not human review — and that is intended.** For a near-miss objection `bypass-policy` returns
  `passthrough`; Claude Code's own rules and permission mode decide. Only a blocked command, a sensitive path or an
  out-of-bounds redirect forces `ask`. This stays as is (Design Decisions: "What a session-initiated bypass hands
  over").

## Proposed Approach

Three parts; the first two are code, the third is the guidance that makes sessions use them.

1. **bypass-policy analyses what it runs.** `bypass_transform` re-analyses the wrapped words' own source span of the
   original command (shfmt `Pos.Offset`/`End.Offset` of the first and last argument after `bypass-policy`) instead of
   `" ".join(argument.text …)`. Runtime (`bin/bypass-policy`, `execvp`) is unchanged; outcomes are unchanged
   (passthrough for near-miss, ask for blocked/sensitive/redirect).
2. **add-allow-policy proves its entry works.** Grammar gains a required, repeatable `--example "<command>"`:
   `add-allow-policy --scope <user|project> --intent "<why>" --example "<command>" [--example …] '<entry>'`. Before
   asking, the transform checks every example against the session's effective config (`Config.decision_for`'s own
   `self`) merged with the proposed entry: each must decide `allow`, and at least one must NOT already be allowed by the
   effective config alone (otherwise the entry adds nothing). Failures deny with new Reasons naming the example and the
   rendered reason it got. The ask dialog lists the examples. The write side (`lib/add_allow_write.py`) re-runs the same
   check against the loaded config (defence in depth, same posture as `--intent`/`proposal_problems`). A bare-string
   entry containing whitespace becomes a static `AllowedCommand` problem ("an entry names a program, not a command — use
   a JSON entry with filters"). The canonical form everywhere says `'<entry>'`, not `"<command>"`.
3. **Sessions learn when to escalate** — prose only (Design Decision "End-of-session trigger"). `Config.explain()`'s
   static tail replaces `_ADD_ALLOW_POLICY_ADVISORY` with an escalation advisory stating the four triggers (see
   Implementation Notes for the text). `agents/find-auto-allowed-command.md` step 4 returns the exact `bypass-policy …`
   line to run when nothing auto-allowed fits. `skills/config/SKILL.md` gets a "Writing an add-allow-policy proposal"
   section.

## Affected Components

- `lib/escalation_policy.py` — `bypass_transform` (source-span re-analysis), `add_allow_policy_transform` /
  `_classify_add_allow_invocation` (`--example`, example verification), module docstring.
- `lib/config.py` — `decision_for` passes the command text (for the source span) and an example verifier (self merged
  with the entry) to the transforms; `_ADD_ALLOW_POLICY_ADVISORY` → escalation advisory.
- `lib/statement.py` — `Command` exposes the byte span of its arguments (from the raw words' `Pos`/`End`).
- `lib/reason.py` / `lib/reason_renderer.py` — new grammar code `missing_example`; new Reasons for an example the entry
  does not allow and for a proposal that changes no example's outcome; `ADD_ALLOW_POLICY_CANONICAL_FORM` updated.
- `lib/allowed_command.py` — whitespace-in-bare-program problem.
- `lib/add_allow_write.py` — `--example` (argparse, `action="append"`, required), write-side re-check.
- `agents/find-auto-allowed-command.md`, `skills/config/SKILL.md`, `README.md`,
  `docs/knowledgebase/command-policy-decision-model.md` (grammar table, bypass re-analysis).
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — version bump 0.7.0 → 0.8.0 in the same commit as the
  content change (CLAUDE.md: "Version Bumps Are Load-Bearing").

## Implementation Notes

- **Example verification receives its data.** `add_allow_policy_transform` must not load config itself:
  `Config. decision_for` hands it a callable (`decide_with_entry(entry, example) -> PermissionDecision`) built from
  `self` merged with a one-entry overlay, plus `self.decision_for` for the "already allowed" check. Tests exercise it
  with `Config.from_dict` — no files.
- **Examples are commands, not escalations.** An example that itself starts with `bypass-policy`/`add-allow-policy` is
  verified like any other command (it will not be `allow` and so fails) — no special case.
- **Source span is byte-based.** shfmt offsets are byte offsets; slice `command.encode()` and decode. When the statement
  was built after `_parse_and_normalize`'s heredoc normalisation, take the span from the text that was parsed. If no
  span is available (should not happen for a `Command`), fall back to today's join rather than raising.
- **Escalation advisory text (draft, to be tightened during implementation):**
  ```
  ESCALATION - when no auto-allowed command does the job:
  - Do not ask the operator to run a command (no "please run !cmd"). Run it yourself as
    bypass-policy <program> [args...] - this tells command-policy you know no entry allows it; Claude Code's own
    permission rules then decide.
  - Before starting a task that will need many bypass-policy calls of the same shape, propose ONE durable rule first:
    add-allow-policy --scope user --intent "<why>" --example "<command>" '<entry>'
  - When a session needed many bypasses or workarounds that one rule would have collapsed, propose that rule as the
    LAST step, after the task itself is done.
  - If your work is handed on afterwards (to an operator, an orchestrator, a parent agent), do not run add-allow-policy:
    put the exact command in your hand-off instead.
  Load command-policy:config before writing an entry - an entry is a program name or a JSON object, never a command line.
  ```
- **Skill section content:** entry vs command (with the measured `"git status --short"` failure as the warning example),
  single-quote JSON entries so inner double quotes survive, choose `--example`s that are the real commands that needed
  bypassing, default to `--scope user`, how to read an example-refusal and fix the entry.

- **As implemented (2026-11-06):** `bypass_transform` gained an optional `command_text` (falls back to the old join when
  absent); `Command.arguments_source_text(command)` slices the byte span. The whitespace problem applies to ANY entry's
  `program` (bare string or JSON), not only bare strings. The transform takes two callables, `decide_example` and
  `decide_example_with_entry` (`Config.decision_for_with_entry`); `example_objections_for` is shared with the write side
  (`lib/add_allow_write.py`, which loads config via `load_config_from_environment`). `render_clauses` was added to the
  renderer so an example's failure text embeds without a second equivalence pointer. A sensitive variable in a wrapped
  command stays `passthrough` (not `ask`) - unchanged behaviour. Entrypoint tests now isolate `HOME`, since the real
  user config would otherwise make a proposal "change nothing". The drift test compares canonical forms modulo
  whitespace because a formatter hook re-wraps markdown.

## Test Architecture

`tests/` with pytest (`cd tests && nix-shell --run pytest`). Unit tests are pure (`Config.from_dict`, no files):

- `tests/test_escalation_policy.py` / `tests/test_config.py` — bypass re-analysis: `bypass-policy echo "a; rm x"` and
  `bypass-policy echo "a > /etc/foo"` allow under allowedCommands `[echo]`, blockedCommands `[rm]`;
  `bypass-policy cat "$X"` still sees the variable; a wrapped blocked command still asks. add-allow: missing `--example`
  denies (`missing_example`); an example the merged config does not allow denies naming it; all examples already allowed
  denies; a valid proposal asks and the reason lists the examples; a whitespace bare-program entry denies.
- `tests/test_allowed_command.py` — whitespace problem.
- `tests/test_reason_renderer.py` — new reasons render; canonical form text.
- `tests/test_escalation_entrypoints.py` — via the existing `run_entrypoint` fixture: `bin/add-allow-policy` refuses to
  write without `--example` and when an example is not allowed; writes when valid.
- `tests/test_config.py` — `explain()` ends with the escalation advisory (bypass-policy, up-front, end-of-session,
  hand-off lines).
- `tests/test_skill_drift.py` — extend: the skill and the agent name the canonical form verbatim
  (`ADD_ALLOW_POLICY_CANONICAL_FORM` in both), so the docs cannot drift from the grammar again.

## Assumptions

- **bypass-policy with the whole command as one quoted string runs that command** — refuted (bypass-policy
  bin/bypass-policy 'ls -d bin' exits 127: execvp treats the whole string as the program name)
- **add-allow-policy refuses an entry that would not allow the command it was written for** — refuted
  (proposal_problems('git status --short','user',None) returns (); Config.from_dict({'allowedCommands':['git status
  --short']}).decision_for('git status --short') is deny)
- **bypass_transform analyses the same command execvp runs** — refuted (experiments/bypass_quoting.py: with
  allowedCommands [echo], blockedCommands [rm]: 'echo "a; rm x"' -> allow, but 'bypass-policy echo "a; rm x"' -> ask and
  'bypass-policy echo "a > /etc/foo"' -> ask; the joined text re-parses quoted ; and > as shell syntax. Over-escalation
  only.)

## Design Decisions

### What a session-initiated bypass hands over

- **Chosen:** keep today's outcomes — `passthrough` for ordinary near-miss objections, forced `ask` only for a blocked
  command, a sensitive path or an out-of-bounds redirect.
- **Rationale (operator):** "bypass-policy isn't meant as 'ask Operator' it is literally just an information to the
  plugin 'yeah I know this isn't going to pass using a command-policy, I'm aware of that.' This is necessary because the
  command-policy actually rejects any non-auto-allowed command right now to guide the session towards similar but auto
  allowed commands! the rejection here is _not_ a security mechanism actively attempting to shut out other allow
  mechanisms."
- **Rejected:** always force `ask` for a bypass, so every session-initiated escalation reaches the operator.
- **Date:** 2026-11-06

### bypass-policy invocation form

- **Chosen:** the argv form only — `bypass-policy <program> [args...]`, executed via `execvp` exactly as today. Fix the
  ANALYSIS side instead: re-analyse the wrapped words' own SOURCE TEXT — the slice of the original command from the
  first wrapped word's shfmt `Pos.Offset` to the last one's `End.Offset` (byte offsets, measured present:
  `echo 'bypass-policy echo "a; rm x" $X' | shfmt --to-json` gives 0–13, 14–18, 19–28, 29–31) — so quoting AND
  unknowable content (`$X`, `$(…)`) survive into the re-analysis exactly as the shell will see them.
- **Rationale (operator):** "the expected version is `bypass-policy ls -d bin`" — execvp already preserves quoted
  arguments; the quoting problem is the analysis's re-join only.
- **Rejected:** a single script-string form (`bypass-policy 'cmd && cmd'` run via `bash -c`). Also rejected (planner,
  2026-11-06): `shlex.join` over `Argument.text` — `.text` is `""` for `$X`/`$(…)`, so `bypass-policy cat "$X"` would
  re-analyse as the literal `cat ''`, erasing the unknowability the containment rules depend on.
- **Date:** 2026-11-06

### Making add-allow-policy rules correct

- **Chosen:** a required, repeatable `--example "<command>"`; add-allow-policy refuses unless the current effective
  config PLUS the proposed entry allows every example. Also: a bare program name containing whitespace becomes an entry
  problem, and every rendering of the canonical form says `"<entry>"` instead of `"<command>"`.
- **Rationale:** rationale not captured (operator: "sounds like a good addition. Let's go with A)").
- **Rejected:** fixing only the documentation/skill guidance.
- **Date:** 2026-11-06
- **Details (planner defaults, presented 2026-11-06, not objected to):** at least one `--example` required; examples
  verified against the effective user+project config plus the new entry; refused when the entry changes no example's
  outcome; examples listed in the ask dialog.

### End-of-session trigger

- **Chosen:** prose guidance only — the session-start/subagent-start escalation advisory names WHEN to propose (up
  front, at the end, hand-off instead of running).
- **Rationale (operator):** "I believe so far it was mentioned but no indication was given for what reason it should be
  run. Since we now have the reasons specified I have hopes that this will be enough"
- **Rejected:** a `Stop`/`SubagentStop` hook counting the session's bypass-policy invocations from the transcript and
  blocking the stop once with a reminder past a threshold.
- **Date:** 2026-11-06

## Success Criteria

- `bypass-policy echo "a; rm x"` allows under allowedCommands `[echo]` + blockedCommands `[rm]`; a genuinely wrapped
  blocked command still forces `ask`; a wrapped near-miss still passes through.
- `add-allow-policy` without `--example` is denied with `missing_example`; with an example the merged config + entry
  does not allow, it is denied naming that example and its reason; with `'git status --short'` as a bare entry it is
  denied (whitespace problem); a correct proposal asks, listing its examples.
- `bin/add-allow-policy` re-checks the examples before writing and writes nothing when one fails.
- SessionStart/SubagentStart output contains the escalation advisory with all four triggers.
- The finder agent, config skill, README and knowledgebase article state the new grammar; a drift test pins the
  canonical form in the skill and the agent.
- Plugin version is 0.8.0 in both manifests; full suite green.

## Implementation TODO

- [x] Update status to in-progress
- [x] bypass re-analysis from the source span: `lib/statement.py` (argument byte span on `Command`),
      `lib/escalation_policy.py` (`bypass_transform`), `lib/config.py` (`decision_for` passes the parsed text); tests in
      `tests/test_statement.py`, `tests/test_escalation_policy.py`, `tests/test_config.py`
- [x] Whitespace-in-bare-program problem: `lib/allowed_command.py`; `tests/test_allowed_command.py`,
      `tests/test_proposal_validation.py`
- [x] `--example` grammar + `missing_example`: `lib/escalation_policy.py` (`_classify_add_allow_invocation`),
      `lib/reason.py`, `lib/reason_renderer.py` (explanation, `ADD_ALLOW_POLICY_CANONICAL_FORM`);
      `tests/test_escalation_policy.py`, `tests/test_reason_renderer.py`
- [x] Example verification on the ask path: `lib/config.py` (verifier from `self` + one-entry overlay),
      `lib/escalation_policy.py` (`add_allow_policy_transform`, dialog lists examples), new Reasons in `lib/reason.py` /
      `lib/reason_renderer.py`; `tests/test_escalation_policy.py`, `tests/test_config.py`
- [x] Write-side `--example` + re-check: `lib/add_allow_write.py`; `tests/test_escalation_entrypoints.py`
- [x] Escalation advisory replacing `_ADD_ALLOW_POLICY_ADVISORY`: `lib/config.py`; `tests/test_config.py`,
      `tests/test_hook_envelopes.py` (if it pins the text)
- [x] Agent step 4 returns the exact `bypass-policy …` line: `agents/find-auto-allowed-command.md`
- [x] Config skill "Writing an add-allow-policy proposal" + escape-hatch reference update: `skills/config/SKILL.md`;
      drift test pinning the canonical form in skill and agent: `tests/test_skill_drift.py`
- [x] Docs: `README.md`, `docs/knowledgebase/command-policy-decision-model.md` (grammar table incl. `missing_example`,
      bypass source-span re-analysis), module docstrings of `lib/escalation_policy.py`, `bin/add-allow-policy`,
      `bin/bypass-policy`
- [x] Version bump 0.7.0 → 0.8.0 in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, in the same
      commit as the content change; run `cd tests && nix-shell --run pytest`
- [x] Update status to completed