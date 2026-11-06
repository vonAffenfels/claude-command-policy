# Improvement 20260918-205740: Fix Double-Quoted-Argument Blindness

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-18
- Updated: 2026-09-18
- Plan started: 2026-09-18T20:57:18+02:00
- Plan finished: 2026-09-18T21:37:35+02:00
- Impl started: 2026-09-18T21:44:49+02:00
- Impl finished: 2026-09-18T21:55:10+02:00
- Depends on: 20260915-010959

## Context / Why This Exists

**Origin / trigger:** Found by an independent review of leaf 20260915-010959 (deny-reason-escalation-paths) during its
own reopening; deliberately deferred to its own improvement rather than folded into that leaf, and made to depend on it.

**Consumer(s) of the output:** No live consumer yet — command-policy is not wired into any real Claude Code session
(packages/shfmt-permissions remains the live engine, byte-for-byte untouched and out of scope). The immediate consumer
is the decision-specification test suite (tests/test_permission_decisions.py), which is the trunk's behavior-pinning
mechanism; the eventual consumer is whichever future cutover leaf wires command-policy into a live hook. This is why
these are latent defects, not currently-exploitable ones — but the task explicitly said not to treat that as a reason to
go slowly.

**Adjacent systems already covering part of the need:** packages/shfmt-permissions is the live engine and is explicitly
out of scope and unaffected; this improvement touches only packages/command-policy's lib/ and tests/, plus the
command-policy-decision-model.md knowledgebase article.

## This Improvement's Objective

Fix the double-quoted-argument blindness in packages/command-policy that produces false ALLOWs and false DENIALs in the
permission engine. Root cause: Argument.text (lib/statement.py) does a naive one-level concatenation of a word's shfmt
Parts; a double-quoted word is a single top-level DblQuoted part carrying no Value of its own (its literal content sits
one level deeper, in that part's own nested Parts), so Argument.text reads a double-quoted argument as the empty string
while unquoted and single-quoted forms read correctly. Redirect.target_text has the identical naive-concatenation gap.
Found by an independent review of leaf 20260915-010959 and deliberately deferred to its own improvement; depends on
improvement-20260915-010959-deny-reason-escalation-paths, which already added a separate Argument.literal_text accessor
and routed only add-allow-policy's own classification site through it. This improvement fixes the call sites that leaf
left behind, and — per a live design decision made during this planning session — merges the fix directly into
Argument.text/Redirect.target_text rather than keeping literal_text as a separate accessor, since every production
reader of .text needs correct literal content, not double-quote-blindness specifically. Also closes a related
add-allow-policy gap: the grammar rejects a command substitution in the entry as shell_touched but not a parameter
expansion, so a double-quoted entry containing $HOME displays a narrower string than lib/add_allow_write.py will
actually persist (it parses real post-expansion argv).

## Proposed Approach

Merge the DblQuoted-unwrapping recursive logic (currently living as the separate Argument.literal_text / module-level
\_literal_text_of_parts helper, added by leaf 20260915-010959) directly into Argument.text's own computation in
Argument.from_word, and apply the identical fix to Redirect.target_text (which has the same one-level-concatenation bug
but no literal_text-equivalent today). Delete Argument.literal_text, its literal_text constructor parameter, and
\_literal_text_of_parts entirely once merged — extract a single shared recursive helper (e.g. rename
\_literal_text_of_parts to something like \_recursive_text_of_parts) used by BOTH Argument.from_word and wherever
Redirect builds target_text (statement.py, near line 74). The corrected accessor still contributes "" for a
ParamExp/CmdSubst/ProcSubst (matching today's Argument.contains_substitution / referenced_variables split — those remain
the way callers detect that unknowable content is present), so the unknowability rules in the KB (the 'Absence is never
provable' / 'Presence IS provable' family) are fully preserved; only the double-quote-blindness (a solvable,
non-unknowable case) is fixed.

CRITICAL CONSEQUENCE OF THIS DESIGN, verified during planning: Argument.text has exactly THREE production readers today
(confirmed by grep across packages/command-policy/lib/\*.py): escalation_policy.py:112 (bypass-policy's wrapped_text),
allowed_command_policy.py:147 (argument_texts, which feeds every filter matcher in matcher.py AND the default parser's
path detection), and allowed_command_policy.py:374/377 (\_substitution_indices's dash-prefix option/positional
classification, used only to compute where a real substitution's word-splitting shift lands relative to an index-based
filter). Because all three already read .text, merging the fix into .text fixes ALL THREE AUTOMATICALLY — NO call-site
changes are needed at any of them. This also resolves a consistency risk found during planning: \_substitution_indices
reads argument.text directly (not through argument_texts), so if only argument_texts had been re-routed to a separate
literal_text-style accessor, \_substitution_indices's own dash-classification would have kept misreading a double-quoted
flag argument (e.g. "--json") as a positional instead of an option, disagreeing with the parser's own (now-corrected)
classification whenever a command mixed a quoted literal with a real substitution. Merging into .text makes this class
of site-vs-site inconsistency structurally impossible, since there is only one accessor left to read.

The ONLY call-site change needed anywhere is escalation_policy.py's \_classify_add_allow_invocation (lines ~212, 217,
224), which currently reads the now-deleted .literal_text and must switch to .text (trivial rename, same semantics
post-merge). Separately (independent change, same function): extend the add-allow-policy grammar's shell_touched
detection so it also fires when the entry (command) argument's existing Argument.referenced_variables field is non-empty
— this catches $HOME / "$HOME" / ${HOME} uniformly without requiring single-quote syntax or special-casing ParamExp's
AST node type directly, and reuses a field Argument already computes.

Every behavior change must be characterized as a new or updated case in tests/test_permission_decisions.py (red before
green) per this project's TDD discipline and that suite's established role as the trunk's shared decision-pinning
mechanism — see Design Decisions and the TODO list for exactly which cases.

## Affected Components

**Files:**

- `packages/command-policy/lib/statement.py:222-297` (Argument class, from_word, \_literal_text_of_parts) - merge fix
  into Argument.text, delete literal_text
- `packages/command-policy/lib/statement.py:58-91` (Redirect class) - apply identical merged fix to target_text
- `packages/command-policy/lib/escalation_policy.py:196-243` (\_classify_add_allow_invocation) - .literal_text to .text
  rename; add referenced_variables shell_touched check
- `packages/command-policy/tests/test_statement.py:606-730` (TestCommandArguments class) - rewrite/rename pinned .text
  tests, delete now-redundant literal_text tests
- `packages/command-policy/tests/test_permission_decisions.py` - add new decision-spec cases (Batch 2 filters, Batch 3
  paths/redirects, Batch 5 bypass/add-allow-policy) plus FLAG_LIST coverage entries
- `packages/command-policy/tests/test_escalation_policy.py:119-156` - update docstrings/comments referencing
  literal_text as a separate accessor
- `docs/knowledgebase/command-policy-decision-model.md` - correct 'What the Engine May Not Conclude From Text It Cannot
  See' intro framing, the 'Statement: What Every Policy Actually Reads' .text/.literal_text bullet, and the
  add-allow-policy grammar section (shell_touched now also covers referenced_variables)

**Classes/Functions:**

- Argument
- Redirect

**Modules:**

- `packages/command-policy/lib/statement.py`
- `packages/command-policy/lib/escalation_policy.py`
- `packages/command-policy/lib/allowed_command_policy.py` (unchanged, but its correctness depends on this fix)

## Implementation Notes

CONCRETE EXAMPLES (verified directly against the code during planning, not theoretical):

1. bypass-policy 'rm -rf /' (single-quoted): Argument.text reads 'rm -rf /' correctly (a SglQuoted word carries Value
   directly) -> escalation_policy.py:112's wrapped_text is truthy -> re-enters the ordinary pipeline on 'rm -rf /' -> rm
   isn't allow-listed -> ordinary near-miss reason, not in \_FORCES_ASK_REASON_TYPES -> PASSTHROUGH (correct: human
   decides). bypass-policy "rm -rf /" (double-quoted, TODAY, before fix): the word's Parts = [one DblQuoted part with no
   Value of its own]. Argument.text = "".join(part.get('Value','') for part in parts) = "" (the naive one-level read
   never looks inside the DblQuoted's own nested Parts). wrapped_text = "" -> falsy -> `PermissionDecision.allow()`
   branch taken directly (line 113's `if wrapped_text else PermissionDecision.allow()`) -> AUTO-ALLOWED, no human
   involved. This is the worst finding. AFTER FIX: Argument.text recurses into the DblQuoted's own nested Parts (finding
   the Lit part 'rm -rf /') -> text = 'rm -rf /' -> identical treatment to the single-quoted form -> PASSTHROUGH.

2. allowedCommands filter
   {"type":"argumentAtIndex","index":0,"pattern":"^--danger$","action":"block"} on program rg: `rg --danger` and `rg '--danger'` both read '--danger' at argument_texts[0] -> ArgumentAtIndexMatcher matches -> block action inverts -> filter fails -> entry doesn't vouch -> DENY (correct). `rg "--danger"` (TODAY, before fix): argument_texts[0] = "" (same naive-concatenation bug) -> regex '^--danger$'
   doesn't match "" -> NOT_MATCHED -> block action finds nothing to block -> filter PASSES -> entry vouches -> ALLOW.
   One double-quote defeats the block rule. AFTER FIX: argument_texts[0] = '--danger' (recovered) -> DENY, matching the
   other two forms. The SAME argument_texts list (allowed_command_policy.py:147) also feeds allowedPaths detection
   (finding 3) and every other matcher type in matcher.py (finding 4's namedValue/positionalArgAtIndex false-denials) —
   fixing Argument.text fixes all of these simultaneously since they all read parsed.\* which is built from this one
   list.

3. \_substitution_indices consistency example (the scope-adjacent gap found during planning, not in the original
   report): config
   {"program":"rg","filters":[{"type":"positionalArgAtIndex","index":0,"pattern":"^expected$","action":"required"}]},
   command `rg "--json" expected $(cat x)`. BEFORE FIX: argument_texts = ["", "expected", ""] (the quoted --json reads
   empty) -> DefaultParser classifies the empty string as a POSITIONAL (doesn't start with '-') at index 0, 'expected'
   at index 1, substitution's empty text at index 2 -> positional_values()[0] = "" -> doesn't match '^expected$' ->
   required filter fails -> WRONGLY DENIED (a false negative on a legitimate command — finding 4's class of bug).
   Separately, \_substitution_indices (lines 374-382) ALSO misclassifies the quoted --json as a positional for its own
   index-shift bookkeeping. AFTER FIX (merged into .text): argument_texts = ["--json", "expected", ""] -> DefaultParser
   classifies '--json' as an OPTION (starts with '-'), 'expected' as positional index 0, substitution as positional
   index 1 -> positional_values()[0] = 'expected' -> MATCHES -> required filter satisfied -> entry vouches -> ALLOW
   (correct). \_substitution_indices, reading the SAME now-corrected .text, agrees automatically — no separate change
   needed there, and no risk of the two computations disagreeing.

4. Redirect.target_text (finding 5, milder): `echo x > "/etc/passwd"` already DENIES today
   (test_permission_decisions.py's REDIRECTS_THAT_MUST_DENY, line ~776), but via the WRONG mechanism: target_text reads
   "" (same naive-concatenation bug), which test_an_unresolvable_redirect_target_is_denied_never_resolved_to_cwd's own
   property ('an empty or unresolvable extracted target must be treated as unresolvable and DENIED') catches
   coincidentally. This is a reason-fidelity defect, not a security hole: the human is told the redirect target is
   empty/unresolvable, not that it points at /etc/passwd. AFTER FIX: target_text correctly reads '/etc/passwd' -> denied
   via the real path-outside-allowed-prefixes mechanism, with the real path named in the Reason. Verify this
   REDIRECTS_THAT_MUST_DENY batch still passes (same deny outcome, different Reason type/content) after the fix — do not
   let the outcome silently flip. For 'echo x > "$HOME/.bashrc"': the word's Parts are [Lit("/.bashrc") wrapped with a
   preceding ParamExp for HOME] inside one DblQuoted. The corrected recursive read contributes the literal Lit content
   ('/.bashrc') but still contributes "" for the ParamExp itself (matching Argument.text's own preserved
   substitution-blindness) -> target_text = '/.bashrc' (a partial, still-conservative read — an absolute-looking path,
   still outside any allowed prefix) -> still DENIES, now for a more informative reason. This is consistent with the
   existing 'Absence is never provable' / partial-knowledge family of rules already documented in the KB; nothing new to
   invent.

5. add-allow-policy ParamExp gap: `add-allow-policy --scope user --intent "x" "cat $HOME/file"` today:
   as_sole_invoked_program() only returns None (shell_touched) when statement.sub_statements() is non-empty, which
   covers CmdSubst/ProcSubst (they ARE Statement subtypes reachable via sub_statements()) but NOT a bare ParamExp (not a
   Statement subtype at all — it's a word-level expansion with no nested command). So this line passes the shell_touched
   gate today and gets classified normally, showing the human a narrower entry string than lib/add_allow_write.py will
   actually persist (it parses real post-expansion argv). FIX: in \_classify_add_allow_invocation, after identifying the
   entry/command-argument token (not --scope or --intent), also check that argument's existing .referenced_variables
   field; if non-empty, return ('shell_touched', None) — the same violation code already used for the CmdSubst case,
   reusing the existing \_ADD_ALLOW_POLICY_VIOLATION_EXPLANATIONS rendering. Track the Argument object for the entry
   (not just its .text) through the token-scanning loop so this check is possible after the loop.

STATEMENT.PY MECHANICS FOR THE MERGE ITSELF: Argument.from_word currently does
`text = "".join(part.get("Value", "") for part in parts)` then separately computes
`literal_text = _literal_text_of_parts(parts)`. Merge means: `text` should be computed via the same recursive logic
literal_text uses today (unwrap a part with no 'Value' of its own via its own nested 'Parts', recursively; contribute ""
for a part with neither 'Value' nor 'Parts' — i.e. ParamExp/CmdSubst/ProcSubst). Delete the separate literal_text local
variable/parameter/property and the `literal_text=None` constructor kwarg; update **repr** (currently shows both text=
and literal_text=, should show only text= after merge). Apply the identical recursive function where Redirect computes
target_text (statement.py ~line 74, currently the same one-level `"".join(part.get("Value", "") for part in parts)`
pattern) — extract ONE shared helper (rename \_literal_text_of_parts to something accessor-neutral like
\_recursive_text_of_parts) used by both Argument.from_word and Redirect's construction path, replacing both naive
concatenations.

TEST FILE UPDATES NEEDED (packages/command-policy/tests/test_statement.py, TestCommandArguments class, current line
numbers as of planning time — will drift once other edits land, locate by test name not line number):

- test_a_braced_variable_reference_next_to_literal_text (~line 654): currently asserts `argument.text == ""` for
  `echo "${HOME}/.bashrc"`. Rewrite (and rename — the name references literal_text, which is being deleted) to assert
  the corrected value: `argument.text == "/.bashrc"` (the Lit suffix recovered, the ParamExp still contributing
  nothing). Keep the `referenced_variables == frozenset({"HOME"})` assertion — unaffected by this change.
- test_literal_text_unwraps_a_double_quoted_word_that_text_leaves_empty (~line 675): asserts `argument.text == ""` and
  `argument.literal_text == "plain value"` for `echo "plain value"`. After merge, `literal_text` no longer exists;
  rewrite to assert `argument.text == "plain value"` directly (fold into a renamed test, e.g.
  test_a_double_quoted_word_with_no_substitution_reads_its_real_content).
- test_literal_text_matches_text_for_an_unquoted_or_single_quoted_word (~line 688): becomes vacuous once there's only
  one accessor — either delete or repurpose to assert unquoted/single-quoted words are unaffected by the merge (still
  read correctly).
- test_literal_text_contributes_nothing_for_a_variable_or_substitution (~line 718): asserts
  `argument.literal_text == "/.bashrc"` for the same $HOME case above — this becomes a duplicate of the renamed first
  test once merged; consolidate rather than keeping both.
- test_a_command_substitution_argument_contains_no_literal_text (~line 631): rename (references 'literal_text' in its
  name/wording) to describe .text's own substitution-blindness directly (e.g.
  test_a_command_substitution_argument_has_empty_text), assert `argument.text == ""` for `echo $(echo safe)`.
- Add a new Redirect-focused test mirroring the Argument ones: a double-quoted redirect target with real literal content
  recovers it, e.g. `echo x > "/etc/passwd"` -> `target_text == "/etc/passwd"`, and a mixed case like
  `echo x > "$HOME/.bashrc"` -> `target_text == "/.bashrc"` (ParamExp contributes nothing, trailing Lit recovered) —
  mirrors the Argument test for the same construct.

DECISION-SPEC SUITE ADDITIONS (packages/command-policy/tests/test_permission_decisions.py) — add to the existing
batches, and add a FLAG_LIST entry naming each new test (see the dict literal near the end of the file, e.g. under
'redirect_target_outside_prefixes' etc. for the pattern to follow):

- Batch 2 (filters, ~line 439+): a double-quoted argument must be denied by a block filter exactly like its
  unquoted/single-quoted equivalents (finding 2) — parametrize alongside any similar existing case if one exists, or add
  fresh, following the REDIRECTS_THAT_MUST_DENY parametrize pattern used in Batch 3 (a list of quoting variants of the
  same semantic command, all asserted to produce the same decision).
- Batch 2 or 3: an allowedPaths double-quote evasion case (finding 3) — a double-quoted path argument outside an
  allowedPaths prefix must deny like its unquoted equivalent.
- Batch 2: the \_substitution_indices consistency case from example 3 above (finding 4's false-denial class) — a
  double-quoted flag argument ahead of a real substitution, with a positionalArgAtIndex/required filter, must ALLOW (not
  wrongly deny).
- Batch 3 (paths and redirects, ~line 762+): strengthen or add to REDIRECTS_THAT_MUST_DENY's reason-fidelity — assert
  (via assert_reason_includes / assert_primary_reason, both already defined in this file as structural Reason-object
  comparisons, not substring matching) that the double-quoted redirect cases now produce a reason naming the REAL
  resolved path, not an 'unresolvable target' reason. Do not let this batch's existing DENY outcomes silently flip —
  read test_an_unresolvable_redirect_target_is_denied_never_resolved_to_cwd's own case ('cat ./README.md > ""' — a truly
  empty double-quoted target) and confirm it is UNAFFECTED (still legitimately unresolvable, no literal content to
  recover).
- Batch 5 (bypass and add-allow-policy escalation, ~line 1565+): a bypass-policy double-quoted dangerous-inner-command
  case (finding 1, the worst one) — `bypass-policy "rm -rf /"` must produce the SAME decision as
  `bypass-policy 'rm -rf /'` (passthrough, since rm is merely not allow-listed — not
  blocked/sensitive-path/redirect-outside, so it does not hit the forces-ask set).
- Batch 5: an add-allow-policy ParamExp-in-entry case — `add-allow-policy --scope user --intent "x" "cat $HOME/file"`
  must deny via AddAllowPolicyGrammarViolation('shell_touched'), mirroring the existing CmdSubst-in-entry case's outcome
  (find that existing case for the exact pattern to follow — search this file for an existing shell_touched
  CmdSubst-in-entry test).

test_escalation_policy.py (~lines 119-156): this file's own docstrings/comments currently describe literal_text as the
fix for the add-allow-policy display bug (e.g. 'real content via Argument.literal_text ... literal_text fixes this at
the classification call site'). Rewrite these to describe .text itself being fixed at the source, not a separate
accessor routed to at one call site.

RUN THE FULL SUITE after implementing: `cd packages/command-policy/tests && nix-shell --run pytest`. Confirm green
except the four PRE-EXISTING xargs-parser-dependent failures already tracked in the KB's Gotchas section (not this
improvement's to fix) — do not let this change introduce any NEW red case beyond what's deliberately added as new
coverage.

KNOWLEDGEBASE CORRECTIONS (docs/knowledgebase/command-policy-decision-model.md):

- 'What the Engine May Not Conclude From Text It Cannot See' section's intro currently reads as reassurance that
  .text-reading policies never claim to see unknowable content — true for substitutions, was FALSE for a purely literal
  double-quoted word (exactly what findings 1-3 exploited). Once merged, this becomes true again (by construction, since
  .text itself now correctly recovers literal content) — but state plainly in the corrected passage that a double-quoted
  word's literal content IS statically knowable and was previously misread as unknowable, which is what this improvement
  fixed, so a future reader understands why the passage changed rather than assuming it was always accurate.
- 'Statement: What Every Policy Actually Reads' section's `.text` vs `.literal_text` bullet (currently describes them as
  'two deliberately different readings of one word, not a bug and its fix') is now WRONG post-merge — rewrite it to
  describe the single corrected .text accessor, its recursive DblQuoted-unwrapping behavior, and that it still
  contributes nothing for a ParamExp/CmdSubst/ProcSubst (preserving the unknowability invariant). Explicitly note that
  leaf 20260915-010959's own Interface hand-back said a future caller hitting this gap 'should follow the same pattern
  (an additive accessor, not a change to the pinned field) rather than re-deriving it' — and that THIS improvement
  deliberately supersedes that guidance after re-evaluating it live during planning (found only 3 production readers,
  none needing the naive behavior specifically). Do not edit leaf 20260915-010959's own improvement file itself — it is
  a historical record of what was decided at the time; only the living KB document needs to reflect the new reality.
- The add-allow-policy grammar section (the 'shell_touched' row of the violation-code table, and its surrounding prose)
  should mention the additional referenced_variables-based trigger.

DO NOT TOUCH: packages/shfmt-permissions (the live engine, explicitly out of scope) or the four xargs-parser-dependent
test_permission_decisions.py cases already tracked as needing packages/command-policy/parsers/xargs.py (a different,
unbuilt piece of work).

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/test_permission_decisions.py` —
  assert_decision/assert_reason_includes/assert_primary_reason helpers, and the parametrized quoting-variants pattern
  already used by REDIRECTS_THAT_MUST_DENY — reuse this exact pattern for the new filter/path double-quote-evasion cases
- `packages/command-policy/tests/conftest.py` — cwd_pinned_inside_project fixture, needed for any new redirect/path case
  the same way Batch 3's existing cases use it

**New helpers to create:**

- (none identified)

**Fantasy callsites (test-facing API sketches):**

- (none sketched)

**Testability-driven production decisions:**

- (none)

## Assumptions

- **Argument.text has exactly three production call sites: escalation_policy.py:112, allowed_command_policy.py:147, and
  allowed_command_policy.py:374/377 (the \_substitution_indices dash-classification) — no other production code reads
  it.** — confirmed (grep -rn '\\.text\\b' across packages/command-policy/lib/\*.py during planning returned only these
  three sites plus statement.py's own **repr** (debug-only) and parsed_result.py's unrelated
  ParsedResult.text/NestedCommand.text (a different attribute on a different class).)
- **Argument.literal_text has exactly one production caller: escalation_policy.py's \_classify_add_allow_invocation
  (three reads, lines ~212/217/224).** — confirmed (grep -rn 'literal_text' across packages/command-policy/ during
  planning found no other production reader — only statement.py's own definition, the three escalation_policy.py reads,
  and test files (test_statement.py, test_escalation_policy.py) plus one unrelated test name in test_sensitive_path.py
  (a differently-scoped 'literal text' concept on SensitivePathReferenced, not Argument.literal_text).)
- **Every Matcher class in matcher.py reads only from ParsedResult (built from allowed_command_policy.py's
  argument_texts list), never from an Argument object directly — so fixing Argument.text at that single source point is
  sufficient to correct all eight matcher types with no per-matcher code change.** — confirmed (Read matcher.py in full
  during planning: ParameterRegexMatcher, MatchFullParameterMatcher, PositionalArgRegexMatcher, ArgumentAtIndexMatcher,
  PositionalArgAtIndexMatcher, NamedValueMatcher, OptionValueMatcher, OptionPresentMatcher all take a
  `parsed: ParsedResult` and call parsed.all_argument_texts()/positional_values()/named/options — none imports or
  references statement.Argument.)
- **Redirect.target_text's current bug already fails closed (denies) for the existing REDIRECTS_THAT_MUST_DENY suite
  cases, via the 'unresolvable target' mechanism, not via correct path resolution — so fixing target_text changes reason
  fidelity, not the deny outcome, for these pinned cases.** — confirmed (Read test_permission_decisions.py lines
  ~773-817 during planning: the REDIRECTS_THAT_MUST_DENY parametrize list and its docstring explicitly state
  'double-quoted targets extract as the empty string' as the reason these currently deny, and the sibling
  test_an_unresolvable_redirect_target_is_denied_never_resolved_to_cwd pins the general 'empty/unresolvable target must
  deny' property that catches them.)
- **Statement.as_sole_invoked_program() already treats any CmdSubst/ProcSubst anywhere in add-allow-policy's arguments
  as shell_touched (because they are Statement subtypes reachable via .sub_statements(), which forces a None return),
  but a bare ParamExp is invisible to it because ParamExp is not a Statement subtype at all.** — confirmed (Read
  as_sole_invoked_program()'s implementation (statement.py ~lines 166-182) during planning: it returns None whenever
  self.sub_statements() is non-empty; CmdSubst/ProcSubst nodes are Statement subtypes that populate sub_statements(),
  while a ParamExp is a word-Part with no nested Statement, so it never appears there. Confirmed against
  Argument.referenced_variables' own separate recursive ParamExp-detection logic, which exists precisely because
  sub_statements()-based checks cannot see it.)

## Design Decisions

### Where the double-quote fix lives: merge into Argument.text/Redirect.target_text directly, vs. keep Argument.literal_text as a separate additive accessor and route only the known-broken call sites through it

- **Chosen:** Merge into Argument.text/Redirect.target_text directly; delete Argument.literal_text entirely
- **Rationale:** User proposed this directly ('How about we fix .text instead? ... recurse into the parts, and the parts
  know where their text is _and_ recurse into their parts'). Verified during planning that Argument.text has exactly 3
  production readers (escalation_policy.py:112, allowed_command_policy.py:147, allowed_command_policy.py:374/377) and
  Argument.literal_text has exactly 1 (escalation_policy.py's \_classify_add_allow_invocation) — none of the 3 .text
  readers needs double-quote-blindness specifically, only substitution-blindness, which the merged accessor preserves
  identically. Keeping them separate would leave .text pinned by a test but unread by any production code after this
  change, and (per a consistency gap found during planning) would have left \_substitution_indices's own
  dash-classification inconsistent with the parser's classification whenever a literal_text-only fix was applied
  elsewhere.
- **Rejected alternatives:** Keep literal_text as a separate additive accessor (matches the original task text's stated
  constraint that Argument.text's pin 'must stay', and leaf 20260915-010959's own Interface hand-back guidance to follow
  the same additive pattern for any future caller) and route only the identified broken call sites (bypass-policy,
  allowedCommands/allowedPaths argument_texts, Redirect.target_text) through it.
- **Date:** 2026-09-18

### How add-allow-policy's grammar should catch a ParamExp in the command entry

- **Chosen:** Extend the existing shell_touched check to also fire when the entry argument's
  Argument.referenced_variables is non-empty
- **Rationale:** User's counter-proposal to requiring single-quote syntax ('maybe it's easiest to just force the command
  to use a single quoted string'). Refined during planning: reusing the existing referenced_variables field (already
  computed by Argument, already recursing through DblQuoted the same way the merged .text does) catches $HOME / "$HOME"
  / ${HOME} uniformly regardless of quote style, without adding a new quoting-style grammar rule and without breaking
  the existing double-quoted flagship KB example
  (`add-allow-policy --scope user --intent "x" "echo something > somewhere"`, which references no variable and must
  remain accepted).
- **Rejected alternatives:** Requiring the command entry to be syntactically single-quoted (rejects double-quoted
  entries with no variables too, a stricter syntax-level rule rather than a content-level one); the original narrower
  proposal of special-casing ParamExp detection separately from the existing CmdSubst check.
- **Date:** 2026-09-18

### Where to characterize the behavior changes first

- **Chosen:** Add cases to tests/test_permission_decisions.py
- **Rationale:** Matches the trunk's established decision-pinning discipline — the same shared decision-specification
  suite leaf 20260915-010959 and its predecessors used to characterize behavior before implementing it, rather than
  narrower unit tests scattered near each call site.
- **Rejected alternatives:** Narrower unit tests near each call site only (matcher/statement/escalation_policy test
  files) without extending the shared decision-spec suite.
- **Date:** 2026-09-18

### Scope of the knowledgebase correction

- **Chosen:** Correct the passage and document the fixed/unfixed split
- **Rationale:** Leaving the KB inaccurate in the meantime (deferring the correction to a separate improvement) would
  mean the article keeps asserting a false safety property (that .text-reading policies never claim to see unknowable
  content) even after the fix lands, for no benefit.
- **Rejected alternatives:** Fix the call sites only; leave the doc correction as a follow-up improvement.
- **Date:** 2026-09-18

## Success Criteria

- [ ] Argument.text (lib/statement.py) recovers a double-quoted word's real literal content while still contributing ""
      for a ParamExp/CmdSubst/ProcSubst; Argument.literal_text and \_literal_text_of_parts no longer exist anywhere in
      the codebase.
- [ ] Redirect.target_text applies the identical recursive-parts fix as Argument.text (via one shared helper).
- [ ] bypass-policy "rm -rf /" (double-quoted) produces the same decision (passthrough) as bypass-policy 'rm -rf /'
      (single-quoted) — no longer silently allow.
- [ ] A double-quoted argument no longer defeats an allowedCommands block filter, or an allowedPaths prefix check,
      relative to its unquoted/single-quoted equivalents.
- [ ] A legitimate double-quoted command that a positionalArgAtIndex/namedValue filter should accept is no longer
      wrongly denied, including the \_substitution_indices consistency case (a double-quoted flag ahead of a real
      substitution no longer miscounts positional indices).
- [ ] add-allow-policy --scope user --intent "x" "cat $HOME/file" denies via
      AddAllowPolicyGrammarViolation('shell_touched'), matching how a command substitution in the entry is already
      rejected.
- [ ] \_classify_add_allow_invocation reads .text (not a deleted .literal_text) and still correctly classifies a
      double-quoted --scope/--intent/entry value.
- [ ] Every changed/new behavior is characterized by a case in tests/test_permission_decisions.py (or
      tests/test_statement.py for the Statement-level accessor change itself); the full packages/command-policy pytest
      suite is green except the four pre-existing, already-tracked xargs-parser-dependent failures.
- [ ] docs/knowledgebase/command-policy-decision-model.md's 'What the Engine May Not Conclude From Text It Cannot See'
      section and its 'Statement: What Every Policy Actually Reads' .text/.literal_text bullet are corrected — no
      remaining claim that a purely literal double-quoted word is unknowable, and no remaining 'two deliberately
      different readings' framing.

## Implementation TODO

TDD: every RED item below must fail for the right reason before any GREEN item is started. The RED items are
deliberately grouped first because they characterise the whole defect surface at once — the decision-spec suite is where
this engine's behaviour is pinned (see Design Decisions).

- [x] Update status to in-progress
- [x] RED: Statement-level tests — `Argument.text` recovers a double-quoted word's literal content and still contributes
      nothing for a ParamExp/CmdSubst/ProcSubst; same property for `Redirect.target_text` (test_statement.py)
- [x] RED: decision-spec case — bypass-policy with a double-quoted inner command produces the same decision as the
      single-quoted form (passthrough, never allow) (Batch 5)
- [x] RED: decision-spec case — a double-quoted argument cannot evade an allowedCommands block filter (Batch 2)
- [x] RED: decision-spec case — a double-quoted path cannot evade an allowedPaths prefix (Batch 2/3)
- [x] RED: decision-spec case — a double-quoted flag ahead of a real substitution no longer miscounts positional
      indices, so a legitimate command is no longer wrongly denied (Batch 2)
- [x] RED: decision-spec case — add-allow-policy denies a parameter expansion in the command entry via
      `AddAllowPolicyGrammarViolation('shell_touched')` (Batch 5)
- [x] GREEN: merge the recursive Parts-to-text logic into `Argument.text` behind one shared helper in statement.py
- [x] GREEN: apply that same shared helper to `Redirect.target_text`
- [x] GREEN: switch `_classify_add_allow_invocation` from `.literal_text` to `.text`
- [x] GREEN: add the `referenced_variables` shell_touched check for the add-allow-policy command entry
- [x] Delete `Argument.literal_text`, its constructor parameter, `_literal_text_of_parts`, and the `literal_text=` half
      of `__repr__`
- [x] Confirm no call-site change was needed at escalation_policy.py:112 or allowed_command_policy.py:147/374/377, and
      that each now reads correct values
- [x] Rewrite/rename the literal_text-era tests in test_statement.py (the pinned `.text == ""` test plus the three
      literal_text tests), consolidating the duplicates rather than keeping both forms
- [x] Update test_escalation_policy.py docstrings that describe literal_text as a separate accessor
- [x] Verify REDIRECTS_THAT_MUST_DENY still denies, now naming the real resolved path, and that the truly-empty `> ""`
      case remains unaffected
- [x] Add FLAG_LIST coverage entries for every new decision-spec test
- [x] Run the full suite (`cd packages/command-policy/tests && nix-shell --run pytest`) and confirm green except the
      four pre-existing xargs-parser failures
- [x] Correct docs/knowledgebase/command-policy-decision-model.md — the 'Text It Cannot See' framing, the
      `.text`/`.literal_text` bullet (noting the superseded leaf-20260915-010959 guidance), and the add-allow-policy
      shell_touched row
- [x] Update status to completed
