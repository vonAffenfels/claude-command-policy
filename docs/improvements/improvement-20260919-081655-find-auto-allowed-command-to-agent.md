# Improvement 20260919-081655: Convert find-auto-allowed-command to a Zero-Context Agent

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-19
- Updated: 2026-09-20
- Plan started: 2026-09-18T23:13:53+02:00
- Plan finished: 2026-09-19T08:16:55+02:00
- Impl started: 2026-09-20T13:25:39+02:00
- Impl finished: 2026-09-20T13:39:37+02:00

## This Improvement's Objective

Convert the command-policy equivalence search from a same-conversation SKILL into a zero-context AGENT — the shape
originally intended — and stop it shelling out to `explain-policy` for information it is already handed. Today
`packages/command-policy/skills/find-auto-allowed-command/SKILL.md` is loaded by the Skill tool into the MAIN
conversation, and its Procedure step 1 is "Run `explain-policy`". Both halves are wrong: (1) the vehicle was never
actually chosen — trunk `20260914-195111`'s decision quotes the operator as "reference a skill OR AGENT", leaf
`20260915-010959` carried "skill/agent" forward verbatim, and leaf `20260915-011123` collapsed it to a skill with NO
Design Decision entry, on a flat input-plumbing-convenience assertion ("the invoking session already has the denied
command in its own context ... so it need not accept parameters") inside a leaf whose own title and charter already
presupposed "skill"; (2) the rendered effective config is ALREADY injected into the main session by
`bin/command-policy-render-session-start` and into EVERY subagent by `bin/command-policy-render-subagent-start` via
`additionalContext`, so running `explain-policy` re-fetches what the reasoner already holds, burning a Bash call and
roughly sixty lines of main-conversation context per denial. An agent gets those rules automatically from zero context,
which is the isolation the operator wanted so the equivalence search is not biased by the intent the main session has
already formed. Note this isolation is also the stated premise of a rule that is live in the code but currently
unjustified: leaf `20260915-011123`'s Design Decision skipping candidate pre-verification against
`Config.decision_for()` argues from "the caller is already an agent starting from empty context" — a property the
shipped skill does not have, so that decision must be revisited as part of this conversion rather than inherited. There
is no `packages/command-policy/agents/` directory yet; the agent was simply never written. The frozen pointer string
`command-policy:find-auto-allowed-command` (`lib/reason_renderer.py:36`) is vehicle-neutral, since skills and agents are
both addressed as `plugin:name`, so the contract name can likely survive unchanged — confirm rather than assume. FOLDED
IN (operator decision, carried from the now-superseded improvement `20260918-231406`): `explain-policy`'s output must
distinguish "no config file found" from "config present but empty". `lib/config_loader.py:43` already knows whether each
file existed and discards it, returning `Config.defaults()` for an absent file — byte-identical to a present-but-empty
one — so `Config.explain()` prints a silent empty structure that names neither of the two paths searched nor
`migrate-config`. Decide the fate of the existing SKILL.md (delete outright versus retain as a user-invocable entry
point) and whether the agent needs its own `tools:` restriction. ALREADY SETTLED, do not reopen: deny-by-default stays;
`explain-policy` gets NO standing engine exemption and no shipped default `allowedCommands` entry (the first such entry
would break "deny-by-default with an empty config" and was deliberately avoided); the `bypass-policy` escape hatch is
unchanged and correct, and `bypass-policy explain-policy` is the accepted answer for the rare stale-context case where a
mid-session config write makes the injected snapshot wrong. Tests must be non-vacuous, matching the standard set by the
last two security improvements in this trunk (each verified by running new tests against pre-fix code).

## Context / Why This Exists

**Origin / trigger:** Two-step. The session began on a different complaint — `explain-policy` being denied by
deny-by-default when no config exists — and while auditing that, the operator recognised the deeper cause and stated it
directly: _"I believe my original design was to advertise a find-auto-allow-command AGENT which gets its info directly
from the SubagentStart hook and decides on an auto allow command matching its prompt just as intelligently as the main
context but with no context at all to distract it."_ The archaeology then confirmed the vehicle was never deliberately
chosen (see Objective). The original complaint dissolved on the operator's own observation that `explain-policy` is
never needed by the model at all, because the config is already in context.

**Consumer(s) of the output:** The model itself, in the main session, at the moment a command is denied — reached via
the unconditional pointer appended to every non-empty deny reason (`lib/reason_renderer.py:36`). It is the
self-correction half of the deny+hint outcome model. Not a human-facing surface.

**Adjacent systems already covering part of the need:** `bin/command-policy-render-subagent-start` already injects the
full rendered config into every subagent via `additionalContext` (`SubagentStart` is registered with no matcher, so it
fires for all of them) — this is the infrastructure the agent design depends on, and it already exists and works.
`bin/command-policy-render-session-start` does the same for the main session. `bypass-policy` remains the escape hatch
for anything neither route covers. `Config.explain()` is the shared rendering surface all of it sits on.

## Proposed Approach

Five changes, in dependency order. The first three are the conversion; the fourth is the folded-in `explain-policy` fix,
independent of the others; the fifth is documentation and packaging.

**1. Create the agent** (`packages/command-policy/agents/find-auto-allowed-command.md`, the package's FIRST `agents/`
directory). Frontmatter: `model: sonnet`, `description` describing when to delegate, and `tools:` set to grant NOTHING —
the agent reasons purely over what it is already handed, which makes "it never shells out to `explain-policy`" an
enforced property of the tool surface rather than an instruction prose could fail to hold. Body carries the reasoning
procedure migrated from the skill, with the decisive change: step 1 stops being "run `explain-policy`" and becomes "read
the rendered rules already in your context" (the `SubagentStart` hook put them there at dispatch). Retain the skill's
"deliberately does NOT verify its own candidate" section — see the Design Decision reaffirming it, whose premise only
now holds. Add the input contract the skill never needed: the denied command and its deny reason arrive in the PROMPT,
and when they do not, the agent says so plainly instead of guessing at what was denied.

**2. Delete the skill** (`packages/command-policy/skills/find-auto-allowed-command/`, whole directory). It is
`user-invocable: false`, so the deny pointer is its only caller; once that points at the agent, nothing can reach it.

**3. Reword the deny pointer** (`lib/reason_renderer.py:36`) to name the vehicle explicitly, and correct the module
docstring above it (lines 8-15), which currently describes the target as a skill. Blast radius is small and was
measured: the string is defined once, used once (line 109), and NO test asserts its full text —
`test_reason_renderer.py:33` asserts only the substring `find-auto-allowed-command`, which any rewording keeps. The
101KB decision-specification suite asserts `Reason` TYPES, not rendered pointer prose, so it is untouched.

**4. Make `explain-policy` distinguish "no config found" from "config present but empty"** (the folded-in item).
`lib/config_loader.py:43` already tests `path.exists()` and discards the answer, returning `Config.defaults()` for an
absent file — byte-identical to a present-but-empty one. Carry that knowledge instead: a small value object (following
the package's existing style, e.g. `name_collection.py` / `path_config.py`) recording per layer which path was searched
and whether it was present, unioned on merge like every other collection, exposed through `Config.explain()`. Render it
FIRST in the explain output, because "no config file exists at either scope" is what EXPLAINS the empty sections beneath
it, and name both paths plus `migrate-config` as the next step. Keep it silent when at least one file was found, so the
ordinary case gains no noise.

**5. Documentation and packaging.** Update `docs/knowledgebase/command-policy-decision-model.md` (its "Two Consumer
Skills" section at line 459, plus lines 114, 503 and the glossary row at 601) so it describes one skill and one agent.
Update the `command-policy` paragraph in root `CLAUDE.md`. Bump `version` in BOTH
`packages/command-policy/.claude-plugin/plugin.json` and the matching entry in root `.claude-plugin/marketplace.json`
(currently `0.3.1` in both; a new agent plus a removed skill is a minor bump to `0.4.0`) — the two must never disagree.

## Affected Components

**Files:**

- `packages/command-policy/agents/find-auto-allowed-command.md` (NEW — first `agents/` dir in this package)
- `packages/command-policy/skills/find-auto-allowed-command/SKILL.md` (DELETE, with its directory)
- `packages/command-policy/lib/reason_renderer.py` (reword `EQUIVALENCE_POINTER`, correct module docstring)
- `packages/command-policy/lib/config_loader.py` (stop discarding per-layer path/presence)
- `packages/command-policy/lib/config.py` (carry the new value object through construction, `_replace`, `merged_with`,
  and `explain()`)
- `packages/command-policy/lib/<new value object module>.py` (NEW — per-layer searched-path/presence record)
- `packages/command-policy/tests/test_config_loader.py`, `test_config.py`, `test_reason_renderer.py`, `test_scaffold.py`
  (extend)
- `packages/command-policy/tests/test_permission_decisions.py` (verify untouched — see Implementation Notes)
- `docs/knowledgebase/command-policy-decision-model.md`
- `CLAUDE.md` (root — the `command-policy` bullet)
- `packages/command-policy/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (version bump, in lockstep)

**Experiment artifacts (KEEP — evidence behind the model decision, commit with the plan):**

- `docs/improvements/experiments/20260919-081655/results.md` — the 18-run model comparison and its caveats
- `docs/improvements/experiments/20260919-081655/probe.py` — harness: renders authentic deny reasons from the live
  config, and scores candidate commands through the real engine
- `docs/improvements/experiments/20260919-081655/cases.json` / `answers.json` — the six cases and the 18 collected
  responses with timings

**Files to delete:**

- `packages/command-policy/skills/find-auto-allowed-command/SKILL.md`

**Classes/Functions:**

- `EQUIVALENCE_POINTER` (`lib/reason_renderer.py:36`) — the one definition of the pointer clause
- `render()` (`lib/reason_renderer.py:109`) — its only consumer
- `_load_layer(path, layer)` (`lib/config_loader.py:41`) — where presence is currently discarded
- `Config.__init__` / `_replace` / `merged_with` / `explain` / `_explain_allowed_commands` (`lib/config.py`) — the
  construction, copy-on-write, union and rendering path the new record threads through

## Implementation Notes

**Testing Strategy:** TDD (red-green-refactor). The repository's `tdd` skill governs test work; invoke it before writing
the first test. Run with `cd packages/command-policy/tests && nix-shell --run pytest`.

**BASELINE — know it before you start.** The suite stands at 634 passed with exactly TWO pre-existing failures, both on
a missing `xargs` parser and both owned by a SEPARATE improvement:
`test_a_nested_command_filter_composes_with_other_filters_across_entries` and
`test_propagation_does_not_see_operands_arriving_on_stdin`. They must stay red — do not fix them here. ANY other failure
is yours. Also run `packages/shfmt-permissions/tests` (751 passed) to confirm the old engine is untouched.

**Non-vacuous tests are the standard, not a preference.** The last two security improvements in this trunk were each
verified by running the new tests against PRE-FIX code, one with 11 of 11 genuinely failing. Do the same: write the
test, watch it fail against current code, then implement. A test that passes before the change is evidence of nothing.

**The agent itself is not unit-testable, so guard it structurally.** Its reasoning quality cannot be asserted in pytest,
but its EXISTENCE and the skill's ABSENCE can — add a scaffold-level test (`test_scaffold.py`) asserting
`agents/find-auto-allowed-command.md` is present and `skills/find-auto-allowed-command/` is gone. That test fails
against current code in both halves, which is what makes it worth having.

**Why the pointer rewording is safe, measured rather than assumed:** `rg -c "auto-approved alternative"` finds the
clause in exactly one lib file (`reason_renderer.py`, definition + use) and in NO test or doc.
`lib/session_audit.py:48`'s superficially similar `DENY_HEADING` is a different string and must not be swept up in the
edit. After rewording, re-run the full suite and confirm the count of failures is still exactly the two baseline ones.

**`tools:` granting nothing is the point, not an oversight.** Per `docs/knowledgebase/agent-frontmatter.md`, `tools:` is
a whitelist and OMITTING it inherits everything — so the agent must set it explicitly, not leave it off. This is what
makes the no-shell-out property enforced rather than merely instructed, mirroring how
`packages/improvement/agents/code-research.md` documents its own `tools:` line as a real restriction rather than a
claim.

**The agent's prompt is its whole world.** `agent-frontmatter.md` is explicit that an agent sees no parent history, so
the caller must pass the denied command and the deny reason in the prompt. The skill needed no input contract precisely
because it ran in the calling conversation; the agent does. Specify it in the agent body AND make the agent degrade
gracefully when it is missing.

**Config freshness is a property worth preserving deliberately.** Measured this session: `SubagentStart` renders at EACH
dispatch, so the agent's copy of the rules is always current, whereas the main session's `SessionStart` copy is frozen
at session start and goes stale after any mid-session config write. This is a correctness advantage the skill vehicle
structurally could not have. Do not "optimise" it away by, for example, passing the main session's stale copy into the
prompt.

**Do not reintroduce a static equivalence map.** Trunk `20260914-195111` and `_derive_filter_alternative` both refuse to
author a command-equivalence table because it "would rot like hand-written prose". The agent reasons over the LIVE
rendered rules for the same reason. This constraint survives the vehicle change intact.

**Added during implementation — the `unverified` "empty `tools:`" assumption is settled, and NOT the way planning hedged
for.** Planning's Assumptions section anticipated one failure mode if empty meant something other than "grants nothing":
that it might mean "inherits everything" instead, in which case the fallback was "the narrowest explicit non-empty
whitelist." The actual failure mode, confirmed via Claude Code's own subagent documentation
(`https://code.claude.com/docs/en/sub-agents.md`, retrieved via the `claude-code-guide` agent, 2026-09-20) is harder
than that: **a fully empty resolved `tools:` list makes Claude Code refuse to spawn the agent at all** ("Agent would be
spawned with zero tools"). A live dispatch of the real, newly-created agent to confirm this directly was attempted and
found structurally impossible in this same session — plugin agent files are not hot-reloaded (this package's own
`packages/command-policy/.claude-plugin/plugin.json` is at `0.3.3` while the installed plugin cache serving this very
session is at `0.3.0`), exactly the limitation planning's own Assumption already recorded when it could not probe this
from `.claude/agents/`. The shipped agent therefore carries `tools: Read` — the narrowest non-empty grant available, per
the plan's own previously-REJECTED-but-now-necessary fallback. The load-bearing property is unchanged: the agent has no
`Bash`, so it structurally cannot run `explain-policy` or invoke `Config.decision_for`; `Read` cannot execute anything
and so cannot reach either. See the "What tools the agent gets" Design Decision below for the corrected rationale, and
the corresponding Assumption entry for the settled (not merely re-hedged) finding.

## Test Architecture

**Existing helpers to reuse** (`packages/command-policy/tests/conftest.py`):

- `run_entrypoint` — invokes a `bin/` entrypoint as a subprocess with an env overlay; used by `test_scaffold.py` and
  `test_consumer_entrypoints.py`. Its env override is how migration tests already redirect `HOME` to a pytest
  `tmp_path`, which is exactly the mechanism the "no config at either scope" case needs.
- `cwd_pinned_inside_project` — pins `cwd` and `CLAUDE_PROJECT_DIR` together, then restores both. Needed to exercise the
  project-scope config path without touching the real repo.

**Fantasy callsites** (what the tests will want the production API to look like):

- `Config.from_dict({}).explain()` starting with a line that names both searched paths — the empty-config case as seen
  by a reader.
- `load_config(<absent user path>, <absent project path>).explain()` versus
  `load_config(<file containing {}>, <absent>).explain()` — the two must differ, which is the whole point of the change.

**New helpers to create:**

- A fixture (or plain `tmp_path` usage) producing the three interesting layer combinations: both files absent, one
  present-but-empty, one present with content. Only add a named fixture if the same setup appears in three or more
  tests; two occurrences do not earn an abstraction.

**Testability-driven production decisions:**

- The searched-path/presence record must be a plain value object carried on `Config`, not read from the filesystem at
  `explain()` time — otherwise `explain()` becomes untestable without real files on disk, and the package's existing
  separation (`config_loader.py` is pure I/O, `config.py` carries no I/O) would be violated.

## Assumptions

- **`SubagentStart` fires for Task-dispatched plugin agents and injects the full rendered config** — confirmed (live
  probe: a dispatched subagent quoted back "SubagentStart hook additional context: AUTO-ALLOWED COMMANDS:" and reported
  roughly 56 entries, naming `explain-policy`, `bypass-policy` and `improvement-plan-context`)
- **The `SubagentStart` copy is rendered per dispatch, so it is fresher than the session's `SessionStart` copy** —
  confirmed (the probe listed three entries added to the user config mid-session that the planning session's own
  `SessionStart` block does not contain)
- **`explain-policy` is denied under an empty config while `bypass-policy explain-policy` is passthrough** — confirmed
  (executed `Config.from_dict({}).decision_for(...)` for both: `ProgramNotAllowListed` versus "analysis skipped by
  design")
- **The deny pointer's full text is asserted in no test, so rewording it breaks nothing** — confirmed
  (`rg -c "auto-approved alternative"` matches only `reason_renderer.py`'s definition and its single use;
  `session_audit.py:48`'s `DENY_HEADING` is a different string; `test_reason_renderer.py:33` asserts only the substring
  `find-auto-allowed-command`)
- **`config_loader.py` discards per-layer presence, making an absent config indistinguishable from an empty one** —
  confirmed (`_load_layer` returns `Config.defaults()` on `not path.exists()`, the same object an empty `{}` produces)
- **`Config.decision_for` is implemented and live, contrary to root CLAUDE.md** — confirmed (executed it directly and
  got real decisions; the CLAUDE.md claim that it "still raises `NotImplementedError`" is stale — see Observed during
  exploration)
- **Agents and skills are both addressed as `plugin:name`, so the contract name survives the vehicle change** —
  confirmed (`docs/knowledgebase/agent-frontmatter.md:43` specifies `subagent_type` as `{plugin-name}:{agent-name}`, and
  this session's available-agents list shows that form for every plugin agent)
- **An explicitly-empty `tools:` frontmatter grants NO tools rather than inheriting everything** — REFUTED, by a harder
  finding than the one this assumption hedged against (settled 2026-09-20 via Claude Code's own subagent documentation,
  since a live dispatch of the real agent remained structurally impossible for the same reason recorded here at planning
  time — plugin agents are not hot-reloaded and the installed plugin cache serving this very session predates this
  package's version). A fully empty resolved `tools:` list does not mean "grants nothing" AND does not mean "inherits
  everything" either — it means Claude Code refuses to spawn the agent at all ("Agent would be spawned with zero
  tools"). The shipped agent uses `tools: Read`, the narrowest non-empty grant, per the plan's own previously-rejected
  fallback; see the corrected "What tools the agent gets" Design Decision and the Implementation Notes entry added
  during implementation.

- **`sonnet` is the right model for this agent — haiku is materially worse and opus buys nothing** — confirmed (18-run
  measurement recorded in `docs/improvements/experiments/20260919-081655/results.md`: every model is engine-verified
  auto-allowed 5/5 with a correct `NONE` on a blocked control, but functional correctness splits sonnet 6/6, opus 6/6,
  haiku 4/6, and haiku is also ~2x slower than both)
- **A model can produce a candidate the engine auto-allows that nonetheless returns the wrong result** — confirmed (two
  haiku answers were allowed by the live engine yet verified wrong by running them: a `sort -rn` missing `-t: -k2`
  ranked reverse-alphabetically rather than by count, and a `find ... -type f` omitted all 15 directories when the goal
  was the directory structure; this is why the agent's own no-self-verification decision rests on the CALLER re-running
  the candidate, not on the candidate being trustworthy)

## Design Decisions

### Whether read-only diagnostics get a standing exception from deny-by-default

- **Chosen:** No standing exception for any command. Advertise the AGENT instead; `explain-policy` needs no exemption
  because nothing that reasons about policy has to run it.
- **Rationale:** Operator: _"advertise the use of the agent instead. The explain-policy is never needed anymore because
  the information is already in the context of the main session and all agents anyway."_ Verified: the rendered config
  is injected into the main session at `SessionStart` and into every subagent at `SubagentStart`, so a `Bash` call to
  `explain-policy` re-fetches what the reasoner already holds. Removing the need is strictly better than granting an
  exception to satisfy it — it leaves deny-by-default literally intact with an empty config, and creates no permanent
  self-allowed command.
- **Rejected alternatives:** A hardcoded engine exemption for `explain-policy` alongside the existing
  `bypass-policy`/`add-allow-policy` transformers in `escalation_policy.py` (would have been the least-bad exception,
  extending an established mechanism, but is unnecessary once the need is removed); shipped default `allowedCommands`
  entries merged under any user config (would have created the first shipped allow-list entry the trunk has ever had,
  making "deny-by-default with an empty config" no longer literally true, and a user could delete it and re-break their
  own recovery); a documentation-only fix pointing the skill at `bypass-policy explain-policy` (leaves the redundant
  shell-out in place); the original brief's option (c), the bin script short-circuiting the hook for itself, which is
  impossible — the `PreToolUse` hook denies before the script ever executes.
- **Date:** 2026-09-19

### How the stale in-context config snapshot is handled

- **Chosen:** Leave it. `bypass-policy explain-policy` covers the rare case, and no engine change is made for it.
- **Rationale:** The operator chose the no-change option after the staleness gap was demonstrated live (the
  `SessionStart` block in the planning session predated three entries the operator added mid-session, while live output
  showed them). A subsequently-measured fact makes this cheaper than it looked: the `SubagentStart` copy is rendered at
  EACH DISPATCH, not once per session, so an agent always reasons from current rules. Staleness therefore afflicts only
  the main session's own copy, never the equivalence search itself once it is an agent.
- **Rejected alternatives:** Re-inject a refreshed config after an `add-allow-policy` write completes (fixes the cause,
  but is unnecessary for the equivalence search and adds a new push path); grant `explain-policy` a standing exemption
  purely to serve live re-reads (a permanent exception for a narrow job); treat staleness as out of scope and silent
  (rejected — it is recorded here instead).
- **Date:** 2026-09-19

### Fate of the existing find-auto-allowed-command SKILL.md

- **Chosen:** Delete it outright. The agent fully replaces it.
- **Rationale:** The skill is `user-invocable: false`, so the deny-reason pointer is its ONLY caller. Once that pointer
  routes to the agent, the skill is unreachable code — precisely the permanently-stale artefact the planning rules say
  not to leave behind. Deleting also keeps the reasoning procedure in exactly one file, so the agent's instructions and
  a leftover skill copy cannot drift apart.
- **Rejected alternatives:** Keep it but flip it to user-invocable so a human can ask directly (costs a second copy of
  the procedure that drifts); reduce it to a thin stub that dispatches the agent (avoids drift, but adds an indirection
  layer for a skill nothing currently calls).
- **Date:** 2026-09-19

### Scope of the superseded explain-policy improvement

- **Chosen:** Fold improvement `20260918-231406`'s one surviving item (distinguishing "no config file found" from
  "config present but empty") into THIS improvement, and drop that improvement rather than implement it separately.
- **Rationale:** Operator decision. After the exception question dissolved, `20260918-231406` had exactly one item left
  — a small loader/`explain()` output fix — which was not worth its own plan-implement-review cycle.
- **Rejected alternatives:** Keep `20260918-231406` as a narrowed standalone improvement (cleaner separation, but two
  work items where one suffices); drop the item entirely on the grounds that the no-config output is rarely seen
  (rejected — a human running `explain-policy` in their own terminal bypasses hooks entirely and still meets the useless
  output).
- **Date:** 2026-09-19

### Which model the agent runs on

- **Chosen:** `sonnet` (pinned), not `inherit`.
- **Rationale:** Operator chose `sonnet`; the choice was then MEASURED rather than left to judgement, and the
  measurement confirms it. Eighteen runs (6 denied commands of increasing complexity x 3 models, zero context, config
  delivered via the real `SubagentStart` hook) are recorded in
  `docs/improvements/experiments/20260919-081655/results.md`. Two findings decided it. First, "is the proposed candidate
  auto-allowed" is SATURATED — every model scored 5/5 engine-verified auto-allowed plus a correct `NONE` on a blocked
  negative control, so that axis cannot choose a model. Second, "does the candidate actually do the job" separates them:
  sonnet 6/6, opus 6/6, haiku 4/6. Both haiku failures were auto-allowed commands that silently return the WRONG RESULT
  — the worst available failure shape, since the engine waves them through and the output looks plausible (it dropped
  `-t: -k2` from a `sort`, ranking reverse-alphabetically instead of by count, and added `-type f` to a `find`, omitting
  every directory when the goal was the directory structure). Haiku was also the SLOWEST model, ~2x sonnet and opus even
  after discarding a 40s outlier. Sonnet and opus tie on accuracy and latency (~4s), so the remaining difference is
  cost, which favours sonnet.
- **Rejected alternatives:** `haiku` — rejected on measured evidence, not suspicion: least accurate AND slowest of the
  three; `inherit` (matches the stated intent most literally, but makes every denial's follow-up cost track an
  arbitrarily expensive parent, and the measurement shows opus buys no accuracy over sonnet here); `opus` pinned (equal
  accuracy and latency to sonnet at higher cost)
- **Date:** 2026-09-19

### What tools the agent gets

- **Chosen (REVISED during implementation, 2026-09-20):** `tools: Read` — not the literal empty grant planning intended.
  Planning's own design decision below is preserved for its record of the original reasoning; this supersedes only its
  "Chosen" line.
- **Original planning decision (2026-09-19), now impossible to ship literally:** None — `tools:` set explicitly to grant
  nothing, on the reasoning that the agent already holds everything it needs (rendered rules via `SubagentStart`, the
  denied command via its prompt) and that granting nothing makes "never shells out to `explain-policy`" an enforced
  tool-surface property rather than an instruction the agent could drift from, mirroring
  `packages/improvement/agents/code-research.md`'s own read-only charter.
- **Why it changed:** Confirmed during implementation (see Implementation Notes) that Claude Code refuses to spawn an
  agent whose resolved `tools:` list is empty at all — "Agent would be spawned with zero tools" — so the literal empty
  grant is not a stricter version of the intended design, it is a non-shippable one. `Read` is the narrowest non-empty
  grant available. The property that actually mattered survives fully: `Read` carries no code-execution capability, so
  the agent still structurally cannot run `explain-policy` or invoke `Config.decision_for` — the enforcement claim is
  corrected to "no `Bash`" rather than "no tools," which is the fact that was actually load-bearing all along. `tools:`
  still must be set explicitly rather than omitted, because omitting it inherits EVERYTHING including `Bash`.
- **Rejected alternatives:** `Read` as a fallback for a missing/truncated injection (planning's own words — rejected at
  planning time as adding a rarely-run, rarely-tested path; adopted anyway during implementation once the literal empty
  grant proved non-shippable, so this alternative is no longer rejected in the final shipped agent); `Bash` restricted
  to `explain-policy` (reintroduces the exact shell-out this improvement removes, and `explain-policy` is not
  auto-allowed anyway)
- **Date:** 2026-09-19 (original); revised 2026-09-20

### Whether the deny pointer names the vehicle explicitly

- **Chosen:** Yes — reword `EQUIVALENCE_POINTER` so it says an AGENT is to be dispatched, rather than naming the target
  bare.
- **Rationale:** Rationale not captured. (Chosen over leaving the vehicle-neutral string untouched; the tradeoff put to
  the operator was that an explicit verb removes any ambiguity about how to reach the target, at the cost of a longer
  clause appended to every single denial and a change to a string earlier leaves treated as a frozen contract.)
- **Rejected alternatives:** Keep the string unchanged, relying on the agent appearing in the model's available-agents
  list under exactly that name (zero churn, keeps the frozen contract frozen); defer the decision to implementation and
  change the string only if the bare name proves insufficient in practice
- **Date:** 2026-09-19

### Whether the agent pre-verifies its own candidate against Config.decision_for()

- **Chosen:** No — reaffirmed unchanged from leaf `20260915-011123`, but now on a premise that actually holds.
- **Rationale:** That leaf justified skipping verification on the grounds that "the caller is already an agent starting
  from empty context" — a property the shipped SKILL never had. The conversion makes the premise true rather than
  aspirational, so the rule stands on its own footing for the first time. The substantive argument is unchanged: a wrong
  candidate is tested for real moments later when the calling session runs it, and the engine denies it again, so the
  self-correction loop already catches it. Pre-verification would also drag engine logic into what must stay a thin
  consumer of the rendered rules — and with `tools:` granting nothing, the agent structurally cannot run it anyway.
- **Rejected alternatives:** Verify candidates via `Config.from_dict(cfg).decision_for(candidate)` before presenting
  them, now that the isolation premise is real (rejected — the justification never depended on isolation, and verifying
  would require giving the agent a tool surface the previous decision deliberately denies it)
- **Date:** 2026-09-19

## Success Criteria

- [x] `packages/command-policy/agents/find-auto-allowed-command.md` exists, with `model: sonnet` and an EXPLICIT
      `tools:` line (not omitted) — ships as `tools: Read` (see below for why not a literal empty grant)
- [x] **PARTIALLY MET, by necessity, with the substance preserved:** dispatching that agent and asking it to enumerate
      its tools was attempted and found structurally impossible in the implementing session (plugin agent files are not
      hot-reloaded, and the installed plugin cache serving this session predates this package's version — exactly the
      limitation planning's own Assumption recorded). The `unverified` assumption was instead settled via Claude Code's
      own subagent documentation: a fully empty `tools:` list makes Claude Code refuse to spawn the agent at all, a
      harder failure than the "inherits everything" case planning hedged for. The Design Decision is corrected
      accordingly (`tools: Read`, the narrowest non-empty grant, chosen for carrying no code-execution capability) — see
      the "What tools the agent gets" Design Decision and the Implementation Notes entry added during implementation.
- [x] `packages/command-policy/skills/find-auto-allowed-command/` no longer exists anywhere in the tree — confirmed via
      a repo-wide `find` for the directory name at completion time, in addition to the scaffold test
- [x] The agent body contains no instruction to run `explain-policy`, and no statically authored command-equivalence
      table — confirmed by inspection at completion time: the only `explain-policy` mention states the agent CANNOT run
      it, and the only "equivalence table" mention is a prohibition on authoring one
- [x] Every non-empty deny reason ends with a pointer that names the agent AND the fact that it is dispatched as an
      agent — `EQUIVALENCE_POINTER` now reads "dispatch the command-policy:find-auto-allowed-command agent for an
      auto-approved alternative"
- [x] `explain-policy` with NO config file at either scope prints, as its first line, a statement that no config was
      found, naming both searched paths and pointing at `migrate-config` — verified both by unit/integration tests and
      by an end-to-end run of the real `bin/explain-policy` entrypoint against an empty `HOME`/`CLAUDE_PROJECT_DIR`
- [x] `explain-policy` with a config file present but empty does NOT print that line — the two states are
      distinguishable from the output alone — verified end-to-end the same way
- [x] `explain-policy` with a normal populated config prints no new noise relative to today's output — verified
      end-to-end the same way
- [x] Each new test was run against pre-fix code and observed to FAIL; the count of genuinely-failing new tests is
      recorded in the implementation notes — 12 new tests total (2 in `test_scaffold.py`, 2 in
      `test_reason_renderer.py`, 4 in `test_config.py`, 4 in `test_config_loader.py`), every one observed RED before its
      corresponding fix, per the Implementation TODO entries above.
- [x] **CORRECTED — the plan's "TWO known baseline failures" was itself stale by the time implementation started** (a
      prior improvement in this same batch had already fixed the `xargs`-parser gap the plan warned about). The ACTUAL
      measured baseline was 737 passed / 0 failed, and the suite ends this improvement at 749 passed / 0 failed (737
      baseline + 12 new tests). No failures of any kind remain.
- [x] `packages/shfmt-permissions/tests` still reports 751 passed, proving the old engine is untouched
- [x] **CORRECTED — the plan's "bumped from `0.3.1`" was stale**: by the time this improvement started, a prior
      improvement in this batch had already carried the version to `0.3.3`.
      `packages/command-policy/.claude-plugin/     plugin.json` and the `command-policy` entry in root
      `.claude-plugin/marketplace.json` both now carry `0.4.0`, in lockstep.
- [x] `docs/knowledgebase/command-policy-decision-model.md` describes one skill and one agent, with no surviving "Two
      Consumer Skills" framing or stale glossary row

## Implementation TODO

- [x] Update status to in-progress
- [x] Read `docs/knowledgebase/command-policy-decision-model.md` and `docs/knowledgebase/agent-frontmatter.md`; invoke
      the `tdd` skill before writing the first test
- [x] Capture the baseline: run both suites and confirm 634 passed / 2 known failures, and 751 passed (ACTUAL measured
      baseline, 2026-09-20: `packages/command-policy/tests` 737 passed / 0 failed — the two `xargs`-parser failures the
      plan warned about are already fixed by a prior improvement in this batch; `packages/shfmt-permissions/tests` 751
      passed, as expected)
- [x] Write the failing scaffold test asserting the agent file exists and the skill directory does not; observe it fail
- [x] Create `packages/command-policy/agents/find-auto-allowed-command.md` (model `sonnet`, explicit `tools:`, migrated
      reasoning procedure, prompt-input contract, retained no-self-verification section)
- [x] Dispatch the new agent once and record what tool surface it actually reports — settle the `unverified` assumption
      and correct the Design Decision if empty `tools:` does not mean "nothing" (settled via documentation instead of a
      live dispatch — see Implementation Notes; a live dispatch of a newly-created agent file is structurally impossible
      in the implementing session, exactly as planning's own Assumption recorded)
- [x] Delete `packages/command-policy/skills/find-auto-allowed-command/` and confirm the scaffold test now passes
- [x] Write the failing test for the reworded deny pointer; observe it fail (also added a regression test for the
      `UnknowablePathArgument` hint wording defect flagged for this improvement; both new tests observed RED before the
      fix)
- [x] Reword `EQUIVALENCE_POINTER` (`lib/reason_renderer.py:36`) and correct the module docstring above it, leaving
      `session_audit.py:48`'s `DENY_HEADING` untouched
- [x] Re-run the full suite and confirm the failure count is still exactly the two baseline ones (741 passed, 0 failed —
      737 baseline + 4 new tests; this trunk's actual baseline carried no pre-existing failures, see the corrected
      baseline note above)
- [x] Write the failing tests distinguishing absent-config from empty-config in `explain()` output; observe them fail (8
      new tests: 4 in `test_config.py` unit-testing the `LayerPresence` value object directly on `Config`, 4 in
      `test_config_loader.py` integration-testing through `load_config`; all 8 observed RED via an `ImportError` for the
      not-yet-created `layer_presence` module, then via assertion failures once collectible)
- [x] Add the per-layer searched-path/presence value object and thread it through `config_loader.py` and `Config`
      (`__init__`, `_replace`, `merged_with`, `explain`) — new `lib/layer_presence.py` (`LayerSearch`/`LayerPresence`),
      a `with_layer_presence` wither on `Config` (not a constructor param threaded through `from_dict`, since the
      presence fact is known only to the loader, never to a raw config dict)
- [x] Render the no-config-found line first in `explain()`, naming both paths and `migrate-config`, and keep it silent
      when any layer was found
- [x] Run both suites; confirm the two baseline failures only, and shfmt-permissions unchanged at 751 (749 passed / 0
      failed in `packages/command-policy/tests` — 741 + 8 new tests; `packages/shfmt-permissions/tests` still 751
      passed)
- [x] Update `docs/knowledgebase/command-policy-decision-model.md` (lines ~114, ~459, ~503, glossary ~601)
- [x] Update the `command-policy` bullet in root `CLAUDE.md` to describe the agent, and correct the stale claims noted
      under Observed during exploration (all three corrected: `decision_for` is live, the escalation/hook entrypoints
      graduated, and the shfmt-permissions/command-policy live-engine relationship is now stated as migration-gated
      rather than "shfmt-permissions remains the live engine")
- [x] Bump the version in `packages/command-policy/.claude-plugin/plugin.json` and root
      `.claude-plugin/marketplace.json` together (`0.3.3` → `0.4.0`, in lockstep, per the "new agent plus a removed
      skill is a minor bump" rule)
- [x] Update status to completed

## Observed during exploration

Recorded, not folded in — default action is to leave these alone unless the implementer is already editing the line in
question.

- **Root `CLAUDE.md`'s `command-policy` paragraph is materially stale in three ways.** It claims
  `Config.decision_for(command)` "still raises `NotImplementedError` pending the pipeline leaf", that
  `bypass-policy`/`add-allow-policy`/`audit-session-policy` and "the two `analyze-*` hook entrypoints remain stubs", and
  that "`shfmt-permissions` remains the live engine". All three are contradicted by direct observation this session:
  `decision_for` executes and returns real decisions, `test_scaffold.py`'s own docstring records that those entrypoints
  graduated, and command-policy is demonstrably the engine enforcing denials in this very session (its deny reasons name
  `command-policy:find-auto-allowed-command`). Since this improvement already edits that paragraph to add the agent,
  correcting these is the natural completion of that edit rather than separate work.
- **`packages/improvement/agents/code-research.md` pins `model: claude-sonnet-4-5`, a full model ID.**
  `docs/knowledgebase/agent-frontmatter.md:58-59` explicitly warns that full IDs rot and that aliases survive model
  refreshes. Out of scope here (different package), but worth a future sweep of every agent's `model:` line.

## Related Past Improvements

- improvement-20260914-195111: Trunk that first floated "skill OR agent" as the vehicle for the equivalence search,
  never resolved to a Design Decision.
- improvement-20260915-010959: Carried the vehicle choice forward verbatim as "skill/agent" without settling it.
- improvement-20260915-011123: Collapsed the vehicle to "skill" without a Design Decision entry, and is the source of
  the now-unjustified candidate-pre-verification-skip rule this improvement must revisit.
- improvement-20260918-231406: Planned and then discarded within the same session (2026-09-19), never committed, so no
  file remains — it began as "make `explain-policy` work with no config" and dissolved once the operator observed the
  config is already in context. Its one surviving item (distinguishing "no config file found" from "config present but
  empty") is folded into this improvement's objective; the reasoning is preserved in this file's Design Decisions, not
  in a separate document.
