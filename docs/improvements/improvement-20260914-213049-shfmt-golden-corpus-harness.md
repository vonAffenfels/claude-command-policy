# Improvement 20260914-213049: Author Decision Specification for Command-Policy Engine

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-14
- Updated: 2026-09-16
- Plan started: 2026-09-14T22:20:35+02:00
- Plan finished: 2026-09-15T13:14:00+02:00
- Impl started: 2026-09-16T12:40:04+02:00
- Impl finished: 2026-09-16T23:17:14+02:00
- Trunk: 20260914-195111
- Kind: decomposed
- Depends on: 20260915-010936

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`

## WHAT DENY MEANS (read this before any case in the spec suite)

Settled by the user 2026-09-16, during batch 5 review, after this leaf had spent four batches quietly assuming the
opposite. Recorded at the top because every case below is misread without it.

**Deny is not prevention. Deny is routing.** The engine has exactly one privileged outcome — `allow` — and it is
privileged because it is the only one that runs with no human involved. Nothing else grants anything, and nothing else
stops anything either; the rest hand the decision onward.

| outcome       | what it actually says                                                                                      |
| ------------- | ---------------------------------------------------------------------------------------------------------- |
| `allow`       | Auto-approved. Runs unseen. The only outcome that grants.                                                  |
| `deny` + hint | "This could not be auto-approved." Claude is expected to TRY AGAIN with something that can be.             |
| `passthrough` | Reached only by `bypass-policy`: Claude's statement that no auto-approved route exists. The human decides. |
| `ask`         | Reached only by `add-allow-policy`: "make this permanently allowed", where the dialog IS the config write. |

The user's framing verbatim: deny is "our carriage to tell claude 'this command was not able to automatically run.
Here's a list of stuff you can do instead or ask this agent to find a command that does the same thing but with auto
approved commands. If the result of this command can genuinely not be achieved by any auto approved way prefix it with
bypass-command-policy to actively ask the user. But be aware that you **MUST** run auto approved commands whenever
possible.'"

THREE CONSEQUENCES THAT ARE EASY TO GET BACKWARDS:

1. **Denying more is not safer.** A denied command is not a blocked command — it is a command Claude will now attempt
   another way, or escalate. Narrowing `bypass-policy` therefore removes the escalation route WITHOUT adding protection,
   because bypass already routes to the human. This leaf nearly asked the user to widen the shell-performed-redirect
   veto on exactly that mistaken reasoning; the question was withdrawn.
2. **The hint is load-bearing, not decoration.** It is the routing information Claude acts on to find an auto-approved
   equivalent. A deny carrying a hint that names the wrong cause (see E7's ordering cases) sends Claude down a route
   that cannot work. This is also why the trunk's equivalence-search skill exists and why it runs AFTER a deterministic
   deny rather than inside it.
3. **The defect class this specification guards against is unintended AUTO-APPROVAL, not insufficient denial.** A
   fail-open filter (Flag List A) matters because the command then runs UNSEEN — not because "something dangerous got
   through". Every "fail closed" in this file means "decline to auto-approve", never "block".

WHAT THIS DID AND DID NOT CHANGE IN THE SUITE: no expected decision in any of the 87 cases changed. The cases were
right; the reasoning written around several of them was not. What changed is the prose — this section, the outcome
vocabulary in the knowledgebase article, and the suite's module docstring — plus the withdrawal of a veto-widening
question that only made sense under the prevention reading.

## Context / Why This Exists

**Origin / trigger:** Surfaced during planning of trunk 20260914-195111 (the Statement value-object full rewrite): of
371 tests in `test_analyze_bash_command.py`, only roughly 250-280 go solely through
`BashCommandAnalyzer(config).analyze(command)` and are implementation-independent. The other ~100-140 couple directly to
internal classes, raw AST dict shapes, `ParsedResult.paths`, or private methods, and break by design under the rewrite.
Without an implementation-independent specification the rewrite's correctness evidence would be 'a rewritten test suite
agrees with a rewritten engine.' During this leaf's first planning pass the scope shifted further: the specification
must be AUTHORED and reviewed, not mechanically captured, because current behaviour is demonstrably wrong in several
security-relevant cases. RE-PLANNED 2026-09-15 after the trunk's plugin-move and outcome-model invalidation.

**Consumer(s) of the output:** Every engine-building leaf in the trunk's nine-leaf stream (20260914-213153 Config,
20260914-213321 Statement, 20260914-213502 Filter/Parser, 20260914-213652 pipeline, 20260915-010959
deny-reason/escalation, 20260915-011123 skills, 20260914-213825 land-and-deprecate) verifies its own work against this
specification as the acceptance gate. Leaf 20260914-213153 additionally consumes the (now trimmed) flag list's naming
half. Leaf 20260914-213502 additionally consumes the external-script-parser-must-survive constraint and the xargs
wrapper-case hand-back. The trunk's INTEGRATE step consumes the whole result.

**Adjacent systems already covering part of the need:** The existing behavioural test suite (~250-280 of the 371 tests)
partially covers this today but targets the OLD outcome model (passthrough/ask), which the new deny+hint model
supersedes; it remains harvest-as-inspiration only, never adopted verbatim. No snapshot-testing plugin, golden-file
pattern, or fixture-corpus mechanism exists anywhere in the repo. `packages/command-policy/tests/conftest.py` (created
by the scaffold leaf, verified runnable this session — `cd packages/command-policy/tests && nix-shell --run pytest` → 3
passed) is the nearest precedent and is reused directly.

## This Improvement's Objective

LEAF 2 of trunk 20260914-195111 (RE-PLANNED 2026-09-15 after the trunk's plugin-move + outcome-model invalidation; this
re-plan is what lifts the leaf's prior DO-NOT-IMPLEMENT halt). AUTHOR THE DECISION SPECIFICATION for the
`command-policy` engine: a fresh, human-reviewed set of behavioural test cases, expressed purely through a newly-settled
public entrypoint, that defines what the engine SHOULD do under the trunk's new deny+hint outcome model — used as the
acceptance gate for every later leaf in the rewrite.

NOTE ON THE FILENAME: this file's slug still says 'golden-corpus-harness'. That name is a MISNOMER, kept only because
renaming would break the trunk's Leaf Stream pointer and this leaf's marker binding. The leaf was originally scoped as a
blind golden-corpus CHARACTERIZATION harness; it was deliberately redirected during its first planning pass into an
AUTHORED specification instead — see the design decision 'Characterization corpus vs authored specification'.

WHAT CHANGED IN THIS RE-PLAN (2026-09-15), all resolved this session:

1. **PACKAGE MOVE**: every path in this leaf's plan now targets `packages/command-policy/` (lib/ + thin bin/, no
   scripts/ dir — settled by the now-in-progress scaffold leaf 20260915-010936), not `packages/shfmt-permissions/`,
   which stays byte-for-byte untouched under the trunk's 'additive, deprecate only' cutover.

2. **THE ENGINE DOES NOT EXIST YET** when this leaf runs (it is leaf 2 of 9; the Statement/Config/Filter/Pipeline leaves
   that build it are leaves 3-6). Resolved: this leaf SETTLES the public entrypoint now —
   `Config.from_dict(cfg).decision_for(command)` in a new `packages/command-policy/lib/config.py` stub that raises
   `NotImplementedError` — and authors the full suite against it. The suite is deliberately RED (fails on
   import-succeeds-but-NotImplementedError, later on real assertions) until leaf 20260914-213652 (pipeline) wires the
   real body. This is an outside-in/acceptance-TDD pattern, chosen explicitly over writing the suite only once the
   engine exists, because (user's words) 'wiring up the tests after the implementation exists smells like going
   implementation first, which I'd rather avoid.'

3. **OUTCOME MODEL**: four of five decision knobs (defaultDecision, sensitiveVariableResponse, pathValidationResponse,
   filterRejectionResponse) DIE outright rather than being renamed — the config can no longer express leniency, only
   what is allowed; not-allowed collapses uniformly to deny+hint. Only commandSubstitutionResponse survives, reduced to
   {deny, via-allowed-commands}. The adjudicated flag list's rename section (B) and coverage-gap section (E) are
   reworked accordingly — moot renames for dying knobs are DROPPED rather than carried forward, per the user's explicit
   call: 'they are no longer needed. Replaced by a better system. Nothing to rename if they are gone.'

4. **NEW HARD CONSTRAINT** surfaced by the user during this re-plan: the external-script CommandParser provider route
   MUST survive the Filter/Parser family's rewrite into value objects (leaf 20260914-213502). Verbatim: 'I'm fine with
   the provided parsers being rewritten as VOs but the run a script as provider must stay open - that's a feature. A
   user is supposed to be able to write their own parsers for commands not provided by the plugin itself.' This leaf's
   spec suite must pin that contract as a first-class case, not merely exercise it incidentally through bundled parsers.

5. **SCOPE BOUNDARY CONFIRMED**: this leaf stays COMBINED (audit/flag-list half + authored-suite half in one leaf, not
   split) and does NOT implement the xargs wrapper parser itself — that is handed to leaf 20260914-213502 (Filter/Parser
   leaf), consistent with the Parser family being rebuilt there. This leaf only specifies the xargs case's expected DENY
   outcome.

WHAT THIS LEAF PRODUCES:

1. `packages/command-policy/lib/config.py` — the minimal RED-seam stub (`Config.from_dict`, `Config.decision_for`
   raising NotImplementedError). Leaf 20260914-213153 (Config) extends this file with real parsing/validation; leaf
   20260914-213652 (pipeline) wires the real `decision_for` body.

2. A fresh behavioural test suite, `packages/command-policy/tests/test_permission_decisions.py`, using the old 371
   shfmt-permissions tests as INSPIRATION rather than inheritance, calling ONLY
   `Config.from_dict(cfg).decision_for(command)`.

3. A REWORKED ADJUDICATED FLAG LIST (complete, in Implementation Notes): every place actual behaviour disagrees with
   what a config knob's NAME leads a competent reader to expect, each resolved as 'rename' (trimmed hand-back to leaf
   20260914-213153), 'behaviour fix' (its own follow-up improvement), or 'dissolved by the outcome model' (no action
   needed — the knob itself is gone).

4. The acceptance gate every later leaf checks itself against, RED until leaf 20260914-213652 lands.

This is leaf 2 of trunk 20260914-195111 (after the now-in-progress scaffold leaf 20260915-010936) and every
engine-building leaf after it depends on it.

SCOPE WARNING FOR THE TRUNK (carried forward, still true): this leaf grew well past its original brief — it carries an
audit, a trimmed adjudicated rename list, several behaviour-change proposals, a settled public entrypoint, and a 200-400
case authored suite reviewed in batches. It remains the largest leaf in the nine-leaf stream.

## Proposed Approach

AUTHOR, DO NOT CAPTURE. The specification is written by a human-reviewed process, not mechanically recorded from the
current engine.

**Step 1** — Blind naive reading (DONE, first planning pass). An agent given ONLY knob names, defaults and valid-value
lists — no implementation, no tests — wrote what each knob should do and flagged 17 ambiguous names.
Package-independent; unaffected by the plugin move (trunk Shared Context item D) — read, not re-derived.

**Step 2** — Evidence extraction (DONE, first planning pass). Extracted what the existing tests actually assert per knob
value, plus which legal values have no coverage. Package-independent.

**Step 3** — Diff and adjudicate (DONE, first planning pass; see the Flag List). Every mismatch was presented to the
user, who decided per item: fix the name, or fix the behaviour.

**Step 3b** — RE-ADJUDICATE against the new outcome model (DONE this re-planning session, 2026-09-15). Flag List section
B (renames) and section E (coverage gaps) are reworked: entries tied to a knob that DIES under the new model
(defaultDecision, sensitiveVariableResponse, pathValidationResponse, filterRejectionResponse) are dropped rather than
carried forward as renames — there is nothing left to rename once the knob itself is gone. Sections A, C, D (except D2,
which was specifically the filterRejectionResponse rename and is dropped with it), and F are package-independent and
outcome-model-independent; re-read unchanged.

**Step 3c** — SETTLE THE PUBLIC ENTRYPOINT (DONE this re-planning session). `Config.from_dict(cfg) -> Config` and
`Config.decision_for(command: str) -> PermissionDecision` in a new `packages/command-policy/lib/config.py`, the stub
raising `NotImplementedError`. Chosen over a Statement-first shape
(`Statement.for_command(cmd).with_config(cfg).permission_decision()`, which pre-empts leaf 20260914-213321's Statement
surface) and over a bare free function (least domain-expressive), because Config.fromText is already the trunk's own
settled deliverable for leaf 20260914-213153 — the seam is a method on an object that is definitely being built anyway.
This is the RED seam: leaf 20260914-213153 extends `lib/config.py` with real parsing/validation (must not replace the
`decision_for` signature), leaf 20260914-213652 wires `decision_for`'s real body. The suite fails at NotImplementedError
until then — deliberate, not a defect.

**Step 4** — Author the fresh test suite in a NEW file, `packages/command-policy/tests/test_permission_decisions.py`,
using the existing 371 shfmt-permissions tests as inspiration for coverage territory but writing cases anew against
`Config.from_dict(cfg).decision_for(command)` only. `packages/shfmt-permissions` stays byte-for-byte untouched by this
leaf (its migration is leaf 20260914-213825's job); the old suite there keeps guarding the still-live engine while this
new one defines the target for the not-yet-built one.

**Step 5** — REVIEW IN THEMED BATCHES. The user reviews cases one config area at a time: (a) the surviving
decision-adjacent knob plus the uniform deny+hint default, (b) filters, (c) paths and redirects, (d) wrappers and
command propagation — INCLUDING an explicit case for the external-script CommandParser contract, not just bundled
parsers, (e) bypass and add-allow-policy escalation. Do NOT author all cases and present them in one pass.

**Step 6** — The suite becomes the permanent regression asset and the trunk's acceptance gate, staying RED until leaf
20260914-213652 lands.

HARVEST AS INSPIRATION, NOT INHERITANCE (unchanged): the existing tests define which branches, knob combinations and
command shapes are worth reaching; their asserted decisions are NOT automatically adopted as correct — several assert
outcomes (passthrough/ask) the new model no longer produces.

EXTERNAL-SCRIPT PARSER MUST SURVIVE (new constraint, settled this session): CommandParser (the external-script provider
— a config author points `commandParser` at their own script, which the engine invokes as a subprocess and trusts its
JSON `named` output with no schema validation, per Flag List F5) is a public extensibility feature, not an
implementation detail. It must remain available after leaf 20260914-213502 rebuilds the Parser family as value objects.
This leaf's spec suite pins the contract explicitly; that leaf's Interface must confirm it kept the route open.

## Affected Components

**Files:**

- `packages/command-policy/lib/config.py:NEW` — `Config.from_dict(cfg)` constructor, `Config.decision_for(command)`
  raising NotImplementedError; the RED seam leaf 20260914-213153 extends and leaf 20260914-213652 wires
- `packages/command-policy/tests/test_permission_decisions.py:NEW` — the specification suite, RED until leaf
  20260914-213652 lands
- `packages/command-policy/tests/conftest.py:EXTEND` — add the MANDATORY cwd-pinning fixture; existing
  `run_entrypoint`/sys.path bootstrap (verified runnable this session) is kept as-is
- `packages/command-policy/tests/shell.nix:no change expected` — already pins python313 + pytest + shfmt (verified this
  session)

**Classes/Functions:**

- Config
- PermissionDecision
- CommandParser
- ProvidedParser

**Modules:**

- command-policy

## Implementation Notes

THE CENTRAL DISCIPLINE: this leaf authors a specification, so it must never silently adopt current behaviour as correct.
Every case in the fresh suite is there because someone decided the decision it asserts is the RIGHT decision.

MEASURED DECISION-SPACE SIZE (unchanged by the outcome model — this targets MATCHING logic, not the collapsed outcome
vocabulary): ~16 decision points inside `analyze()` plus ~14 nested in the invocation/call-expr checks in the old
engine, ~30 total. The new model collapses what HAPPENS after a non-match (four knobs become one constant, deny+hint)
but does not collapse the matching logic itself — sensitivePaths is still pass 0, filters still need to match or not,
the ~30-branch target still governs coverage.

THE COMMAND-POLICY PACKAGE AND THE RED-SUITE DISCIPLINE: the public entrypoint is
`Config.from_dict(cfg).decision_for(command)` in `packages/command-policy/lib/config.py`. This leaf creates only a stub
(raises NotImplementedError) — it does NOT implement Config parsing (leaf 20260914-213153's job) or the decision
pipeline (leaf 20260914-213652's job). The suite is authored to be RED: it must COLLECT cleanly (the import must
succeed) but every case fails with NotImplementedError until the pipeline exists. A collection/import error is a bug in
this leaf; a NotImplementedError at assertion time is the correct, deliberate RED state. Reused directly from the
scaffold leaf (verified runnable this session, 3 passed): `packages/command-policy/tests/conftest.py`'s sys.path
bootstrap onto `lib/`, and `tests/shell.nix`'s python313+pytest+shfmt pin.

EXTERNAL-SCRIPT PARSER EXTENSIBILITY MUST SURVIVE (new constraint, settled this session, see Design Decisions).
CommandParser already exists today as the sole mechanism (alongside ProvidedParser, which delegates to it) capable of
populating a script-supplied `named` value with NO schema validation (Flag List F5, already-confirmed). The user ruled
explicitly that this script-provider route is a public feature enabling users to write parsers for commands the plugin
does not bundle, and it must not be collapsed away when leaf 20260914-213502 rebuilds the Parser family as copy-on-write
value objects. This leaf's spec suite therefore includes at least one case that exercises a script-provided parser
end-to-end (publishing a sub-command, consumed via the entry's `nestedCommand` filter, re-entering `decision_for` and
hitting blockedCommands) as a FIRST-CLASS case, not only as incidental coverage of a bundled parser.

### G. SURFACED DURING IMPLEMENTATION (2026-09-16) — UNKNOWABLE EXPANSION DEFEATS A CONTENT RESTRICTION

Raised by the user while reviewing spec batch 1, and NOT anticipated by the planned Flag List. It is a BEHAVIOUR
REQUIREMENT on the rebuilt engine, handed to leaf 20260914-213652 (pipeline) and leaf 20260914-213502 (filters), not a
naming issue.

**CORRECTION, 2026-09-16, before authoring batch 2.** This section was first written claiming the old engine "runs
filters against the literal arguments only, silently treating unseen text as absent." THAT CLAIM IS FALSE and is
retracted here rather than quietly edited away. Measured at `analyze-bash-command.py:2060-2064`: an entry that HAS
filters and whose args contain a command substitution is SKIPPED (`continue`) with the comment "A filter cannot match
argument text that is produced at runtime, so an entry that filters cannot vouch for this invocation." The old engine
already reaches G1's and G3's conclusions analytically. The error was mine, made by reasoning from the outcome
(passthrough) back to a supposed cause (filters running blind) without reading the loop — the same overstate-a-finding
failure this trunk's Assumption-Verification discipline exists to catch.

WHAT IS ACTUALLY NEW IN SECTION G, restated correctly:

- **The outcome changes, not the analysis.** The old engine routes this skip to `filterRejectionResponse` (default
  `passthrough`), so today a filtered entry plus a substitution silently defers to the human dialog. Under the new model
  it is deny+hint. That is a real behaviour change, but it is the outcome model doing it, not section G.
- **Section G's actual contribution is PRECISION, and it RELAXES the old rule in two cases.** The old engine's skip is
  BLANKET — it fires for any filter whatsoever, which is exactly the "substitution plus any filter means deny" rule G2
  rejects. G2 (presence provable) and G5 (index pinned ahead of the substitution) both specify ALLOW where the old
  engine rejects. Section G is therefore stricter than the old engine in outcome and more permissive in reach; it is not
  the closing of a fail-open hole, and must not be described as one.
- **G4 is the case where the old engine's bluntness happens to land on the right answer** for the wrong reason. It
  rejects the shifted-index invocation because it rejects everything, not because it reasoned about position.

**G1.** A command substitution's expansion is unknowable at analysis time, so a filter asserting the ABSENCE of content
(`action: "block"`) can never be satisfied next to one. `echo $(echo safe)` against an entry that forbids
`--forbidden-flag` must DENY even under `commandSubstitutionResponse: "via-allowed-commands"` and even though the inner
`echo` is itself allow-listed — nothing static rules out the substitution expanding to exactly the forbidden token. The
old engine agrees analytically (it skips the entry) but routes the skip to `filterRejectionResponse`, default
`passthrough`; the change here is the outcome, not the reasoning.

**G2.** The rule is ASYMMETRIC, and the asymmetry is the whole of its precision: word-splitting a substitution's output
can only ADD arguments, never remove a literal already in the AST. PRESENCE is therefore still provable —
`echo --required-flag $(echo safe)` satisfies an `action: "required"` filter — while ABSENCE is not. A blanket
"substitution plus any filter means deny" rule would be wrong, not merely conservative.

**G3.** A bare entry restricting no argument content is unaffected: `echo $(echo safe)` with a program-only
allowedCommands entry stays ALLOW, because an entry that permits any arguments is not made less true by arguments it
cannot see. The unknowability only bites once the entry makes a claim about content.

**G4.** RESOLVED 2026-09-16 (user settled it during batch 1 review rather than deferring it to batch 2): index-based
filters (`argumentAtIndex`, `positionalArgAtIndex`) face a THIRD case neither G1 nor G2 covers. A substitution expanding
to anything other than exactly one word SHIFTS every index after it, so PRESENCE being provable (G2) is not enough —
POSITION must be provable too. `echo $(echo just-one-argument) --required-second-argument` must DENY against a
`required` filter pinning argument index 1, even though the flag is literally present, because the substitution may
expand to zero words or five and move it. User's words: 'we can't make sure the second argument will be what we expect
it to be.' Holds identically for both index-based filter types — `positionalArgAtIndex` counting only positionals where
`argumentAtIndex` counts every argument does not rescue either.

**G5.** The shift bites only FORWARD, which keeps G4 from collapsing into the blanket rule G2 already rejected. A
substitution can shift only what FOLLOWS it, so an index pinned by a literal AHEAD of the substitution stays provable:
`echo expected-first $(echo tail)` satisfies a `required` filter on positional index 0 and is ALLOWED. Specified with a
control case so the engine cannot satisfy G4 by denying every index filter that shares a command with a substitution.

**G6.** An index-based filter with `action: "block"` next to a substitution needs no separate rule — it is already
denied by G1 (absence unprovable) regardless of index. G4 is therefore about `required` specifically; the `block`
direction is subsumed, not overlooked.

### THE ADJUDICATED FLAG LIST

Produced by diffing a blind name-only reading against extracted test/code evidence, then RE-ADJUDICATED this session
against the new outcome model. This is the hand-back to leaf 20260914-213153 (renames) and to follow-up improvements
(behaviour fixes).

#### A. FAIL-OPEN HOLES — a typo silently widens the allowlist. All BEHAVIOUR FIXES (follow-up improvements). UNCHANGED by the outcome model — package-independent, re-read not re-derived.

**A1.** Invalid filter `action` is a silent no-op — all nine filter `matches()` implementations end `return True` for
any action other than 'block'/'required'; `config_loader` validates ONLY the five decision knobs, so a typo'd action
silently widens the allowlist under entry-level OR. UNTESTED. ADJUDICATED THIS SESSION (2026-09-15) — close at BOTH
layers: `Config.fromText` rejects an unknown filter `action` at load time (leaf 20260914-213153), AND the engine treats
a filter it cannot construct as fail-closed at match time (leaf 20260914-213652), matching A3's already-settled
precedent. The spec needs a case for each layer — a config-load rejection case and, separately, an engine-level
fail-closed case for whatever cannot be caught at load time.

**A2.** Unknown filter `type` is silently skipped — `create_filter` returns None, the loop does `continue`; a typo'd
type REMOVES the restriction. Related: `create_parser` falls back to DefaultParser for an unknown type, and
DefaultParser can NEVER populate `named`, so a typo'd parser type silently disables propagation too. ADJUDICATED THIS
SESSION (2026-09-15) — same two-layer close as A1: load-time validation (leaf 20260914-213153) plus engine fail-closed
at match time (leaf 20260914-213652), defense in depth rather than either alone.

**A3.** Propagation is fail-open when nothing is extracted — ADJUDICATED (first pass): make it FAIL CLOSED — an entry
declaring it evaluates a named value as a command, which extracts nothing, must NOT match. This is now the engine's own
job (leaf 20260914-213652), not this leaf's. Retires the hand-written safety-belt filter idiom.

**A4.** commandSubstitutionResponse 'block' does not block quoted heredocs — `CommandAst.with_heredoc_normalized_to_lit`
rewrites a heredoc to a Lit node BEFORE the substitution check, bypassing it even when the inner command is not
allow-listed.

**A6.** An `optionValue` filter is SILENTLY INERT unless the entry's parser declares that the option consumes a value.
SURFACED 2026-09-16 while authoring spec batch 2, and verified against the code rather than reasoned about:
`DefaultParser` (`analyze-bash-command.py:110-115`) makes every `-`-prefixed token an option with `arguments=[]`, so
`OptionValueFilter` (`:641-661`) joins an empty list, matches nothing, and under `action: "block"` returns `not False`
-> the filter PASSES. A config author who writes
`{"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}` and no `commandParser` gets a filter
that vouches for exactly the invocation it was written to stop. Distinct from A1/A2: no typo is involved and both the
type and the action are valid, so neither of those validations catches it. ADJUDICATED: load-time rejection (leaf
20260914-213153) — whether an option consumes a value is knowable from the entry's own parser config with no command in
hand, so this is catchable at the layer where the author can still act on it. Both cases are specified in the suite: the
filter WITH a `structured` parser denying, and the filter without one failing to load.

**A6b.** ENFORCING A6 REQUIRES A PARSER CAPABILITY THAT DOES NOT EXIST — user's point, 2026-09-16, and it upgrades A6
from a validation rule into an interface requirement on leaf 20260914-213502. To reject an `optionValue` filter naming
an option the parser cannot populate, load-time validation must ask the entry's parser TWO questions: _do you know this
option?_ and _does that option consume a value?_ Nothing can answer them today. CORRECTED FACT (the user believed the
default parser was configurable for this; it is not): `DefaultParser` takes NO config whatsoever — constructed as
`DefaultParser()` at all three call sites (`:748`, `:759`, `:2078`), no `__init__`, and its docstring states "No
argument consumption logic is applied." Option-arity knowledge lives ONLY in `StructuredParser`, privately.

The two questions are genuinely distinct, which is why the spec carries four cases rather than two: an option declared
as a BARE FLAG answers yes to the first and no to the second, and an `optionValue` filter needs both.

CONSEQUENCE WORTH CARRYING TO LEAF 20260914-213502: if the default parser gains option declarations — which is what the
user's four cases specify — then `DefaultParser` and `StructuredParser` differ only by how much they have been told, not
by kind. The rebuilt Parser family should consider collapsing them into one configurable parser rather than porting a
distinction that no longer carries weight.

**B7.** PARSER CONFIG IS THE ONE SNAKE_CASE ISLAND in a camelCase vocabulary — noticed 2026-09-16 while choosing the
config shape for the A6b cases. `allowedCommands`, `blockedCommands`, `matchFullParameter`, `optionPresent`,
`pathOptions`, `pathPositionals`, `additionalAllowedPrefixes` are all camelCase; `options_with_arguments`,
`double_dash_stops` and `timeout_ms` are snake_case, inside the SAME parser config dict that also holds camelCase
`pathOptions`/`pathPositionals`. RENAME, handed to leaf 20260914-213153 with the rest of section B. The spec suite is
written against the camelCase target (`optionsWithArguments`), so the rename is already pinned by the cases.

**A7 (new, 2026-09-16, follows from the B5 reshape).** A `nestedCommand` filter on an entry whose parser CANNOT publish
sub-commands is rejected at config load time. Neither the default nor the structured parser can publish on the dedicated
sub-command channel, so such a filter could never have anything to check and — under A3/D6's fail-closed rule — would
deny every invocation of that entry forever. This is the A6 pattern one filter family over: a filter is only as capable
as the parser feeding it, and the parser's own config settles the question with no command in hand. HANDED TO LEAF
20260914-213153 with the rest of the load-time validation set (A1, A2, A6, E6's unrecognised `fallback`).

**A5 STATUS CORRECTED 2026-09-16.** This entry said the fix "Belongs to improvement 20260912-234028 (HALTED on a FAIL
review)". That improvement is at status `completed`, and the four bypasses are STILL LIVE — measured this session
against the live engine with `{allowedCommands: ['cat','echo'], sensitivePaths: []}` and CLAUDE_PROJECT_DIR pinned to
cwd:

| command                            | measured today |
| ---------------------------------- | -------------- |
| `cat ./README.md > "/etc/passwd"`  | allow          |
| `echo x > "$HOME/.bashrc"`         | allow          |
| `echo x >> ~/.ssh/authorized_keys` | allow          |
| `cat < ~/.ssh/id_rsa`              | allow          |
| `cat ./README.md > '/etc/passwd'`  | passthrough    |
| `cat ./README.md > /etc/passwd`    | passthrough    |

Two conclusions. First, the bypasses have no owner in the current improvement set — the improvement this entry deferred
them to finished without closing them. They are owned HERE now: the spec asserts deny for all six, and leaf
20260914-213652 closes them by implementing F2's fail-closed invariant (an unresolvable target is denied, never resolved
to cwd), which is the actual mechanism behind all four. Second, the bare and single-quoted forms PASSTHROUGH under the
default rather than denying — they deny only with `pathValidationResponse: "deny"` explicitly set. Both the planning
note and this suite's first draft overstated that as "already deny".

**A5.** Double-quoted and tilde redirect targets bypass redirect validation — confirmed by execution. Belongs to
improvement 20260912-234028 (HALTED on a FAIL review), not to this leaf; carried here as required specification cases.

#### B. NAMES THAT TEACH THE WRONG MODEL — RENAMES, handed to leaf 20260914-213153. REWORKED THIS SESSION: the old B3 (filterRejectionResponse rename) is DROPPED — that knob DIES under the new outcome model rather than being renamed; there is nothing left to rename once the CASE A/B distinction it toggled is abolished by the model itself (trunk Consequence 4). The sensitiveVariableResponse half of the old B6 vocabulary-collision note is likewise dropped (that knob also dies). Everything below is a STRUCTURAL/MATCHING knob, not a decision-outcome knob, and is therefore unaffected by the outcome model — unchanged from the first planning pass.

**B1.** `allowedVariables` — reads as narrowing a permissive default; actual semantics are DENY-BY-DEFAULT.
Highest-severity naming defect. Suggested direction: a name exposing the deny-by-default, e.g. onlyTheseVariables.

**B2.** `additionalAllowedPrefixes` — BOTH blind readings ('command-line prefix' and 'wrapper program') are wrong; it is
filesystem PATH prefixes for path validation.

**B4 RESOLVED 2026-09-16 — user settled the target name during batch 3 review: `pathValidation: false` becomes
`hasNoPathParameters: true`.** The old name promises to switch off "path validation" wholesale and delivers something
far narrower; the new name asserts a FACT ABOUT THE ENTRY — this program takes no path parameters — from which skipping
the argument-path check FOLLOWS, and which is silent about redirect validation and the `paths` filter because it makes
no claim about them. The scoping stops being a gotcha a reader must learn and becomes a consequence of the sentence.

POLARITY INVERTS, and this is the part an implementer can get backwards silently: the disabling value is now `true`, not
`false`. `pathValidation: false` and `hasNoPathParameters: true` are the same configuration. An entry carrying
`hasNoPathParameters: false` is asserting that it DOES have path parameters, i.e. the ordinary default. Getting this
backwards inverts a security control without any syntax error, so leaf 20260914-213153 should reject the old key
outright rather than silently accept it during migration. The user wrote the rename as `hasNoPathParameters: false`,
carrying the old value across; the polarity above is this leaf's reading of the name's plain meaning and is flagged for
confirmation rather than assumed settled.

**B4 (original entry).** `pathValidation: false` (the PER-ENTRY structural flag — distinct from the now-dead
pathValidationResponse OUTCOME knob) — turns off ONLY the entry's argument-path check; it does NOT disable
redirect-target validation and does NOT disable the `paths` filter (independent mechanisms).

**B5 SUPERSEDED 2026-09-16 — the rename is moot; the key itself is gone.** The user settled during leaf
20260914-213652's planning that nested (wrapper sub-command) evaluation is an ORDINARY FILTER,
`{"type": "nestedCommand"}`, not an entry-level key at all. User's words: "this becomes a properly composable filter
fitting much better in the existing system" — filters already AND-compose within an entry and OR-compose across entries,
so nested evaluation inherits both rather than running a parallel opt-in mechanism beside them. Leaf 20260914-213652's
planner recommended AGAINST the change and was deliberately overruled; recorded so nobody restores the key on the
planner's reasoning.

Consequences for THIS leaf, all applied: batch 4 was re-authored against the filter shape (2026-09-16, with the user's
approval); the filter needs NO key naming what to read, because sub-commands arrive on the parser's dedicated
sub-command channel rather than through a named value; and the A3/D6 fail-closed property survives the reshape intact —
an entry whose `nestedCommand` filter has nothing to check simply does not pass, and as an ordinary filter it fails the
entry the way any other failing filter does, with no special-casing. Converting old-format configs belongs to the
migration skill (leaf 20260915-011123); the engine carries no back-compat shim. The `nestedCommand` spelling was settled
HERE, by this suite, since the suite is the acceptance gate — leaf 20260914-213652 recorded the filter's behaviour but
never its config spelling.

**B5 (original entry, superseded above).** `propagate` — ADJUDICATED RENAME (first pass, unaffected by outcome model):
`evaluateNamedValueAsCommand: "{named value key}"`. Chosen over `evaluateNamedExportAsCommand` because 'export' would be
a THIRD word for a concept the code already calls `named`/`namedValue`.

**B6.** Vocabulary collisions worth resolving while renaming (sensitiveVariableResponse half dropped — that knob is
gone): `pluginProgram` means a GLOB, not a plugin. `allowedPaths` (Read/Grep/Glob) is indistinguishable from the bash
path machinery. `argumentAtIndex` vs `positionalArgAtIndex` hides an off-by-one in one adjective. `matchFullParameter`
vs `parameterRegex` leaves unanchored-substring matching as the unmarked default. commandSubstitutionResponse's
surviving 'block' value still collides with filter `action`'s 'block' meaning 'entry does not match' rather than 'deny'
— worth resolving now that it is the only decision-adjacent knob left.

#### C. BEHAVIOUR SAFER THAN THE NAME SUGGESTS — no action, record so it is not 'fixed' by mistake. UNCHANGED.

**C1.** The bypass wrapper (now `bypass-policy`) yields PASSTHROUGH, not allow — the human still sees the host dialog;
under the new model this is branch 2 of the outcome model, more important than before, not less.

**C2.** `add-allow-policy` (formerly `propose-allow`) commands yield a hardcoded ASK — under deny-by-default this
remains the durable-fix escalation, per trunk Consequence 3.

**C3.** sensitivePaths hard-denies rather than being inert-unless-opted-into.

**D7 (new, 2026-09-16).** ARGUMENT PATHS ARE JUDGED AFTER NORMALISATION, specified explicitly at the user's request
rather than left as a side effect of other cases ("explicit testing is better"). Five cases pin it, with the pinned
project dir substituted for `{project}`: `/not-allowed.txt` -> deny; `relative-to-project.txt` -> allow;
`{project}/file.txt` -> allow; `{project}/../file.txt` -> deny; `../file.txt` -> deny. The two `..` entries carry the
weight — both are written to look like paths the project owns and both resolve outside it, so a check comparing the
string as written would admit either.

#### D. ADJUDICATED (user decisions, first pass unless noted). D2 (filterRejectionResponse rename) is DROPPED this session — see B above; the knob dies, so there is nothing to rename.

**D1.** sensitivePaths matching — KEEP SUBSTRING, specify and test it explicitly, INCLUDING the false-positive
direction, since no current test distinguishes substring from exact.

**D3.** blockedCommands + wrapper commands — NOT an accepted static-analysis limitation. The trailing-positional wrapper
pattern already ships twice (`timeout.py`, `nix.py`) and a propagated command fully re-enters the decision pipeline and
hits blockedCommands; only the xargs parser artifact is missing, and building it is now explicitly leaf
20260914-213502's job (Parser family rebuild), not this leaf's — this leaf only specifies the expected DENY case. KNOWN
RESIDUAL LIMIT to specify rather than pretend away: propagation sees only the wrapper's command text, never stdin-piped
operands, so blockedCommands and program-level allowlisting work on the propagated command but sensitivePaths on piped
operands cannot.

RESOLVED THIS SESSION (2026-09-15) — bare `xargs` (no command argument, defaults to `echo`, publishes no command) is
DISSOLVED as an open question, not merely settled: A3 already made a whole entry declaring nested command evaluation NOT
MATCH when its parser extracts nothing (not just the propagation sub-check — the entry itself), and under the new
outcome model a non-matching entry always falls through to deny+hint (there is no knob left that could route a non-match
to allow). Bare `xargs` is therefore deny+hint by construction, with no separate policy choice remaining to make. The
spec needs a case asserting this, but there is nothing left to decide.

**D3 CASE CORRECTED 2026-09-16, during batch 4 review — the most consequential error caught this session.** The first
draft of the residual-limit case asserted that `echo /vault/secret.txt | xargs cat` is ALLOWED, on the reasoning that
propagation cannot see piped operands. MEASURED: it DENIES. `sensitivePaths` is checked against every literal in the
command (`_extract_all_literals`), independent of which program receives it, so a path written on the line is caught
whether or not a pipe follows. Had the case shipped, the specification would have required the new engine NOT to catch a
sensitive path sitting in plain sight — a weakening, written into the acceptance gate, justified by a plausible-sounding
sentence about static analysis.

The real limit is narrower: only content the command REFERENCES rather than CONTAINS is out of reach, e.g.
`cat filelist.txt | xargs cat` where the sensitive path lives inside `filelist.txt`. The spec now carries BOTH halves as
a pair, because the ALLOW half alone reads as "piping defeats sensitivePaths" and would invite an implementation that
stops scanning literals once a pipe is present.

**D4.** paths filter relative `exactly` resolution against process CWD rather than CLAUDE_PROJECT_DIR — BUG, follow-up
improvement, unaffected by outcome model.

**D5.** The `paths` filter's rejection message borrows pathValidation's prefix vocabulary though the paths filter has no
prefixes — fix in the fresh suite's message assertions.

**D6.** Propagation fail-open — MAKE IT FAIL CLOSED in the engine (see A3) — now leaf 20260914-213652's job.

#### E. COVERAGE GAPS — legal configs nothing tests. REWORKED THIS SESSION: old E2 (defaultDecision 'ask' + filter rejection), E3 (filterRejectionResponse vs no-filter passthrough disambiguation) and E9 (pathValidationResponse/filterRejectionResponse 'passthrough' explicit values) are DROPPED — all three were specifically about knobs, or knob VALUES, that no longer exist. What replaces them: a single explicit case asserting that a program not present in allowedCommands AT ALL and a program that IS allow-listed but whose invocation was rejected now produce the SAME outcome (deny+hint) — the CASE A/B distinction the dropped knobs used to toggle is abolished by the model itself, so one case suffices where three used to be needed.

**E1.** A program in BOTH allowedCommands and blockedCommands — precedence unambiguous in code (blocked wins) but
unasserted; survives unchanged.

**E4.** Multiple sensitive variables in one command — REWORDED: no longer conditioned on a 'sensitiveVariableResponse:
ask' knob value (that knob is gone; sensitive-variable detection now always denies), but the reason-accumulation
ordering (iteration over a SET, non-deterministic) is still untested and the specification must either pin an order or
assert order-independently.

**E5.** `action: "block"` with an out-of-bounds index / absent option / absent named value REJECTS rather than passes —
a 'block' rule that blocks by ABSENCE; survives unchanged, filter-level not knob-related.

**E6.** Parser `fallback` values 'deny'/'legacy' — the OLD footgun ('deny' silently routing through
filterRejectionResponse's passthrough default) is DISSOLVED by the outcome model itself, since filterRejectionResponse
no longer exists to silently default to passthrough — worth noting as 'resolved by the model change' in the
specification rather than as a bug needing its own fix; still verify 'legacy' end-to-end and an unrecognised fallback
value falling through cleanly.

**E7.** Ordering precedences (substitution before sensitive-variable, sensitive-path deny before deferred
sensitive-variable, sensitive-variable before allowlist) are derivable from code but unasserted — survives, though the
EXACT Pass numbers are leaf 20260914-213652's to declare; this leaf specifies the ORDERING PROPERTY, not a numeric Pass
value.

**E8.** additionalAllowedPrefixes near-miss guard (`/home/user` vs `/home/username`) — guard exists, untested; survives
unchanged.

#### F. STRUCTURAL FACTS THE FRESH SUITE MUST HONOUR. UNCHANGED, still apply to the new package.

**F1.** TEST-INTEGRITY TRAP (historical, about the OLD suite) — a green tilde-redirect test there was green for an
ARTIFACTUAL cwd-vs-CLAUDE_PROJECT_DIR mismatch reason, not because the behaviour was actually safe. EVERY path/redirect
case in the fresh command-policy suite MUST pin cwd explicitly to avoid reproducing this false confidence.

**F2.** FAIL-CLOSED INVARIANT, stated as a named property: an empty or unresolvable extracted redirect target must be
treated as unresolvable and DENIED, never silently resolved to cwd.

**F3.** `packages/command-policy/tests/conftest.py` ALREADY EXISTS (created by the scaffold leaf) — unlike the old
shfmt-permissions package, no importlib-reimplementation problem exists here; this leaf only ADDS the cwd-pinning
fixture to it.

**F4.** An equivalent of the old suite's `assert_config_is_reachable` (re-running every test config through real
validation so unreachable knob values cannot be asserted against) is still required — it covers only decision-adjacent
knob shapes; there is still no equivalent guard for allowedCommands/filters shapes, which is precisely where A1/A2 live.

**F5.** PARSER CAPABILITY FACTS (verified, unchanged, and now load-bearing for the external-script-parser constraint):
DefaultParser and StructuredParser can NEVER populate `named`. Only CommandParser (external script) and ProvidedParser
(bundled, delegates to CommandParser) can populate `named`, with NO schema validation — `named` is unvalidated
pass-through from the script's JSON, and must remain a STRING per the propagation guard.

**F6.** ENVIRONMENT for the NEW suite: `cd packages/command-policy/tests && nix-shell --run "pytest -v"` (verified
runnable this session — 3 passed, 0.16s, before this leaf adds anything). Because the specification is AUTHORED rather
than captured from one engine+shfmt pairing, the 'a corpus is only valid for the shfmt version that produced it' concern
is largely dissolved — but AST-shape-dependent cases can still move under a shfmt upgrade.

## Open Questions

Two of the three questions carried from the first planning pass were resolved this session (2026-09-15) — see A1/A2 and
D3 above for the reasoning. Only one remains genuinely open, and it is correctly out of scope for THIS leaf to decide:

- **Migration/compat for the (now trimmed) renames in section B**: these are public config keys already present in
  users' `shfmt-permissions.json` files, so a rename is a breaking change even after the move to `command-policy.json`.
  Whether to support old keys with a deprecation warning (`Config.warnings()` is the natural home) is undecided and
  belongs with leaf `20260914-213153` — it owns config vocabulary and warnings, not this leaf.

RESOLVED THIS SESSION:

- ~~Whether the fail-open holes in Flag List section A should be closed by validation, engine fail-closed, or both~~ —
  RESOLVED: both. See A1/A2 above.
- ~~Whether bare `xargs` should be allowed at all~~ — DISSOLVED, not merely resolved: A3's fail-closed adjudication plus
  the new outcome model's deny-by-default-on-non-match together leave no policy choice to make. See D3 above.

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/conftest.py` — sys.path bootstrap onto `lib/` (direct `import config` style) and the
  `run_entrypoint` subprocess fixture for `bin/` CLI tests — verified runnable this session, reused as-is; this leaf
  ADDS the cwd-pinning fixture to it
- `packages/command-policy/tests/shell.nix` — already pins python313 + pytest + a real shfmt — no change needed
- `packages/shfmt-permissions/tests/test_analyze_bash_command.py:83-96` —
  `assert_decision(command, config, expected_decision, expected_reason=None)` — the public-entrypoint-only assertion
  shape to adopt, re-pointed at `Config.from_dict(cfg).decision_for(command)`
- `packages/shfmt-permissions/scripts/parsers/timeout.py:88-94` — the trailing-positional wrapper parser pattern —
  SPECIFICATION reference only for the xargs case; the artifact itself is leaf 20260914-213502's to write

**New helpers to create:**

- `lib/config.py` `Config.from_dict` / `Config.decision_for` stub — the RED seam every spec case calls; raises
  NotImplementedError until leaf 20260914-213652 wires the real pipeline
- cwd-pinning fixture in `tests/conftest.py` — MANDATORY — every path/redirect case must pin cwd or it risks the same
  false-confidence trap the old suite fell into
- branch-coverage manifest — success criteria require every one of ~30 matching-level branches to be reached; something
  must make an unreached branch visible
- wrapper-command config builder — the xargs/sh -c/env/timeout family and the external-script-parser case all need the
  same parser + `nestedCommand` filter config shape; building it once keeps those cases readable

**Fantasy callsites (test-facing API sketches):**

- `assert_decision('cat ./README.md > "/etc/passwd"', {allowedCommands:['cat'], sensitivePaths:['/etc/passwd']}, 'deny')`
- `with cwd_pinned_inside_project(): assert_decision('echo x >> ~/.ssh/authorized_keys', config, 'deny')`
- `assert_decision("find . -name '*.tmp' | xargs rm", wrapper_config('xargs', blocked=['rm']), 'deny')  # RED until leaf 20260914-213502 builds the xargs parser`
- `assert_decision('my-custom-tool --frobnicate x', script_parser_config('my-custom-tool', script='./my_parser.sh', blocked=['rm']), 'deny')  # pins the external-script CommandParser contract`

**Testability-driven production decisions:**

- Redirect-target extraction must be reachable as a named, independently assertable property (the fail-closed
  invariant), not only observable through a full `decision_for()` call
- Filter construction must fail loudly on an unknown type or action rather than returning None/True, so the fail-open
  holes in Flag List section A become assertable
- An entry declaring command-evaluation whose parser extracts nothing must fail closed in the engine, so the property is
  assertable without a config-level safety-belt filter
- `Config.decision_for` must accept a config dict shape stable enough that this leaf's stub signature does not need to
  change when leaf 20260914-213153 fills in real validation

## Assumptions

- **Claim:** Double-quoted redirect targets are extracted as the empty string, causing writes to sensitive absolute
  paths to be auto-approved — **confirmed** (Executed against the live engine during first-pass planning (probe imported
  `analyze-bash-command.py` directly; config {allowedCommands:['cat','echo'], pathValidationResponse:'deny',
  sensitivePaths:[]}; cwd and CLAUDE_PROJECT_DIR both at repo root). `cat ./README.md > "/etc/passwd"` -> ALLOW, while
  `> '/etc/passwd'` and bare `> /etc/passwd` -> DENY.)

- **Claim:** Tilde-prefixed redirect targets are never expanded, so writes to files under
  $HOME are auto-approved — **confirmed** (Same probe: `echo x >> ~/.ssh/authorized_keys` -> ALLOW, `cat < ~/.ssh/id_rsa` -> ALLOW, `echo x > "$HOME/.bashrc"`
  -> ALLOW. No tilde expansion before prefix checking, and production cwd sits inside an allowed prefix.)

- **Claim:** A propagated (recursed) command is checked against blockedCommands, so parser+propagate is a real answer to
  the xargs hole — **confirmed** (`_handle_propagate` calls `self.analyze(nested_command, _depth=depth+1)` — a FULL
  re-entry into `analyze()`. blockedCommands is hit at the normal check point. Tests confirm nested sensitive paths,
  substitution policy and path validation are likewise enforced.)

- **Claim:** An existing parser type can extract a wrapper's inner command when it comes from TRAILING POSITIONALS
  rather than an option value, so the xargs proposal is expressible without an engine change — **confirmed** (The
  pattern already ships twice (`timeout.py`, `nix.py`). CommandParser takes `named` verbatim from the script's JSON with
  no validation; ProvidedParser delegates to it. Only the xargs parser artifact is missing — now leaf 20260914-213502's
  job.)

- **Claim:** The trunk's figure of 'eleven short-circuit branches' is the size of the decision space the specification
  must cover — **refuted** (Code-research against HEAD found ~16 decision points inside `analyze()` plus ~14 more nested
  checks. The real target is ~30 branches — this figure is unaffected by the outcome model, since it counts MATCHING
  logic, not outcome vocabulary.)

- **Claim:** Some adjacent snapshot/golden-file/fixture-corpus mechanism already exists in this repository and should be
  extended rather than duplicated — **refuted** (Repo-wide research found zero snapshot plugins, zero golden-file
  patterns, no corpus-replay script anywhere in the repo.)

- **Claim:** `test_append_redirect_to_outside_path_passes_through` (in the OLD suite) genuinely pins the tilde-redirect
  behaviour it appears to pin — **refuted** (The test's green result is an artefact of pytest's cwd differing from
  CLAUDE_PROJECT_DIR in that test; in production the same command is ALLOWED. Historical — the fresh suite pins cwd
  explicitly to avoid reproducing this.)

- **Claim:** A blind naive reading of the config knob names yields the same semantics the engine actually implements —
  **refuted** (An agent given only knob names, defaults and valid-value lists flagged 17 names as ambiguous, misleading
  or under-determined. See the Flag List.)

- **Claim:** The existing test suite's assertions can be adopted wholesale as the specification's starting point —
  **refuted** (At least three existing tests assert behaviour now adjudicated as WRONG (the xargs hole, a misleading
  rejection message, deliberate propagation fail-open). Compounded by the outcome model: any old test asserting
  passthrough/ask for a non-approved command asserts an outcome the new engine will not produce.)

- **Claim:** The scaffolded command-policy test harness (`tests/conftest.py` + `tests/shell.nix`) is runnable and green
  before this leaf adds anything — **confirmed** (Executed this session:
  `cd packages/command-policy/tests && nix-shell --run pytest` -> '3 passed in 0.16s', exit code 0.)

- **Claim:** CommandParser (the external-script provider) is already the sole mechanism capable of exposing a
  script-provided named value, so preserving it as a rewrite constraint requires no NEW capability, only non-removal —
  **confirmed** (Restates Flag List F5 (already-verified during the first planning pass): DefaultParser and
  StructuredParser can never populate `named`; only CommandParser and the ProvidedParser that delegates to it can, with
  no schema validation on the script's JSON output. This session elevates that fact from an incidental observation to a
  binding constraint on leaf 20260914-213502, per the user's explicit ruling that the script-provider route is a public
  feature.)

## Design Decisions

### Source of the (command, config) matrix

- **Chosen:** Harvest-driven: use the existing 371 tests as the source of coverage territory
- **Rationale:** rationale not captured (chosen from options; subsequently refined by the user's specification reframe,
  under which the harvest supplies INSPIRATION and coverage targets rather than inherited assertions)
- **Rejected alternatives:** Hybrid harvest + combinatorial cross-product + hand-filled gaps; purely combinatorial
  generation over declared axes
- **Date:** 2026-09-14

### Characterization corpus vs authored specification (what the gate actually asserts)

- **Chosen:** Author a fresh, human-reviewed test suite that defines what the engine SHOULD do, using the existing tests
  as inspiration. Explicitly NOT a blind capture of current decisions.
- **Rationale:** User: 'Frankly - this is a rewrite. We don't need to inherit the exact same decisions. The perfect
  result will be that the config variables are self explanatory.' Vindicated during planning by execution: the current
  engine ALLOWS writes to "/etc/passwd", "$HOME/.bashrc" and `~/.ssh/authorized_keys` purely because of quoting style —
  a blind characterization corpus would have frozen those four allows as the specification.
- **Rejected alternatives:** Zero-diff-or-sanctioned-change-list gate; strict zero-diff with all behaviour changes
  deferred to follow-ups; corpus advisory only with the migrated test suite as sole authority
- **Date:** 2026-09-14

### Ownership of the flagged name-vs-behaviour mismatches

- **Chosen:** This leaf FLAGS and adjudicates. Naming changes are executed by leaf 20260914-213153. Behaviour changes
  become their own follow-up improvements.
- **Rationale:** rationale not captured (chose the recommended option). Keeps config renames from landing before the
  Config model that owns them exists, and gives each behaviour change its own review.
- **Rejected alternatives:** This leaf performs the whole audit AND applies both renames and behaviour fixes end-to-end;
  defer all fixes to the trunk's INTEGRATE step
- **Date:** 2026-09-14

### Lifetime of the specification suite after the rewrite lands

- **Chosen:** Permanent regression asset — stays in the suite indefinitely, re-baselined deliberately whenever behaviour
  is intentionally changed
- **Rationale:** rationale not captured (chose the recommended option)
- **Rejected alternatives:** Scaffold deleted once the migrated suite is green; keep the captured data permanently but
  retire the generation machinery
- **Date:** 2026-09-14

### Where the acceptance gate lives

- **Chosen:** Pytest test only — no separate CLI diff tool
- **Rationale:** rationale not captured (chose 'Pytest test only' over the recommended pytest+CLI option). Consistent
  with the specification reframe: an authored suite's failures are ordinary pytest assertion failures on named cases.
- **Rejected alternatives:** Pytest test plus a standalone CLI producing per-case diff reports; standalone CLI only
- **Date:** 2026-09-14

### sensitivePaths matching semantics

- **Chosen:** Keep substring matching (plain Python `in`), but specify and test it explicitly — including the
  false-positive direction
- **Rationale:** rationale not captured. Substring is intentional catch-everything breadth for a denylist; no current
  test distinguishes substring from exact.
- **Rejected alternatives:** Path-prefix matching with separator-awareness; exact match only
- **Date:** 2026-09-14

### Resolving the filterRejectionResponse naming/scope mismatch

- **Chosen:** SUPERSEDED 2026-09-15 — the knob DIES entirely under the new outcome model rather than being renamed. The
  CASE A/B distinction it used to toggle is abolished by the model itself (trunk Consequence 4): both cases now produce
  deny+hint uniformly, so no rename is needed because there is nothing left to configure.
- **Rationale:** User (this session): 'they are no longer needed. Replaced by a better system. Nothing to rename if they
  are gone.'
- **Rejected alternatives:** (original, now moot) Split into two knobs; keep the name and document the second case
- **Date:** 2026-09-15

### Whether blockedCommands circumvention via wrapper commands is an accepted limitation

- **Chosen:** NOT accepted. Argument-taking wrapper commands must be configured with a parser exposing the inner command
  as a named value plus propagation. The engine mechanism already does this correctly; the gap was config, guidance, and
  a missing xargs parser file — RE-SCOPED 2026-09-15: building that xargs parser is now leaf 20260914-213502's job (the
  rebuilt Parser family), not this leaf's; this leaf only specifies the expected DENY case.
- **Rationale:** User (first pass): 'xargs should only ever be allowed with a parser that fills a command named export
  and then propagate that command export and propagated commands should match against blockedCommands as per the stated
  policy resolve chain.' Verified: the trailing-positional wrapper pattern already ships twice, a propagated command
  fully re-enters the decision pipeline and hits blockedCommands.
- **Rejected alternatives:** Accept it as a genuine static-analysis boundary; special-case a hardcoded set of known
  wrappers inside the engine; escalate to renaming blockedCommands
- **Date:** 2026-09-14

### The paths filter resolving relative `exactly` entries against process CWD

- **Chosen:** Bug — resolve against CLAUDE_PROJECT_DIR instead, as a follow-up improvement
- **Rationale:** rationale not captured (chose the recommended option). Every other path mechanism in the engine anchors
  on CLAUDE_PROJECT_DIR.
- **Rejected alternatives:** Require absolute paths in `exactly` and warn/reject relative entries at config-validation
  time; declare CWD-relative intentional and pin it with a test that varies CWD
- **Date:** 2026-09-14

### Target name for the `propagate` config key

- **SUPERSEDED 2026-09-16** — the key is replaced entirely by a `{"type": "nestedCommand"}` FILTER; see Flag List B5.
  The reasoning below settled the best NAME for a mechanism that no longer exists as a config key, and is kept only so
  the vocabulary argument is not re-run.
- **Chosen (superseded):** `evaluateNamedValueAsCommand: "{named value key}"`
- **Rationale:** The user proposed a sentence shape correctly killing the 'propagate WHAT?' problem; the planner
  objected that a third vocabulary word would contradict the trunk's naming decision to share one convention
  (`named`/`namedValue`). The user accepted the substitution.
- **Rejected alternatives:** `evaluateNamedExportAsCommand` as originally proposed; that plus renaming
  `named`->`exports` everywhere, which changes the parser script contract for every bundled and user-written parser
- **Date:** 2026-09-14

### How to handle propagation's fail-open when no command is extracted

- **Chosen:** Make it fail CLOSED in the engine — an entry declaring it evaluates a named value as a command, which
  extracts nothing, does not match. Retires the hand-written safety-belt filter idiom.
- **Rationale:** rationale not captured (chose the recommended option). Today the only protection is a filter the config
  author must remember to add.
- **Rejected alternatives:** Keep fail-open but have `Config.warnings()` flag an entry lacking the belt filter; keep
  as-is and merely specify the fail-open behaviour
- **Date:** 2026-09-14

### Where the fresh specification suite lives relative to the existing test file

- **Chosen:** SUPERSEDED 2026-09-15 by the plugin move: A NEW file,
  `packages/command-policy/tests/test_permission_decisions.py`, in the NEW package.
  `packages/shfmt-permissions/tests/test_analyze_bash_command.py` stays byte-for-byte untouched by this leaf under the
  trunk's additive-only cutover; its migration/retirement moves to leaf 20260914-213825.
- **Rationale:** First pass: both suites should run during the rewrite so nothing is unguarded. Re-confirmed under the
  plugin move: the old package keeps guarding the still-live engine unmodified while the new suite defines the target
  for the not-yet-built command-policy engine.
- **Rejected alternatives:** Replace `test_analyze_bash_command.py` wholesale now; split the spec across several new
  files by concern
- **Date:** 2026-09-15

### Shape of the user's review of the specification cases

- **Chosen:** Themed batches, one config area at a time: the surviving decision-adjacent knob + uniform deny+hint
  default, then filters, then paths/redirects, then wrappers/propagation (including the external-script-parser case),
  then bypass/add-allow-policy escalation
- **Rationale:** rationale not captured (chose the recommended option, batch content updated this session for the new
  outcome model and package). With 200-400 cases, a batch is small enough to actually read.
- **Rejected alternatives:** One full pass over the complete list once authoring is done; review only the
  flagged/changed cases
- **Date:** 2026-09-14

### Split leaf (audit/flag-list half vs authored-suite half) into two, or keep combined

- **Chosen:** Keep combined — one leaf still produces both the audit+flag-list AND the authored pytest suite
- **Rationale:** User: 'We know the tests we want to turn green eventually. This is one big red face in TDD. Wiring up
  the tests after the implementation exists smells like going implementation first which I'd rather avoid.'
- **Rejected alternatives:** Split: finish the audit+flag-list now, defer the executable pytest suite to a new
  discovered leaf that runs once the pipeline leaf (20260914-213652) exists to import against
- **Date:** 2026-09-15

### How the specification suite handles the fact that no lib/ engine module exists yet to import

- **Chosen:** Define the future entrypoint now (`Config.from_dict(cfg).decision_for(command)`, stubbed
  NotImplementedError) and author the full suite against it immediately — deliberately RED until leaf 20260914-213652
  lands
- **Rationale:** Same as the split decision above — an outside-in acceptance-test pattern consistent with writing the
  tests you want to turn green before the implementation exists, not after.
- **Rejected alternatives:** Author the suite's `assert_decision(...)` calls now but leave the entrypoint import
  unresolved, so a later leaf must both build the pipeline and fix up the suite's import
- **Date:** 2026-09-15

### Shape of the settled public entrypoint

- **Chosen:** Config-first: `Config.from_dict(cfg).decision_for(command)`
- **Rationale:** rationale not captured (an echo-back was attempted; the user's reply addressed a different, related
  constraint — the external-script-parser requirement — instead of this specific question, so no rationale is recorded
  here beyond the option chosen)
- **Rejected alternatives:** Statement-first: `Statement.for_command(cmd).with_config(cfg).permission_decision()`
  (mirrors the trunk's own captured shape, but binds every spec case to leaf 20260914-213321's Statement surface); a
  bare free function `decision_for(command, config)` in `lib/permission_decisions.py` (narrowest seam, least
  domain-expressive)
- **Date:** 2026-09-15

### Where the xargs wrapper parser artifact gets built

- **Chosen:** Hand it to leaf 20260914-213502 (the Filter/Parser family rebuild) — this leaf only specifies the expected
  DENY case; the case stays RED until that leaf lands, same as the rest of the suite
- **Rationale:** rationale not captured
- **Rejected alternatives:** Keep building it in this leaf, written against the new package — rejected because the
  Parser family structure it would plug into does not exist yet, which is exactly the kind of guessing the scaffold leaf
  existed to prevent
- **Date:** 2026-09-15

### External-script parser (CommandParser) extensibility through the Parser-family rewrite

- **Chosen:** MUST survive as a first-class, unremoved capability of the rebuilt Parser family (leaf 20260914-213502) —
  a public extensibility feature, not an implementation detail
- **Rationale:** User: 'I'm fine with the provided parsers being rewritten as VOs but the "run a script as provider"
  must stay open - that's a feature. A user is supposed to be able to write their own parsers for commands not provided
  by the plugin itself.'
- **Rejected alternatives:** Collapsing the Parser family into fully-bundled parsers only, dropping the external-script
  route as an implementation detail that happened to exist under the old '-er' design
- **Date:** 2026-09-15

### Closing the A1/A2 fail-open holes (invalid filter `action`, unknown filter `type`)

- **Chosen:** Both layers — `Config.fromText` rejects an unrecognized filter `type` or `action` at load time (leaf
  20260914-213153), AND the engine treats a filter it cannot construct as fail-closed at match time (leaf
  20260914-213652), as defense in depth
- **Rationale:** rationale not captured (chose the recommended option). Matches A3's already-settled precedent
  (propagation-extracts-nothing was made fail-closed in the engine, not merely validated away), and load-time validation
  gives a config author an early, clear error rather than relying on a single line of defense to catch every case.
- **Rejected alternatives:** Validation only (Config.fromText rejects the bad config, engine trusts anything that passed
  validation); engine fail-closed only (no load-time validation added, config authors get no early warning)
- **Date:** 2026-09-15

## Success Criteria

- [ ] The public entrypoint `Config.from_dict(cfg).decision_for(command)` is defined in
      `packages/command-policy/lib/config.py`; the fresh suite imports and calls only that entrypoint — no test
      instantiates a parser or filter class, reads a raw AST dict, or calls a private method
- [ ] `packages/command-policy/tests/test_permission_decisions.py` exists and is COLLECTIBLE by pytest (imports
      cleanly); running it fails with NotImplementedError from `decision_for` — never a collection/import error
- [ ] Every one of the ~30 MATCHING-level decision branches (the matching logic, not the collapsed outcome vocabulary)
      is reached by at least one case in the fresh suite
- [ ] The only surviving decision-adjacent knob, commandSubstitutionResponse, is exercised at both its remaining values
- [ ] Every case that used to assert passthrough or ask for a non-approved command has been re-derived to assert
      deny+hint instead — none of the old passthrough/ask assertions survive unexamined
- [ ] All six confirmed redirect-bypass commands assert DENY: `cat ./README.md > "/etc/passwd"`,
      `echo x > "$HOME/.bashrc"`, `echo x >> ~/.ssh/authorized_keys`, `cat < ~/.ssh/id_rsa`, plus the single-quoted and
      bare equivalents that already deny
- [ ] Every path- or redirect-related case pins cwd explicitly via the (newly added) cwd-pinning fixture rather than
      inheriting pytest's working directory
- [ ] The fail-closed invariant is asserted as a named property: an empty or unresolvable redirect target is denied,
      never resolved to cwd
- [ ] Every fail-open hole in Flag List section A has an explicit case asserting the intended (closed) behaviour:
      invalid filter action, unknown filter type, propagation-extracts-nothing, and the quoted-heredoc substitution
      bypass
- [ ] At least one case pins the external-script CommandParser contract explicitly (a user-provided parser script
      publishing a sub-command, consumed via the entry's `nestedCommand` filter, hitting blockedCommands) as a
      first-class case distinct from any bundled parser
- [ ] `find . -name '*.tmp' | xargs rm` with blockedCommands:['rm'] and xargs configured with a parser + a
      `nestedCommand` filter asserts DENY — the case is authored and reviewed here; the xargs parser implementation
      itself is leaf 20260914-213502's job, so this case stays RED alongside the rest of the suite until that leaf lands
- [ ] sensitivePaths substring semantics are pinned in BOTH directions, including the over-matching false-positive case
- [ ] Every remaining coverage gap in the reworked Flag List section E has at least one case (program-in-both-lists
      precedence, multi-sensitive-variable reason-ordering, out-of-bounds `action:block` rejection-by-absence,
      additionalAllowedPrefixes near-miss guard)
- [ ] The reworked adjudicated flag list is complete: every mismatch is resolved as 'rename' (trimmed hand-back to leaf
      20260914-213153), 'behaviour fix' (raised as a follow-up improvement), or 'dissolved by the outcome model' (no
      action needed), with none left undecided
- [ ] The user has reviewed and approved every themed batch of cases before the suite is considered the acceptance gate
- [ ] `packages/shfmt-permissions` and its test suite remain byte-for-byte untouched by this leaf (git diff scoped to
      that directory is empty)
- [ ] `cd packages/command-policy/tests && nix-shell --run "pytest -v"` runs and COLLECTS successfully across all test
      files, including the new RED specification file (failures are NotImplementedError, never collection errors)

## Implementation TODO

- [x] Update status to in-progress
- [x] Write stub for `packages/command-policy/lib/config.py` with `Config.from_dict` and `Config.decision_for` raising
      NotImplementedError
- [x] Test that stub imports cleanly and raises NotImplementedError when called
- [x] Add cwd-pinning fixture to `packages/command-policy/tests/conftest.py`
- [x] Test that cwd-pinning fixture works correctly
- [x] Refactor conftest if needed (none needed at this size)
- [x] Write test batch 1: surviving decision-adjacent knob + uniform deny+hint default cases in
      `test_permission_decisions.py`
- [x] Verify batch 1 collects cleanly and fails at NotImplementedError
- [x] User reviews and approves batch 1 — reviewed 2026-09-16; user added the `required`-filter gap and the
      unknowable-expansion rule (Flag List G), both incorporated before proceeding
- [x] Write test batch 2: filter matching and rejection cases
- [x] Verify batch 2 collects cleanly and fails at NotImplementedError
- [x] User reviews and approves batch 2 — reviewed 2026-09-16; user accepted all four adjudications and raised the
      parser-capability interface that became A6b
- [x] Write test batch 3: paths and redirects including all six redirect-bypass commands
- [x] Verify batch 3 collects cleanly and fails at NotImplementedError
- [x] User reviews and approves batch 3 — reviewed 2026-09-16; user settled the `hasNoPathParameters` rename and
      supplied the five explicit path-normalisation cases (D7)
- [x] Write test batch 4: wrappers and propagation including external-script CommandParser contract and xargs DENY case
- [x] Verify batch 4 collects cleanly and fails at NotImplementedError
- [x] User reviews and approves batch 4 — reviewed 2026-09-16, then RE-AUTHORED the same day for the `nestedCommand`
      filter reshape (B5 supersede) with the user's explicit approval
- [x] Write test batch 5: bypass and add-allow-policy escalation cases
- [x] Verify batch 5 collects cleanly and fails at NotImplementedError
- [x] User reviews and approves batch 5 — reviewed 2026-09-16; nothing needed deciding, and the one question this leaf
      raised there was withdrawn as malformed (see WHAT DENY MEANS)
- [x] Write branch-coverage manifest helper
- [x] Test that branch-coverage manifest correctly tracks reached branches
- [x] Write wrapper-command config builder helper
- [x] Test that wrapper-command config builder produces valid configs
- [x] Verify all ~30 MATCHING-level decision branches are covered by at least one case — 45 branches manifested, all
      covered
- [x] Verify sensitivePaths substring semantics are tested in both directions
- [x] Verify all Flag List section A fail-open holes have explicit cases — A1/A2 at both layers, A3, A4, A5, A6
- [x] Verify all Flag List section E coverage gaps have cases — E1, E4, E5, E6, E7, E8
- [x] Verify fail-closed invariant has explicit named-property test
- [x] Run full test suite: `cd packages/command-policy/tests && nix-shell --run "pytest -v"`
- [x] Verify suite collects successfully and all failures are NotImplementedError (never collection errors)
- [x] Verify `packages/shfmt-permissions` remains byte-for-byte untouched
- [x] Update status to completed

## Interface

**What this leaf produced:** An AUTHORED decision specification for the command-policy engine
(`packages/command-policy/tests/test_permission_decisions.py`), RED by design, plus the settled public entrypoint stub
(`packages/command-policy/lib/config.py`: `Config.from_dict` / `Config.decision_for` raising NotImplementedError), plus
a cwd-pinning fixture added to the existing `tests/conftest.py`. Also produced: a reworked adjudicated flag list (moot
renames for dying knobs dropped, coverage gaps re-derived against deny+hint) and a hard constraint on leaf
20260914-213502 to keep the external-script CommandParser route open.

**Contract for downstream leaves / integrate:** `test_permission_decisions.py` calls ONLY
`Config.from_dict(cfg).decision_for(command)` and asserts on outcome plus, where it matters, reason content. It touches
no internal class, no raw AST dict, no private method. Leaf 20260914-213153 (Config) MUST extend `lib/config.py`'s
`Config.from_dict` with real parsing/validation WITHOUT changing the `decision_for(command)` signature. Leaf
20260914-213652 (pipeline) MUST implement `decision_for`'s real body and make the suite pass — that is this suite's job
as the trunk's acceptance gate. Leaf 20260914-213502 (Filter/Parser) MUST build the xargs wrapper parser (this leaf only
specifies its expected DENY case) and MUST preserve the external-script CommandParser route as a first-class capability,
not collapse it into bundled-only parsers. The gate is NOT 'zero diffs against the old engine' — it deliberately asserts
decisions the old engine does not make.

**AS-BUILT, 2026-09-16 (final).** `packages/command-policy/tests/test_permission_decisions.py` holds 76 test functions,
plus a 52-branch coverage manifest. Suite-wide that is 89 items (two cases are parametrised, six ways over the
redirect-bypass commands and five over path normalisation): 80 fail with `NotImplementedError`, 9 pass (the stub probe,
the two config-builder guards, the two manifest guards, and the four pre-existing scaffold tests). Zero collection
errors. All five batches were reviewed with the user case-by-case.

**BATCH 4 WAS RE-AUTHORED after first being written and reviewed.** Leaf 20260914-213652's planning session settled with
the user that nested wrapper sub-command evaluation is an ordinary filter, `{"type": "nestedCommand"}`, superseding this
leaf's own B5 rename and invalidating batch 4's config shape. The peer session flagged it rather than letting this leaf
build further on the old shape, and asked for confirmation rather than asserting authority; the user approved the
re-authoring here. The `nestedCommand` CONFIG SPELLING was settled by THIS leaf — 20260914-213652 recorded the filter's
behaviour but never its config surface, and the suite is the acceptance gate. Leaf 20260914-213652 has been told the
exact shape. The parser sub-command channel's key name is deliberately NOT settled here; no case touches raw parser
JSON, so it remains that leaf's to name. `packages/shfmt-permissions/` is byte-for-byte untouched.

Three additions to the plan, each forced by something found while authoring rather than anticipated:

1. **`ConfigError` was added to `lib/config.py`** alongside the stub. A1/A2/A6/E6 all adjudicate to load-time rejection,
   which is unassertable without an observable failure mode. The suite pins THAT an unusable config is rejected; leaf
   20260914-213153 owns which configs qualify and what each message says. Validation cases route through `decision_for`
   rather than calling `from_dict` directly, so they too fail with `NotImplementedError` today and the suite has ONE
   expected failure mode rather than two.
2. **Flag List section G** (unknowable expansion) — a behaviour requirement neither the plan nor the old engine's design
   anticipated, raised by the user during batch 1 review. Handed to leaves 20260914-213502 and 20260914-213652.
3. **Flag List A6** (`optionValue` silently inert without a value-consuming parser) — a fail-open found by verifying a
   case rather than by the planned audit.

**Corrections made to this file during implementation, recorded rather than silently edited:** section G's first draft
claimed the old engine runs filters against literal arguments and treats substituted text as absent. Measured at
`analyze-bash-command.py:2060-2064`, it already skips such an entry. Section G's real contribution is precision — it
RELAXES that blanket skip in the two provable cases — plus the outcome the skip lands on.

**Outcomes re-derived rather than inherited** (each was `passthrough` or `ask` under the old model and is now `deny`):
an empty `allowedCommands`; exceeding the propagation depth limit; a filtered entry meeting a substitution; CASE A and
CASE B collapsing together.

**New dependency edges discovered:** None that change the Leaf Stream order. Leaf 20260914-213153 gains a consumer
relationship on this leaf's (trimmed) rename list, already satisfied by stream order. Leaf 20260914-213502 gains a new
consumer relationship on this leaf's external-script-parser constraint and xargs-case hand-back, also already satisfied
by stream order (leaf 5 runs after leaf 2).

**Follow-ups for integrate:** 1. This leaf remains substantially larger than the other eight leaves in the stream —
unchanged assessment from the first planning pass. 2. The trunk's Shared Context 'eleven short-circuit branches' figure
still undercounts by roughly half (~30 is the real figure) — unaffected by the outcome model, since it counts matching
logic not outcome vocabulary. 3. The RED-suite pattern this leaf establishes (settle the entrypoint before the
implementation exists, author tests against it, stay red until assembly) is now a load-bearing convention for leaves
20260914-213153 through 20260914-213652 — INTEGRATE should confirm the suite actually turned green by the time leaf
20260914-213652 finished, and record the real turnaround if it did not.

## Post-Completion Corrections

Defects found in the delivered suite AFTER this improvement was marked completed, fixed in place rather than deferred,
since a self-contradictory acceptance gate forces every downstream implementer to guess. Recorded here rather than by
reopening the status, because both are defects in what was delivered, not new scope.

**2026-09-16, found by leaf 20260914-213652's planning session on review of commit 7fcea65:**

1. **B7 violated by this leaf's own suite.** One batch-2 case (`test_option_value_filter_rejects_a_disallowed_value`)
   still spelled the parser key `options_with_arguments` while B7 adjudicates the vocabulary as camelCase
   `optionsWithArguments`, which every batch-4/5 case uses. The case was authored BEFORE B7 was discovered and was not
   swept afterwards. Fixed. The lesson is narrow and worth keeping: a rename adjudicated mid-suite has to be applied
   BACKWARDS over already-written cases in the same pass, or the gate ships asserting a key its own Flag List says will
   not exist.

2. **Four cases gave `commandParser` no `type`** (the A6b set). Worse than cosmetic: A2 adjudicates an unrecognised
   parser type to load-time rejection, and a MISSING type is the same class — a config that silently becomes a
   `DefaultParser` is precisely A2's "typo'd parser type silently disables propagation". So two of the four asserted
   `allow` for configs that, under this leaf's own adjudication, should not load at all. Fixed by stating
   `"type": "structured"` explicitly in each, plus a note in the suite recording that there is NO implicit default and
   why. The peer flagged it as "reads as an omission rather than a decision", which was exactly right.

**Channel key settled elsewhere, recorded here for completeness:** the parser's dedicated sub-command channel is
`nestedCommands` (top-level in parser JSON, sibling of `named`), settled with the user by leaf 20260914-213652 after
this leaf settled the `{"type": "nestedCommand"}` filter spelling. Filter and channel deliberately share one word rather
than introducing "sub" as a second word for the concept. No case in this suite names the channel — they assert at
`decision_for` level and never touch raw parser JSON — so nothing here changes.

## Related Past Improvements

(None identified during this planning session)
