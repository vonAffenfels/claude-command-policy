# Improvement 20260915-010959: Deny+Hint Reasons and Escalation Paths

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-15
- Updated: 2026-09-18
- Plan started: 2026-09-17T16:23:40+02:00
- Plan finished: 2026-09-17T18:16:49+02:00
- Impl started: 2026-09-17T21:40:11+02:00
- Impl finished: 2026-09-18T10:26:01+02:00
- Trunk: 20260914-195111
- Kind: decomposed
- Depends on: 20260914-213652

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`

## This Improvement's Objective

LEAF of trunk `20260914-195111` — the second half of what was originally one policy-pipeline leaf, split out during the
2026-09-15 re-plan because the outcome-model change made that leaf far too large. Leaf `20260914-213652` builds the
pipeline, the Pass ordering and the `PermissionDecision` vocabulary; THIS leaf builds what the pipeline SAYS when it
denies, and the escalation paths out of a denial.

IN SCOPE:

1. **The deny+hint reason construction.** Under the new outcome model, deny is the default for anything not
   auto-approved, and the deny reason is the mechanism that steers the model to an approved alternative. Trunk decision:
   near-miss hints are derived MECHANICALLY from the rule that actually fired, and the reason additionally POINTS AT a
   skill/agent that searches for an equivalent approved command by reading the rendered rules. The hint is computed
   deterministically by plain code and consumed BY the model — there is NO LLM call inside the hook.
   - Build on what exists rather than reinventing: `_describe_filter` and `_derive_filter_alternative`
     (`analyze-bash-command.py:2159-2209`) already derive mechanical descriptions from the single filter that fired, and
     they explicitly REFUSE to build a general command-equivalence table because it "would rot like hand-written prose".
     The chosen design respects that refusal — equivalence is delegated to a skill reading live rendered config, never
     to a static authored map. Do not reintroduce the map.
   - The full merged config is ALREADY in scope at every deny-reason construction site. No new plumbing is needed to
     reach the data — only new logic.
   - Today's engine distinguishes CASE A (program not allow-listed at all -> deliberately opinion-free) from CASE B
     (program allow-listed but this invocation rejected -> enriched reason). The new model ABOLISHES that distinction:
     both become deny+hint. CASE A's silence is documented as intentional in
     `docs/knowledgebase/shfmt-permissions.md:44-86`, so reversing it is a deliberate philosophical change, not a bug
     fix.

2. **The three escalation-path policies.** Outcomes were re-adjudicated during this leaf's own planning on 2026-09-17
   and now DIFFER from what the trunk originally settled — see Design Decisions:
   - `bypass-policy <cmd>` -> **result transformer**: ordinary objections become `passthrough` ("no opinion");
     blocked-command and sensitive-path objections become **forced `ask`** with a strongly worded reason. Its "sole
     command on the line" recognition rule must survive intact — it exists to stop denylist smuggling.
   - `add-allow-policy <entry> --scope user|project --intent <why>` -> **forced `ask`**, carrying a JSON diff of the
     exact allowlist entry it would append plus the stated intent, so approving the dialog IS the write.
   - **The shell-performed-redirect veto is never WAIVED, but it is now ESCALATED rather than denied.** A shell redirect
     into a sensitive path cannot be vouched for by the wrapper (the calling shell performs it before the wrapped
     program starts), so bypass cannot silently approve it — but under the 'never stop the user' principle it surfaces
     to the human as `ask` rather than dead-ending as `deny`.

3. **Correct a false claim in the inherited reason text.** The old `BYPASS_REASON` string asserts the bypass "falls
   through to Claude Code's own permission dialog. This counts as a user intervention." The second sentence is NOT
   reliably true: `passthrough` means the hook abstains, so if the user's own `settings.json` permits the pattern or the
   session runs in an accepting permission mode, a bypassed command auto-approves with no human ever seeing it. Rewrite
   the wording honestly rather than porting it.

PLANNING NOTE worth carrying: because bypass abstains rather than prompting, the strength of deny-by-default rests
partly OUTSIDE this plugin. In a `bypassPermissions` session, `bypass-policy` is a free pass. That is accepted (it
matches today's behaviour) but should be stated plainly wherever the escalation paths are documented. Whether a forced
`ask` is ALSO overridden in that mode is an open assumption — see Assumptions.

## Context / Why This Exists

**Origin / trigger:** Split out of leaf `20260914-213652` during the trunk's 2026-09-15 re-plan. The new outcome model
(deny+hint by default, passthrough only via an explicitly named wrapper) landed after the original six-leaf breakdown
was drawn, and loaded the pipeline leaf with the entire reason-construction and escalation surface on top of the
Pass-ordering correctness problem it already carried.

**Consumer(s) of the output:** The model itself is the primary consumer — deny reasons are what steer it into using an
approved command instead. Secondarily the human reading a dialog, and the equivalence-search skill that deny reasons
point at.

**Adjacent systems already covering part of the need:** The equivalence-search skill this leaf's reasons reference is
built in a sibling leaf (`20260915-011123`) and reads `Config.explain()`'s rendered output — so this leaf defines the
POINTER and the contract, not the search itself. The old engine's `_describe_filter`/`_derive_filter_alternative` pair
is the prior art to extend rather than replace.

## Proposed Approach

Two halves, and the REASON MODEL is the centre of gravity — the escalation paths largely fall out of it once the reason
model is right.

**A. The reason model.**

A denial carries a LIST of Reason value objects rather than a single prose string. The list is HETEROGENEOUS: it holds
both near-miss reasons (the program matched an allowlist entry but the invocation was not approved — a filter mismatch,
a disallowed variable, substitution present alongside filters, a parser fallback) and categorical reasons (blocked
command, sensitive path, sensitive variable). A single command can legitimately produce both, which is why they share
one list.

The DECISION IS DERIVED FROM THE LIST'S CONTENTS rather than stored alongside it: if any categorical reason is present
the outcome is categorical. This makes a decision/reason disagreement unrepresentable, which matters because this engine
gates every Bash tool call.

Each Reason carries FACTS (which entry, which filter, which path, which program, which field/pattern), not prose. Prose
is rendered from the facts in ONE renderer. This keeps reason text out of the individual policy classes and makes
wording changeable without touching policies.

The list is FLAT, not a tree. Reasons for different parts of one line are siblings, not parent and child; `Statement` is
already the structural model and re-encoding its shape in the reason list would create a second tree to keep in sync. If
per-reason origin is ever needed (e.g. to point a caret at an offending token), it is an ADDITIVE field on Reason
holding a reference to the originating node — not a restructure. It is not needed now.

**B. The escalation paths.**

`bypass-policy` is a RESULT TRANSFORMER applied outside the pass pipeline, so the pipeline never learns bypass exists:

```
run the pipeline normally, then:
  objection is blocked-command / sensitive-path  -> ask   (strongly worded reason)
  objection is anything else                     -> passthrough
  no objection                                   -> allow
```

Recognition is the EXISTING `sole_invoked_program` rule (the line consists of the wrapper and nothing else), NOT a
`startswith` prefix check. A command merely sharing the line with the wrapper is not wrapped and faces normal analysis.

`add-allow-policy` keeps its forced `ask` with the JSON entry diff plus `--intent`, and keeps validating before asking
(missing intent or missing entry text is rejected outright).

**C. Testing.**

The decision spec suite asserts STRUCTURE (the reason list), not rendered prose. A small separate renderer test — a
handful of representative reason lists, not one per decision case — pins the prose quality.

**D. The equivalence pointer.**

Every deny reason ends with a pointer to `command-policy:find-auto-allowed-command` — the skill (built by sibling leaf
`20260915-011123`) that reads the live rendered config via `Config.explain()` and finds a command which both achieves
the caller's goal and is auto-approved. The pointer is UNCONDITIONAL: it appears on every denial regardless of reason
kind. It is kept to one short clause, not a sentence carrying its own reasoning, since it appears every time.

This leaf owns the NAME as a frozen contract; leaf `20260915-011123` must honour it. No interim pointer at
`explain-policy` is needed: nothing in `command-policy` is user-facing yet (0.2.0, stub entrypoints, with
`shfmt-permissions` 6.1.2 still the live engine until leaf `20260914-213825` deprecates it), and leaf `20260915-011123`
lands between this leaf and that one — so the window in which the pointer names an unbuilt skill is entirely internal to
the trunk.

## Affected Components

**Files:**

- `packages/command-policy/lib/` — new reason module (exact filename to be settled against whatever leaf 20260914-213652
  lands; do not assume a name it has not created)
- `packages/command-policy/bin/bypass-policy` — currently a stub that exits 0 printing nothing
- `packages/command-policy/bin/add-allow-policy` — currently a stub that exits 0 printing nothing
- `packages/command-policy/tests/test_permission_decisions.py:1396-1481` — Batch 5, the seven escalation cases
- `packages/command-policy/tests/test_permission_decisions.py:86-105` — assert_decision helper, gains a structural
  counterpart
- `packages/command-policy/tests/` — NEW renderer test file for reason prose
- `packages/shfmt-permissions/scripts/analyze-bash-command.py` — READ ONLY, prior art (see Implementation Notes)

**Classes/Functions:**

- Reason (new) — base concept for the heterogeneous reason list
- near-miss Reason kinds (new) — filter mismatch, disallowed variable, substitution-with-filters, parser fallback
- categorical Reason kinds (new) — blocked command, sensitive path, sensitive variable
- the reason renderer (new) — single place where facts become prose
- the bypass result transformer (new) — applied outside the pass pipeline
- PermissionDecision — leaf 20260914-213652's container; its `reason` field becomes the reason list (HAND-BACK, see
  Implementation Notes)

**Modules:**

- command-policy

## Implementation Notes

**CROSS-LEAF HAND-BACK REQUIRED — leaf `20260914-213652`.** That leaf's Interface settles `PermissionDecision` as a
simple `{decision, reason}` container with `reason` a string, and explicitly assigns the rich reason text to THIS leaf.
The reason-list model changes that contract. Leaf 6 is at `ready-to-implement` with `Plan finished` stamped but is NOT
yet implemented, so this is the cheapest moment the change will ever be. This must reach leaf 6 before it is implemented
— record it in this leaf's `## Interface` and surface it at INTEGRATE.

**SPEC CASES THAT MOVE.** Three of the seven Batch 5 cases change under the re-adjudicated escalation outcomes. Verified
by reading them:

- `test_the_bypass_wrapper_escalates_a_command_that_would_otherwise_be_denied` (`:1412`) — `passthrough` becomes `ask`.
  NOTE this one was not part of the original framing; it follows from the rule that blocked/sensitive always reaches the
  human.
- `test_the_shell_performed_redirect_veto_survives_the_bypass_wrapper` (`:1437`) — `deny` becomes `ask`. The test NAME
  and docstring also need rewriting: the veto is no longer 'survives as deny' but 'is never waived, and escalates to the
  human'.
- `test_the_bypass_wrapper_does_not_cover_a_command_chained_alongside_it` (`:1423`) — STAYS `deny`. Deliberate; see
  Design Decisions.
- `test_the_two_escape_hatches_produce_different_outcomes_by_design` (`:1473`) — UNAFFECTED. It uses `rg`, which is
  neither blocked nor sensitive, so bypass still yields `passthrough` there and the two hatches still differ.

**A TRUNK-LEVEL CLAIM BECOMES FALSE.** The trunk states `add-allow-policy` is "the ONLY path that forces `ask`". Under
the new escalation rule `bypass-policy` also forces `ask` when it wraps a blocked command or sensitive path. Amend at
INTEGRATE.

**PRIOR ART, AND THE DEFECT IT CARRIES.** `_check_call_expr_against_entries` in the old engine loops over ALL allowlist
entries matching a program. Entries drop out for several DIFFERENT reasons via a bare `continue` — a disallowed
variable, command substitution present alongside filters, a parser `fallback=ask` — and those contribute NOTHING to the
reason. Meanwhile `rejecting_filter_def` is a SINGLE overwritten variable, so the final reason names whichever entry
happened to be visited LAST. The emitted text reads "arguments did not match any allowed pattern (rule that rejected it:
X)" — plural in its claim, singular and arbitrary in its evidence. The reason list exists to fix exactly this: report
the whole candidate set, each with its own cause.

**WHY `ask` RATHER THAN `passthrough` FOR THE HARD CASES.** `passthrough` DISCARDS the reason string — the hook emits
nothing and Claude Code falls through to its own logic, so the human is never warned. A warning nobody reads is not a
control. `ask` is the only outcome that both stops silent auto-approval and carries text.

**ORDERING TESTS MUST NOT GO VACUOUS.** The existing ordering cases (e.g. `:1484`
substitution-before-sensitive-variable) assert `expected_reason` as a substring, on the premise that only one cause
surfaces. Once the reason reports ALL objections, `"substitution" in reason` passes trivially. These cases must be
rewritten to assert the FIRST element of the reason list (primary objection, by pass order), not 'contains anywhere'. A
spec case that still passes but no longer constrains anything is the worst failure mode this suite has.

**KEEP REASON OBJECTS SMALL.** Structural equality in tests is only ergonomic if each Reason carries few fields. Treat
'a test cannot comfortably construct the expected value by hand' as a signal the value object is carrying too much and
should be split — reach for predicate/partial matching only if that genuinely fails.

**TEST HELPER NAMING.** The suite's convention is `assert_decision`; the structural counterpart should follow it (e.g.
`assert_reason_includes`), not a noun-phrase name.

**VOCABULARY.** Settle on ONE word for the concept across classes and helpers — `Reason` is preferred for continuity
with `PermissionDecision.reason` and the suite's `expected_reason`.

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/test_permission_decisions.py:86` — assert_decision — the existing decision assertion;
  its optional expected_reason substring parameter is what the structural helper replaces for reason claims
- `packages/command-policy/tests/test_permission_decisions.py:62` — assert_config_is_reachable — guards suite-local
  configs against values no real config could produce
- `packages/command-policy/tests/conftest.py` — run_entrypoint and cwd_pinned_inside_project fixtures;
  cwd_pinned_inside_project is already used by the redirect-veto escalation case

**New helpers to create:**

- assert_reason_includes — structural counterpart to assert_decision — asserts a Reason value object is present in the
  decision's reason list without touching rendered prose
- a reason-list builder for expected values — only if constructing expected Reason objects by hand proves awkward — and
  if it does, treat that as a signal the Reason objects carry too much and should be split rather than papering over it
  with a builder

**Fantasy callsites (test-facing API sketches):**

- `assert_reason_includes(result, RegexMismatch(field="args", pattern="^--json$"))`
- `assert_reason_order(result, [SensitivePath("/vault/secret.txt"), BlockedCommand("rm")])`
- `render(reasons).should_name_the_equivalence_route()`

**Testability-driven production decisions:**

- Reason as a value object with structural equality, so tests compare values rather than parse prose — the repo has no
  custom **eq** today, so this follows the trunk's new-convention rule
- Prose rendering split out of the policies into a single renderer, so prose is testable in one place and policy tests
  never assert text
- Decision derived from the reason list rather than stored, so no test needs to construct a decision and its reasons
  separately and keep them consistent

## Assumptions

- **Claim: A forced `ask` emitted by a PreToolUse hook cannot be silently auto-approved in a `bypassPermissions`
  session, or by a permissive allow rule in the user's own settings.json.** — **Verification status: confirmed** —
  **Evidence: MEASURED 2026-09-17 by direct probe, not reasoned.** Method: a PreToolUse Bash hook returning
  `permissionDecision: "ask"` for any command containing a sentinel string, registered in `.claude/settings.local.json`,
  logging EVERY invocation so that "the hook fired and its ask was overridden" could be distinguished from "the hook
  never fired" — two outcomes that are indistinguishable if you only check whether the command ran. Two headless
  sessions were then run against it. (a) bypassPermissions: `claude -p --permission-mode bypassPermissions` instructed
  to run `echo <sentinel> > ran-bypass.txt`. The hook fired and returned `ask`; the file was NOT created; the session
  itself reported "the forced-ask hook denied the call". The mode did NOT bypass the hook. (b) allow rule: `claude -p`
  in default mode instructed to run `python3 <script> <sentinel>`, where `Bash(python3:*)` IS allow-listed in this
  project's `settings.local.json`. The hook fired and returned `ask`; the marker file was NOT created. The allow rule
  did NOT override the forced ask. CAVEAT, recorded rather than smoothed over: both runs were headless, where an `ask`
  has nobody to answer it and therefore blocks. This proves the ask was HONOURED rather than ignored under both
  configurations — which is the load-bearing part, since it means neither route silently auto-approves — but it does not
  directly measure what an INTERACTIVE `bypassPermissions` session does once the dialog appears. That it shows a dialog
  follows from the hook being consulted at all, but was not itself measured. Artifacts:
  `docs/improvements/experiments/20260915-010959/probe-ask-hook.py` and `hook-invocations.log`.
  `.claude/settings.local.json` was restored to its pre-probe state and verified byte-identical afterwards.

- **In the shipped engine, the bypass wrapper currently defeats the shell-performed-redirect veto.** — confirmed
  (`_ast_is_bypass_wrapped` returns at `packages/shfmt-permissions/scripts/analyze-bash-command.py:1452-1453`;
  `_check_redirect_path_validation` is only reached at `:1549`, 97 lines later. So the proposed `ask` outcome is a
  deliberate behaviour CHANGE from today, not a preservation — consistent with the trunk's 'this is not a refactor, this
  is a rewrite'.)

- **Today's filter-rejection reason names only one rule out of a candidate set that may contain several, and omits
  entries that dropped out for non-filter causes.** — confirmed (Read `_check_call_expr_against_entries`: it loops over
  all matching entries; `rejecting_filter_def` is a single variable overwritten per entry, so only the last failing
  entry's filter survives to the reason. Entries skipped via `continue` (disallowed variable, substitution alongside
  filters, parser `fallback=ask`) set nothing and are invisible in the emitted text.)

- **The escalation cases in the decision spec suite assert decisions only, never reason text.** — confirmed
  (`assert_decision` (`test_permission_decisions.py:86`) takes an optional `expected_reason` substring. It is supplied
  at 7 call sites (lines 133, 352, 742, 1500, 1514, 1529, 1558) — none of them in Batch 5 (`:1396-1481`). So the
  escalation reasons have no gate today.)

- **Leaf `20260914-213652` is planned but not implemented, so changing its `PermissionDecision` contract is still
  cheap.** — confirmed (Its Meta reads `Status: ready-to-implement` with `Plan finished: 2026-09-16T23:50:26+02:00` and
  no `Impl started`. The leaf-stream entry marking it 'done' tracks PLANNING completion, which is a different axis — an
  earlier research pass conflated the two and wrongly reported a dependency blocker.)

- **Only three of the seven Batch 5 escalation cases change under the re-adjudicated outcomes.** — confirmed (Read all
  seven. `:1412` passthrough->ask and `:1437` deny->ask change; `:1423` stays deny by deliberate carve-out; `:1473` is
  unaffected because it exercises `rg`, which is neither blocked nor sensitive; `:1397`, `:1453`, `:1465` are
  untouched.)

## Design Decisions

### How `bypass-policy` relates to the decision pipeline

- **Chosen:** A result TRANSFORMER applied outside the pass pipeline: ordinary objections become `passthrough`,
  blocked-command/sensitive-path objections become forced `ask`, no objection stays `allow`.
- **Rationale:** User's requirement was that bypass sit outside the usual decision process and not complicate the policy
  pipeline — 'if the command starts with bypass-policy we hard return a passthrough because that is what that prefix is
  for. No need to make the policy process more complex to fit that in.' The transformer honours that exactly: the
  pipeline never learns bypass exists. A literal `startswith` hard-return was the first formulation and was withdrawn
  once it was shown to launder both chained commands and shell-performed redirects, since `bypass-policy` is a prefix of
  lines that do more than one thing.
- **Rejected alternatives:** Bypass as Pass -1 (anything out-ranking Pass 0 reaches its outcome before the redirect veto
  runs, so the veto never fires); splitting the redirect-veto portion of SensitivePaths into a pass above bypass (splits
  one concept across two classes for a purely ordering reason, and every future unescalatable guard needs another slot);
  an `unescalatable` boolean on Policy (a second ordering axis alongside Pass, whose default value is the unsafe
  direction); literal `startswith` hard passthrough (breaks the anti-smuggling rule).
- **Date:** 2026-09-17

### What happens when bypass wraps a blocked command or a sensitive path

- **Chosen:** Forced `ask` with a strongly worded reason — never `deny`, never `passthrough`.
- **Rationale:** User's principle: 'we never want to stop the _user_ from doing anything so denying this outright feels
  like it was the wrong choice here', plus the observation that 'ask can carry a reason unlike bypass'. This is not a
  middle ground — it dominates both alternatives. Against `passthrough`: passthrough discards the reason entirely (the
  hook emits nothing), so the human is never warned, and under a permissive settings.json or a bypassPermissions session
  it auto-approves silently — which is today's shipped behaviour and the worst outcome. Against `deny`: deny routes back
  to the MODEL, not the human, so it dead-ends an escalation the user made explicitly by name, pointing at alternatives
  that by definition do not exist. The user also noted the intended second-order effect: making blocked/sensitive a
  double-no against the standing 'try to have all commands run without user intervention' pressure.
- **Rejected alternatives:** `deny` (the current spec's answer — dead-ends the explicit escalation); `passthrough`
  (today's shipped engine — verified: bypass returns at `analyze-bash-command.py:1452` while redirect validation sits at
  `:1549`, unreachable, so bypass currently defeats the redirect veto outright).
- **Date:** 2026-09-17

### Whether a blocked command merely SHARING a line with the wrapper also escalates

- **Chosen:** No — it stays `deny`, with a hint naming the route ('the `rm` on this line is not wrapped — wrap it
  explicitly to escalate it').
- **Rationale:** Carved out against the initial framing, which would have made both chained and redirect examples `ask`.
  If an unrelated `bypass-policy echo hi &&` prefix upgrades an unwrapped blocked command from deny to ask, the prefix
  improved the caller's outcome without the caller having escalated the thing that actually matters — a weaker form of
  the laundering the anti-smuggling rule exists to prevent. User agency is still preserved because a named route exists:
  wrap the command you actually mean to escalate. Keeps the rule to one sentence — bypass covers what it invokes.
- **Rejected alternatives:** Treating the chained case as `ask` alongside the genuinely-wrapped cases.
- **Date:** 2026-09-17

### The shape of a denial's reason

- **Chosen:** A flat, heterogeneous LIST of Reason value objects carrying facts, with the decision DERIVED from the
  list's contents and prose rendered in one place.
- **Rationale:** User's framing: 'we usually don't have one decision instead we have a set of policies with matching
  command but filters not aligning', and 'a command can have both a blockedCommand and a sensitivePath in it after all'
  — which argues against the either/or homogeneous lists first sketched. Confirmed against the old engine:
  `rejecting_filter_def` is a single overwritten variable naming whichever entry was visited last, while entries skipped
  via `continue` are invisible in the reason entirely, so today's text claims 'did not match any allowed pattern' but
  evidences exactly one arbitrary member of the set. Deriving the decision from the reasons rather than storing both
  makes decision/reason disagreement unrepresentable, which is worth more than tidy homogeneous lists in something that
  gates every Bash call.
- **Rejected alternatives:** A single prose string built per policy (today's approach — scatters reason assembly across
  every policy class and appends the skill pointer by hand in each); separate homogeneous lists switched on by kind
  (cannot represent a command carrying both a blocked command and a sensitive path); storing the decision alongside the
  reasons (permits the two to disagree).
- **Date:** 2026-09-17

### Whether the reason structure is a list or a tree

- **Chosen:** Flat list. Origin-tracking, if ever needed, becomes an additive field on Reason rather than a restructure.
- **Rationale:** User asked directly whether a list suffices or whether reasons must map back to the Statement/CmdNode
  they came from, and judged it not currently needed. Agreed, with a sharper reason: reasons for different parts of one
  line are SIBLINGS, not parent and child — they do not nest, so a tree would mirror `Statement`'s shape in a second
  place and create two structures to keep in sync, when `Statement` being the single structural model is the trunk's
  whole thesis. The trigger to watch for is wanting to point at a specific token (a caret under an offending argument);
  prose never needs it, and even then a reference field suffices rather than nesting.
- **Rejected alternatives:** A tree mirroring the statement's nesting.
- **Date:** 2026-09-17

### How the spec suite asserts reasons

- **Chosen:** Structural assertions against the non-rendered reason list in the decision spec suite, plus a small
  SEPARATE renderer test pinning the prose.
- **Rationale:** User's instinct was that comparing against the non-rendered list is 'more durable' than rendering to
  string and substring-matching. Confirmed, with three further arguments: substring checks couple every decision test to
  prose that this leaf exists to rewrite; they admit a false-pass class (`'API_TOKEN' in reason` passes when the token
  appears as an ALLOWED variable rather than the sensitive one that fired, whereas typed reasons cannot be confused);
  and they cannot express completeness or absence, so the 'each and thus all reasons present' assertion the user wants
  is only reachable with structural comparison. The split exists because structural-only assertions would leave the
  RENDERED text — this leaf's actual deliverable, and what the model reads — with no coverage at all.
- **Rejected alternatives:** Substring assertions only (the status quo — brittle, false-pass-prone, cannot express
  completeness); structural assertions only (leaves the rendered prose untested); rendering the expected Reason to a
  string and substring-matching it (keeps the prose coupling the change is meant to remove).
- **Date:** 2026-09-17

### The name and target of the equivalence pointer

- **Chosen:** The deny reason points at a skill named `command-policy:find-auto-allowed-command`, frozen here as a
  contract leaf `20260915-011123` must honour. No interim pointer at `explain-policy`.
- **Rationale:** The name was the user's (`find-autoallowed-command`), adopted over the planner's proposed
  `find-equivalent` because it names the PROPERTY the caller needs (a command that runs with no human in the loop)
  rather than the RELATION to the command they tried. That property is the whole basis of the outcome model — `allow` is
  privileged precisely because it is the only outcome with no human involved — and it is what the escalation design's
  "double-no" argument rests on. Hyphenated to `auto-allowed` by the planner for legibility, matching how the concept is
  written elsewhere; the user invited the planner's take on the spelling. The planner's initial objection — that naming
  an unbuilt skill leaves a dangling pointer — was WITHDRAWN as overstated: `command-policy` is at 0.2.0 with stub
  entrypoints and `shfmt-permissions` 6.1.2 remains the live engine until leaf `20260914-213825`, while leaf
  `20260915-011123` lands in between, so no user ever encounters the unbuilt-skill window.
- **Rejected alternatives:** Pointing at `explain-policy` until the skill lands and swapping later (unnecessary once the
  pre-live window was correctly understood; would have cost a renderer change and a test update for no user-visible
  benefit); naming both routes permanently (two routes on every denial forever, with nothing ever removing the second);
  `find-equivalent` (names the relation, not the property).
- **Date:** 2026-09-17

### Which denials carry the equivalence pointer

- **Chosen:** Every deny reason carries it, unconditionally, as one short clause.
- **Rationale:** The planner proposed conditioning the pointer on reason kind — withholding it from pure filter
  near-misses on the grounds that those are self-correcting. The user REFUTED this: "A program with forbidden --json
  might still be the same program without but not do the thing we needed it for anymore. So a near miss is not the same
  as 'usable when done properly'." A near-miss hint answers "how do I make THIS command pass", which is a different
  question from "how do I accomplish the task within what is allowed". The conditional rule would therefore have
  withheld the equivalence route exactly where the near-miss is quietly misleading — leading the model to confidently
  run a command that is approved but no longer does the job. This reframes the pointer from
  error-recovery-for-unfixable-denials into a standing affordance that is always relevant, which is what makes
  unconditional correct. The boilerplate-blindness cost the planner raised is accepted as real but minor, and is
  mitigated by keeping the pointer to one short clause rather than a sentence carrying its own reasoning.
- **Rejected alternatives:** Appending the pointer only when the caller cannot fix the command by adjusting it (program
  not allow-listed at all, or a categorical blocked/sensitive reason) — refuted as above; appending it only when the
  reason list contains zero near-miss reasons — same defect, and additionally silent for a command carrying both a
  near-miss and a blocked command.
- **Date:** 2026-09-17

### Who rewrites the knowledgebase for the CASE A reversal

- **Chosen:** This leaf updates `docs/knowledgebase/command-policy-decision-model.md` with the deny+hint reason model
  and the escalation paths. `docs/knowledgebase/shfmt-permissions.md` is left untouched.
- **Rationale:** The command-policy article ALREADY EXISTS — it was updated 2026-09-16 by the config leaf
  `20260914-213153` — so a correct home is already in place and needs no new article. `shfmt-permissions.md` documents
  shfmt-permissions 6.1.2, which remains THE LIVE ENGINE until leaf `20260914-213825` deprecates it; editing it to
  describe command-policy's behaviour would make it actively wrong about its own subject while that subject is still
  shipping and still behaving exactly as those lines describe. The trunk's observation that the 554-line article "needs
  substantial rewriting" still stands, but that is deprecation-time work owned by leaf `20260914-213825`.
- **Rejected alternatives:** Deferring all knowledgebase work to leaf `20260914-213825` (leaves the reason and
  escalation semantics undocumented across several intervening leaves, and that leaf is already the largest remaining);
  rewriting `shfmt-permissions.md:44-86` now (makes a still-accurate article wrong about the engine still in use).
- **Date:** 2026-09-17

### Whether the strict `add-allow-policy` grammar fixes flag ORDER or only flag/positional shape

- **Chosen:** Order-agnostic. `--scope <val>` and `--intent <val>` may appear in either order or interleaved with the
  command argument; the grammar requires exactly one `--scope` (a valid value), exactly one `--intent`, and exactly one
  remaining (non-flag) token — not a fixed byte-for-byte positional template.
- **Rationale:** The reopening prompt's rationale for the strict grammar is entirely about QUOTING — guaranteeing the
  command reaches the tool as one unmangled argument so the outer shell cannot split a redirect off of it. Nothing in
  that rationale depends on flag order. Rejecting a valid, safely quoted invocation merely because `--intent` was
  written before `--scope` would be gratuitous strictness the stated WHY does not support, and real CLI flag grammars
  (getopt/argparse) are conventionally order-tolerant for options relative to positionals. Made unattended (no human
  available mid-reopening to ask) — flagged here explicitly, with the literal alternative reading ("the ONLY accepted
  one" as a fixed positional template) recorded below, so a reviewer who intended the stricter reading can override it
  in one place (`escalation_policy._classify_add_allow_invocation`) without re-deriving the grammar.
- **Rejected alternatives:** A fixed positional template (`--scope`, value, `--intent`, value, command — exactly this
  order, nothing else) — the more literal reading of "the canonical form, and the ONLY accepted one," rejected because
  it protects nothing the quoting rationale asks for and would deny safe, unambiguous invocations for a reason unrelated
  to the defect being fixed.
- **Date:** 2026-09-17

## Observed during exploration

- **Hooks declared in `.claude/settings.local.json` take effect IMMEDIATELY in already-running sessions — they are not
  snapshotted at session start.** Measured incidentally during the forced-ask probe: the probe hook began firing on THIS
  planning session's own Bash calls within seconds of the file being written, with no restart. The planner had assumed
  the opposite and designed the experiment around that assumption. Relevant to anyone editing hook config mid-session,
  and a caution that a careless hook edit affects the editing session itself.
- **Neither harness finding is expressible as a pytest regression test here.** Both the forced-ask result and the
  hook-liveness result are facts about the Claude Code harness, not about this repo's code, so
  `packages/command-policy/tests/` cannot assert them. This repo's `probe` package exists for exactly this genre —
  measured harness facts recorded with the Claude Code version they hold for. Folding them in there is a plausible
  follow-up, deliberately NOT taken here as it is outside this leaf's scope.

## Observed during implementation

- **`add-allow-policy`'s `--intent` is NOT required for the PIPELINE'S forced `ask` — only for the SCRIPT'S write.** The
  Proposed Approach text ("keeps validating before asking - missing intent or missing entry text is rejected outright")
  reads as a pipeline-level (decision_for) validation, mirroring the old engine's `_check_propose_allow` (which returns
  `deny`, not `ask`, for a missing `--intent`). But both batch-5 spec cases (`add-allow-policy --scope user rg`,
  `--scope project rg`) omit `--intent` entirely and expect `ask` — the acceptance gate, so it wins. Resolved by
  splitting the obligation across the two runtime halves this leaf owns: `escalation_policy.add_allow_policy_transform`
  (the pipeline recognition) forces `ask` whenever an entry is present, regardless of `--intent`, so the human always
  sees the dialog; `lib/add_allow_write.py` (the bin script's write-side logic, run only once that dialog is approved)
  still refuses to WRITE without a non-blank `--intent` (argparse `required=True`, `exit(2)` on blank). A missing ENTRY
  (nothing to propose adding at all) is the one case that still denies at the pipeline level, since there `ask` would
  show an empty diff. See `test_escalation_policy.py` and `test_escalation_entrypoints.py` for both halves' coverage.
- **A Success Criterion needed its own new Reason kind mid-implementation.** "A blocked command sharing a line with the
  wrapper but not wrapped by it still yields `deny`, with a hint naming the wrap-it-explicitly route" was not satisfied
  by `bypass_transform` alone (it never fires for a chained line - `as_sole_invoked_program()` correctly returns
  `None`), so the hint was missing entirely until added as a THIRD, independent transform,
  `escalation_policy.bypass_chain_hint` - applied after `bypass_transform` returns `None`, it checks whether
  `bypass-policy` merely appears elsewhere on the line and, if the ordinary decision already carries a categorical
  forcing reason, augments it with `NotEscalatedByAnUnrelatedBypassWrapper` (a routing note, not itself an objection -
  it never appears alone, and never changes `allow` to `deny`). Not the original design's own idea, but demanded by the
  plan's own Success Criteria list once read closely.
- **The near-miss taxonomy in `reason.py` is smaller than the Objective's illustrative list.** "substitution present
  alongside filters" and "a parser fallback" (`## This Improvement's Objective`, item 1) are not their own Reason kinds:
  the `fallback` knob is permanently gone (leaf `20260914-213502`), so there is nothing left to report a reason about,
  and a substitution defeating a filter is reported as the same generic `FilterRejected(program, filter_type)` as any
  other filter mismatch - `KEEP REASON OBJECTS SMALL` (Implementation Notes) argued against a bespoke kind for one cause
  among several a filter can fail for. `FilterRejected` deliberately omits WHICH pattern/ option/field failed for the
  same reason.
- **The uncompilable-filter-pattern Warning is surfaced EAGERLY at `Config.from_dict` time, not at decision time.**
  Carried-forward finding 1 asked to make the existing decision-time-collected-but-discarded Warning reachable; the
  actual fix is a NEW, independent, static scan (`config.py`'s `_collect_allowed_command_filter_warnings`, using a new
  `Filter.try_from_definition` classmethod shared with `AllowedCommandPolicy`'s own match-time fail-closed path) run
  once per `Config.from_dict` call, so the warning is visible via `Config.warnings()` even for a command that never
  invokes the affected program - matching every OTHER warning in this codebase (all currently construction-time).
  `AllowedCommandPolicy`'s own `warnings_sink`/`.warnings()` machinery (the literal dead end) was deleted rather than
  kept alongside the new mechanism, since it had no reachable caller and duplicating the compile-attempt would have
  produced two warnings for one config defect.

## Observed during implementation (reopened 2026-09-17)

- **The strict grammar's `ask`-dialog diff cannot show a double-quoted command/intent argument's real text - a
  pre-existing, deliberately-pinned limitation surfacing here, not introduced here.** `Argument.text` (`statement.py`)
  does a naive one-level `Parts` concatenation: a double-quoted word is ONE top-level `DblQuoted` node whose nested
  literal content is never unwrapped, so it always extracts as `""` - pinned intentionally by leaf `20260914-213321`'s
  own `test_statement.py::test_a_braced_variable_reference_next_to_literal_text`. Before this reopening nothing
  exercised this on a quoted `add-allow-policy` entry (the old grammar's own tests all used bare, unquoted entries), so
  the gap was latent. The strict grammar's canonical template quotes the command with DOUBLE quotes, which makes the gap
  load-bearing: `add-allow-policy --scope user --intent "x" "rg"` reaches `ask` correctly (argument BOUNDARIES come from
  shfmt's `Args` array, independent of this text-extraction limitation) but its JSON diff shows
  `"allowedCommands": [""]` instead of `"rg"`. `SglQuoted` carries its `Value` directly and is unaffected -
  `add-allow-policy --scope user --intent 'x' 'rg'` shows the real text. NOT fixed here: fixing `Argument.text`'s
  DblQuoted handling is leaf `20260914-213321`'s own deliberate, tested design (see the pinned test above), shared by
  every filter/path/variable check in the engine, not a defect scoped to this leaf - the "Related systems without
  coverage: do NOT touch" scope-discipline boundary applies here even though coverage DOES exist, because the coverage
  is a deliberate pin, not an oversight. The actual config WRITE is unaffected regardless (`lib/add_allow_write.py`'s
  `main()` parses real `argv` via `argparse`, never the shfmt AST), so only the human-facing PREVIEW is degraded, never
  the persisted entry. Flagged as a follow-up for whoever next touches quoted-argument text extraction (`statement.py`'s
  `Argument.from_word`/`Redirect.target_text`), not for this leaf.
- **Grammar validity and the `entry_text` used for display are two separate concerns, deliberately not conflated.**
  `_classify_add_allow_invocation` (`lib/escalation_policy.py`) counts command arguments by shfmt `Args` boundaries
  (always correct, regardless of quote style); it does not additionally require the extracted TEXT be non-empty. Doing
  so would have made every double-quoted, syntactically-correct invocation deny as a false-positive grammar violation -
  defeating the grammar's own canonical template. The display limitation above is accepted instead of papered over with
  a stricter grammar check that would reject valid syntax for the wrong reason.

## Observed during implementation (reopened 2026-09-18)

- **DEFECT FOUND IN REVIEW, previously undisclosed anywhere: the double-quote text-extraction gap was not merely a
  display bug for `add-allow-policy`'s `ask` dialog - it was a WRONG DECISION for `--scope`.** The 2026-09-17 reopening
  note above (`Argument.text` never unwraps a `DblQuoted` word) correctly diagnosed the mechanism but understated its
  reach: `_classify_add_allow_invocation` (`lib/escalation_policy.py`) read `--scope`'s VALUE through the same
  `Argument.text`, so `add-allow-policy --scope "user" --intent "x" "rg"` - a legitimate, correctly-quoted canonical
  invocation - read the scope value as `""`, failed `invalid_scope_value`, and was DENIED outright with a reason
  ("--scope must be exactly 'user' or 'project'") that is factually false about the command it rejects: the value WAS
  exactly `user`, merely double-quoted. Not caught before because every existing batch-5/escalation-policy spec left
  `--scope`'s own value unquoted even when quoting the command/intent - nothing exercised a quoted `--scope` value until
  an independent review looked for one.
- **Fix: `Argument.literal_text`, a new accessor alongside the pinned `Argument.text` (`statement.py`), not a change to
  `text` itself.** `text`'s naive one-level Parts concatenation stays exactly as leaf 20260914-213321 pinned it (its own
  `test_a_braced_variable_reference_next_to_literal_text` is untouched) - the substitution-unknowability rules that
  consume `text` need that exact naive behaviour. `literal_text` unwraps a DblQuoted word's own nested Parts recursively
  (`statement._literal_text_of_parts`), recovering the word's real literal content while still contributing nothing for
  a `ParamExp`/`CmdSubst`/`ProcSubst` - the same blind spot `text` already has for content neither can statically see.
  `_classify_add_allow_invocation` now reads every token (`--scope`/`--intent` flag names included, for consistency) via
  `.literal_text` instead of `.text` - one change at the call site fixes both the wrong `--scope` denial and the empty
  `ask`-dialog diff/intent, since both traced back to the same naive concatenation.
- **`bypass_transform`'s own use of `Argument.text` (building `wrapped_text`) was deliberately left untouched.** Out of
  scope per the reopening instructions - bypass-policy behaviour is unchanged this round.

## Success Criteria

### Reopened 2026-09-18: double-quoted `--scope`/entry/intent text at the classification call site

- [x] `add-allow-policy --scope "user" --intent "x" "rg"` (double-quoted `--scope` value) is ACCEPTED and reaches `ask`,
      exactly like the unquoted and single-quoted forms - not denied as `invalid_scope_value`
- [x] The canonical double-quoted form's `ask` dialog shows the REAL command entry and the REAL stated intent, not an
      empty diff/intent
- [x] `Argument.text` and its pinning test (`test_statement.py:602-614`,
      `test_a_braced_variable_reference_next_to_literal_text`) are unchanged
- [x] The fix lives at the `add-allow-policy` classification call site (`lib/escalation_policy.py`'s
      `_classify_add_allow_invocation`), via a new `Argument.literal_text` accessor - not a change to the shared
      `Argument`/`Redirect` value objects' pinned behaviour
- [x] `test_add_allow_policy_transform_forces_ask_for_the_canonical_quoted_form` asserts the real diff text and the real
      intent text on the double-quoted spec directly; the docstring's now-false "content cannot be asserted" claim is
      removed
- [x] `test_add_allow_policy_transform_forces_ask_and_names_the_proposed_entry` (single-quoted) is kept alongside it
- [x] A new spec asserts the double-quoted `--scope` regression cover: ACCEPTED, reaches `ask`
- [x] `lib/add_allow_write.py`'s stale "`--intent` is not required at the ask-recognition layer" docstring claim is
      corrected to reflect the 2026-09-17 reopening's strict-grammar requirement
- [x] Full command-policy suite passes with exactly the 2 known xargs reds and no new failures
- [x] `docs/knowledgebase/command-policy-decision-model.md`'s "Known display limitation, not fixed here" passage is
      corrected to describe the fix, since the limitation no longer exists
- [x] Item 1 (the wrong `--scope` denial) is recorded in this file as a defect found in review, since it was previously
      undisclosed everywhere

## Success Criteria (original + first reopening, unchanged this round)

- [x] A denial carries a LIST of Reason value objects; a command producing both a blocked-command objection and a
      sensitive-path objection reports BOTH, not one.
- [x] The decision is derived from the reason list's contents — there is no code path that can produce a decision
      disagreeing with its reasons.
- [x] Every entry that matched the program but did not approve the invocation contributes its own Reason, including
      entries that drop out for a disallowed variable, for command substitution alongside filters, or for a parser
      fallback — none are silently omitted. (The `fallback` knob itself no longer exists — see Observed during
      implementation — so there is no reason left to report about it; every other listed cause is covered.)
- [x] Reason objects carry facts, not prose; exactly one renderer turns them into text.
- [x] The decision spec suite asserts reason STRUCTURE via a helper following the `assert_decision` naming convention;
      no decision case asserts rendered prose.
- [x] The ordering cases assert the FIRST element of the reason list, and fail if the primary objection changes —
      verified by deliberately reordering and observing a red test, so they cannot pass vacuously.
- [x] A separate renderer test pins the prose of a handful of representative reason lists.
- [x] `bypass-policy` is applied outside the pass pipeline; no Policy class and no Pass value references it.
- [x] `bypass-policy` wrapping a blocked command or a sensitive-path redirect yields `ask` with a reason naming what
      made it dangerous.
- [x] `bypass-policy` wrapping an ordinary non-approved command yields `passthrough`.
- [x] A blocked command sharing a line with the wrapper but not wrapped by it still yields `deny`, with a hint naming
      the wrap-it-explicitly route.
- [x] `add-allow-policy` forces `ask` carrying the JSON entry diff and `--intent`, and rejects a malformed invocation
      before asking. **SUPERSEDED 2026-09-17 by the reopened strict-grammar criteria below** — `--intent` is now
      required by the grammar itself (not only the write-side script), and "malformed" now covers the full grammar
      (shell-touched, redirect-on-invocation, missing/repeated/invalid `--scope`, missing `--intent`, zero/multiple
      command arguments), not only a missing entry.
- [x] The rewritten `BYPASS_REASON` text makes no claim that a bypass guarantees human review.
- [x] All seven Batch 5 cases pass, with `:1412` and `:1437` amended to `ask` and `:1423` unchanged at `deny`.
- [x] The `## Interface` section records the `PermissionDecision` contract hand-back to leaf `20260914-213652` and the
      trunk's now-false 'only path that forces ask' claim.
- [x] Every deny reason ends with a pointer to `command-policy:find-auto-allowed-command`, including denials that also
      carry an actionable near-miss
- [x] The pointer is a single short clause, not a sentence carrying its own reasoning
- [x] The pointer text is produced by the single renderer, not appended by individual policies
- [x] `docs/knowledgebase/command-policy-decision-model.md` documents the reason list, the unconditional equivalence
      pointer, and the three escalation outcomes; `docs/knowledgebase/shfmt-permissions.md` is left unchanged

### Reopened 2026-09-17: strict `add-allow-policy` grammar

- [x] The ONE accepted grammar — `--scope <user|project> --intent "<why>" "<command>"` (flag order free, exactly one of
      each) — forces `ask`; every other shape whose command word is `add-allow-policy` denies via a structured
      `AddAllowPolicyGrammarViolation` Reason rendered by the single renderer, never a hand-built string
- [x] Denied: missing/repeated `--scope`; a `--scope` value other than `user`/`project`; missing `--intent`; zero or
      more than one command argument; a redirect on the invocation itself; the invocation being part of a pipeline, a
      `&&`/`||`/`;` list, backgrounded, or carrying a command substitution anywhere in it
- [x] The deny reason teaches the correct form and the quoting rationale, naming the unquoted-redirect case by name
- [x] `test_add_allow_policy_forces_ask_as_the_durable_fix_escalation` and
      `test_add_allow_policy_forces_ask_for_the_project_scope_too` re-authored to the canonical quoted form; the
      forced-ask path they cover remains asserted, not merely deleted
- [x] `test_the_two_escape_hatches_produce_different_outcomes_by_design` fixed for the same reason, though not named in
      the reopening task — a necessary consequence of the grammar change, not a revisit of anything else
- [x] New Batch 5 cases assert deny for the unquoted-redirect shape (the one with a real user-visible consequence) and
      for a redirect-free multi-argument shape, registered in `MATCHING_BRANCH_COVERAGE`
- [x] Full command-policy suite passes with exactly the 2 known xargs reds and no new failures (481 passed at reopened
      completion, up from 466 before)
- [x] `docs/knowledgebase/command-policy-decision-model.md` documents the strict grammar and its quoting rationale
- [x] The order-agnostic-vs-fixed-template judgment call (made unattended) is recorded in Design Decisions

## Implementation TODO (reopened 2026-09-18)

**REOPENED 2026-09-18** for a second, tightly bounded fix round: an independent review found the double-quote
text-extraction gap flagged (but understated) during the 2026-09-17 reopening was also a WRONG DECISION for `--scope`,
not only a display bug for the `ask` dialog's diff/intent - see
`## Observed during implementation (reopened 2026-09-18)` above.

- [x] Re-flip status to in-progress for the reopened work
- [x] Write failing tests in `test_statement.py` for a new `Argument.literal_text` accessor that unwraps a double-quoted
      word's nested Parts, without touching `Argument.text` or its pinning test
- [x] Implement `Argument.literal_text` (`lib/statement.py`) to pass those tests
- [x] Write a failing regression test that `add-allow-policy --scope "user" --intent "x" "rg"` (double-quoted `--scope`)
      is ACCEPTED and reaches `ask`
- [x] Fix `lib/escalation_policy.py`'s `_classify_add_allow_invocation` to read tokens via `.literal_text` instead of
      `.text`, fixing both the wrong `--scope` denial and the empty diff/intent in one change
- [x] Re-author `test_add_allow_policy_transform_forces_ask_for_the_canonical_quoted_form` to assert the real diff and
      intent text directly, removing the now-false "content cannot be asserted" docstring claim
- [x] Correct the stale `--intent`-not-required docstring in `lib/add_allow_write.py`
- [x] Run the full command-policy suite and confirm exactly the 2 known xargs reds remain, no new failures
- [x] Correct `docs/knowledgebase/command-policy-decision-model.md`'s "Known display limitation, not fixed here" passage
- [x] Record item 1 in this file as a defect found in review
- [x] Update status to completed (reopened work)

## Implementation TODO

**REOPENED 2026-09-17** for one bounded addition: strict grammar for `add-allow-policy` (only
`--scope <user|project> --intent "<why>" "<command>"` accepted; anything the outer shell has touched, or with
missing/repeated/invalid `--scope`, missing `--intent`, or zero/multiple command arguments, denies with a structured
`Reason` explaining correct usage) plus the two batch-5 spec re-authorings this forces. See
`## Observed during implementation` (reopened) below for the grammar-ordering judgment call made without a human
available to ask.

- [x] Re-flip status to in-progress for the reopened work
- [x] Write failing unit tests in `test_escalation_policy.py` for the strict grammar: missing/ duplicate/invalid
      `--scope`, missing `--intent`, zero/multiple command arguments, a chained/ piped/backgrounded/substitution-bearing
      invocation, and a redirect on the invocation itself
- [x] Add the `AddAllowPolicyGrammarViolation` Reason kind to `lib/reason.py`
- [x] Implement the strict-grammar check in `lib/escalation_policy.py`'s `add_allow_policy_transform`, denying via the
      new Reason for every malformed shape and asking (unchanged) only for the canonical form
- [x] Register `AddAllowPolicyGrammarViolation`'s clause in `lib/reason_renderer.py`: "wrong use of add-allow-policy.
      Correct use: ..." plus the quoting rationale, teaching the redirect case by name
- [x] Add a `test_reason_renderer.py` case pinning the malformed-grammar prose
- [x] Re-author `test_add_allow_policy_forces_ask_as_the_durable_fix_escalation` and
      `test_add_allow_policy_forces_ask_for_the_project_scope_too` to use the canonical quoted form with `--intent`
- [x] Fix `test_the_two_escape_hatches_produce_different_outcomes_by_design`, which independently breaks under the
      strict grammar (same no-`--intent` shape) though not named in the reopening task
- [x] Add new Batch 5 cases asserting deny for malformed shapes, especially the unquoted-redirect case, and register
      them in `MATCHING_BRANCH_COVERAGE`
- [x] Run the full command-policy suite and confirm exactly the 2 known xargs reds remain
- [x] Update `docs/knowledgebase/command-policy-decision-model.md` with the strict grammar and its quoting rationale
- [x] Update status to completed (reopened work)

## Original Implementation TODO (completed 2026-09-17, prior to reopening)

- [x] Update status to in-progress
- [x] Re-read the Design Decisions before starting — every question this plan opened is settled; none are left to
      adjudicate during implementation
- [x] (DONE AT PLAN TIME) The forced-ask assumption was measured, not reasoned — see Assumptions. No further
      verification needed before implementing.
- [x] Write a failing test for a denial carrying MULTIPLE reasons (blocked command + sensitive path on one command)
- [x] Implement the Reason value objects and the reason list to pass it
- [x] Refactor the Reason value objects — split any that are too large to construct comfortably in a test
- [x] Write a failing test that every non-approving allowlist entry contributes its own Reason, including entries
      dropping out for a disallowed variable, substitution alongside filters, or a parser fallback
- [x] Implement full candidate-set reporting to pass it
- [x] Write a failing test that the decision is derived from the reason list's contents
- [x] Implement decision derivation to pass it
- [x] Add `assert_reason_includes` to the spec suite following the `assert_decision` convention
- [x] Convert the 7 existing `expected_reason` substring call sites to structural assertions
- [x] Rewrite the ordering cases to assert the FIRST reason, then prove they are not vacuous by reordering and observing
      red
- [x] Write the separate renderer test for reason prose
- [x] Implement the single reason renderer to pass it
- [x] Write a failing test that every deny reason ends with the `command-policy:find-auto-allowed-command` pointer,
      including a denial that also carries a near-miss
- [x] Implement the unconditional pointer in the renderer to pass it
- [x] Refactor the renderer
- [x] Write a failing test for the bypass result transformer: ordinary objection becomes passthrough
- [x] Write a failing test that bypass wrapping a blocked command or sensitive-path redirect becomes `ask`
- [x] Amend spec cases `:1412` (passthrough->ask) and `:1437` (deny->ask), including the `:1437` test name and docstring
- [x] Implement the bypass result transformer outside the pass pipeline to pass all of the above
- [x] Verify `:1423` still yields `deny` and that its hint names the wrap-it-explicitly route
- [x] Refactor the bypass transformer
- [x] Implement `add-allow-policy` forced `ask` with the JSON entry diff and `--intent`, including rejection of
      malformed invocations
- [x] Rewrite `BYPASS_REASON` so it makes no claim of guaranteed human review
- [x] Update `docs/knowledgebase/command-policy-decision-model.md` with the deny+hint reason model, the reason list, the
      unconditional equivalence pointer, and the three escalation paths
- [x] Run the full command-policy suite: `cd packages/command-policy/tests && nix-shell --run pytest`
- [x] Write the `## Interface` section: the `PermissionDecision` hand-back to leaf 20260914-213652, the trunk's
      now-false "only path that forces ask" claim, and the resolved pointer contract for leaf 20260915-011123
- [x] Update status to completed

## Interface

**What this leaf produces:** `packages/command-policy/lib/reason.py` (the `Reason` value-object family — five
categorical kinds, six near-miss kinds, one routing-only kind (`NotEscalatedByAnUnrelatedBypassWrapper`, never itself
the cause of a denial), plus one grammar-violation kind added on reopening (`AddAllowPolicyGrammarViolation`, also never
produced by the ordinary pipeline — see below)), `reason_renderer.py` (the single `render(reasons) -> str`), and
`escalation_policy.py` (`bypass_transform`, `bypass_chain_hint`, `add_allow_policy_transform` — three independent result
transformers `Config.decision_for` applies, in that order, after the ordinary pass pipeline runs). Also new:
`lib/add_allow_write.py` and real bodies for `bin/bypass-policy` (execs its argv) and `bin/add-allow-policy` (parses
`--scope`/`--intent`/the entry and writes it) — both graduated out of `test_scaffold.py`'s `STUB_ENTRYPOINTS` list.
Every Policy class (`sensitive_paths_policy.py`, `blocked_commands_policy.py`, `command_substitution_policy.py`,
`sensitive_variables_policy.py`, `redirect_path_validation_policy.py`, `allowed_command_policy.py`) now returns Reason
tuples from `decision()` instead of prose strings; `AllowedCommandPolicy` was restructured from a single boolean "does
any entry vouch" question into `_reasons_for_command`/`_entry_rejection_reason`, which report EVERY candidate entry's
own rejection cause rather than the old engine's single overwritten `rejecting_filter_def`. **(Added 2026-09-18,
reopened again)** Also touches `lib/statement.py` — owned by leaf `20260914-213321`, not this leaf — adding one new
accessor, `Argument.literal_text`, alongside (not replacing) that leaf's pinned `Argument.text`; see the Interface entry
below for what it fixes and why it is additive rather than a change to the pin.

**Contract for downstream leaves:**

- **`PermissionDecision.reason` HAND-BACK, resolved:** for `deny`, `reason` is a TUPLE of `Reason` value objects,
  ordered primary-first by pass order (never a string) — `Config._decision_for_statement` derives `deny` vs `allow` from
  whether this tuple is empty, and never stores the two separately. For `ask`/`passthrough` (both exclusively produced
  by `escalation_policy.py`, never by an ordinary Policy), `reason` stays a plain STRING — these are human-facing
  dialog/log text, not structured facts a future leaf needs to pattern-match on, and `PermissionDecision` itself
  enforces no shape on either constructor argument. Leaf `20260914-213825` (the hook-JSON mapping leaf) must call
  `reason_renderer.render(...)` to turn a `deny`'s reason tuple into text for the hook's protocol; an `ask`/
  `passthrough` string is already final text.
- **The trunk's "`add-allow-policy` is the ONLY path that forces `ask`" claim is now FALSE.** `bypass-policy` also
  forces it, for a blocked command, a sensitive path, or a redirect landing outside the project/allowed prefixes it
  cannot vouch for (`escalation_policy.bypass_transform`'s `_FORCES_ASK_REASON_TYPES`). Only `add-allow-policy`'s ask IS
  the durable config write, though — that half of the trunk's claim stands.
- **The equivalence pointer is a frozen contract for leaf `20260915-011123`:** the skill name is
  `command-policy:find-auto-allowed-command` (`reason_renderer.EQUIVALENCE_POINTER`), appended unconditionally to every
  non-empty rendered reason list, one short clause, produced by the renderer alone — no Policy or transformer appends it
  itself. Leaf `20260915-011123` reads `Config.explain()`'s rendered output to answer what the pointer promises; it does
  not need to parse a `Reason` tuple itself.
- **Near-miss vs categorical is a classification by ORIGIN** (`reason.CATEGORICAL_REASON_TYPES`/
  `NEAR_MISS_REASON_TYPES`), consumed today only by `bypass_transform` (which forces-ask on three specific categorical
  kinds and filters near-miss kinds out of the wrapper's own shell-level objections) and `bypass_chain_hint` (which only
  augments a categorical-forcing denial). The ordinary pipeline's own decision derivation does not branch on this
  distinction at all — any non-empty reason list denies, regardless of kind.
- **SUPERSEDED 2026-09-17 (reopened): `add-allow-policy`'s `--intent` obligation is now enforced by the GRAMMAR, not
  split across two runtime halves.** The original hand-back above (pipeline asks even without `--intent`) was true at
  first completion but was overridden by the operator when reopening this leaf: `add_allow_policy_transform` now denies
  a missing `--intent` outright (`AddAllowPolicyGrammarViolation("missing_intent")`), before any `ask` is ever shown.
  The bin script's write-side logic (`lib/add_allow_write.py`) still separately refuses to WRITE without a non-blank
  `--intent` — defence in depth, not redundant, since the pipeline check and the write check now agree rather than
  disagree.
- **`add-allow-policy` accepts exactly ONE grammar, reopened 2026-09-17 (Task 1):**
  `--scope <user|project> --intent "<why>" "<command>"`, flag order free but exactly one of each element. Every other
  shape whose command word is `add-allow-policy` — a redirect on the invocation, a pipeline/list/backgrounding/
  substitution touching it, or a missing/repeated/invalid `--scope`, missing `--intent`, or zero/multiple command
  arguments — denies via a new Reason kind, `reason.AddAllowPolicyGrammarViolation(violation: str)`, whose `violation`
  is a controlled-vocabulary code (`missing_scope`, `duplicate_scope`, `invalid_scope_value`, `missing_intent`,
  `no_command_argument`, `multiple_command_arguments`, `redirect_on_invocation`, `shell_touched`) rendered by
  `reason_renderer.py`'s `_ADD_ALLOW_POLICY_VIOLATION_EXPLANATIONS` map. This Reason kind is NEVER produced by the
  ordinary policy pipeline and is not part of `CATEGORICAL_REASON_TYPES`/`NEAR_MISS_REASON_TYPES` — it only ever appears
  alone, from `add_allow_policy_transform` itself, and never coexists with an ordinary pipeline reason. **Flag ORDER is
  deliberately NOT part of the grammar** (an unattended judgment call — see Design Decisions, 'Whether the strict
  add-allow-policy grammar fixes flag ORDER or only flag/positional shape' — reversible in one place,
  `escalation_policy._classify_add_allow_invocation`, if a reviewer intended the stricter fixed-template reading).
  **FIXED 2026-09-18 (reopened again):** `_classify_add_allow_invocation` reads every token via the new
  `Argument.literal_text` accessor (`statement.py`), not `Argument.text` — see the Interface entry below and
  `## Observed during implementation (reopened 2026-09-18)` for what this closes, including a WRONG-DECISION defect (a
  double-quoted `--scope "user"` was denied outright, not merely displayed wrong) found in review, previously
  undisclosed.
- **`AllowedCommandPolicy`'s own `warnings_sink`/`.warnings()` machinery no longer exists.** The uncompilable-filter-
  pattern `Warning` this leaf inherited from leaf `20260914-213652` is now surfaced by an independent, EAGER scan at
  `Config.from_dict` time (`_collect_allowed_command_filter_warnings`, using the new `Filter.try_from_definition`
  classmethod also used by `AllowedCommandPolicy`'s own match-time fail-closed path) — reachable via `Config.warnings()`
  for any config carrying the defect, independent of whether any command ever invokes the affected program. A future
  leaf adding a new construction-time-degradable filter defect should follow this pattern (a static scan at `from_dict`
  time), not resurrect a decision-time sink.

**Follow-ups for integrate:**

1. Leaf `20260914-213825` must call `reason_renderer.render(...)` when mapping a `deny` decision onto the hook's JSON
   protocol — `PermissionDecision.reason` is no longer directly printable for `deny`.
2. The trunk's Shared Context / Leaf Stream summary of `add-allow-policy` as "the ONLY path that forces ask" should be
   corrected at INTEGRATE (see above).
3. `docs/knowledgebase/shfmt-permissions.md` remains untouched and describes the LIVE engine (6.1.2) accurately; it is
   leaf `20260914-213825`'s job to retire/rewrite it at cutover, not this leaf's.
4. **(Added 2026-09-17, reopened; FIXED 2026-09-18, reopened again — no longer a follow-up)** `statement.py`'s
   `Argument.text`/`Redirect.target_text` still never unwrap a `DblQuoted` word's nested literal content — a deliberate,
   pinned design from leaf `20260914-213321`
   (`test_statement.py::test_a_braced_variable_reference_next_to_literal_text`), unchanged. What WAS load-bearing for
   `add-allow-policy` — its classification call site reading `--scope`/`--intent`/the command entry through that same
   naive `.text` — is fixed: `_classify_add_allow_invocation` now reads `.literal_text`, a new accessor on `Argument`
   that unwraps `DblQuoted` while leaving `.text` and its pin untouched. `Redirect.target_text` was NOT touched (no
   caller of it needed this); a future caller of `Redirect.target_text` hitting the same gap should follow the same
   pattern (an additive accessor, not a change to the pinned field) rather than re-deriving it. The actual config write
   was never affected either way (`lib/add_allow_write.py` parses real `argv`, never the shfmt AST).
5. **(Added 2026-09-17, reopened)** The strict-grammar reading is order-agnostic (an unattended judgment call — see
   Design Decisions) rather than a fixed positional template. If a human reviewer intended the literal "the ONLY
   accepted one" reading as a fixed template, the single place to tighten is
   `escalation_policy._classify_add_allow_invocation`.

## Related Past Improvements

- `improvement-20260913-125012-bypass-log-fidelity.md` — touches the same `bypass-*` command family (log-record fidelity
  for `bypass-shfmt-permissions`), though it addresses logging, not the deny-reason/escalation semantics this leaf
  covers.
