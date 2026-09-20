# Improvement 20260914-213321: Build recursive Statement value object

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-14
- Updated: 2026-09-17
- Plan started: 2026-09-15T16:58:37+02:00
- Plan finished: 2026-09-16T09:45:00+02:00
- Impl started: 2026-09-17T07:42:05+02:00
- Impl finished: 2026-09-17T07:55:23+02:00
- Trunk: 20260914-195111
- Kind: decomposed
- Depends on: 20260914-213049

**You MUST also read:** `docs/improvements/improvement-20260914-195111-shfmt-permissions-command-policy-refactor.md`

## This Improvement's Objective

Build the recursive `Statement` value object that mirrors the shell's own nesting, replacing the flat `walk_ast`
traversal that currently discards it — plus the `RedirectOperator` value object for shfmt's integer redirect operators.

This is leaf 2 of trunk `20260914-195111` (the Statement value-object full rewrite). It depends on leaf
`20260914-213049` (the golden-corpus harness) because the corpus is the acceptance gate for 'no user-visible decision
change'. It is independent of leaf `20260914-213153` (the config model) — a Statement models shell structure, and is
constructible from a command string alone with no config.

THE CORE PROBLEM THIS LEAF SOLVES (measured): `walk_ast` (`analyze-bash-command.py:874`) is a generator that flattens
the entire shfmt AST into a stream of every reachable dict node, discarding all nesting and sibling order. It has ELEVEN
call sites. Because tree position is lost, `sole_command_call` (`:915`) and `redirect_targets_of` (`:971`) each
RE-DERIVE structural facts from the flat stream — reconstructing by `Type`/`Redirs`/`Stmts` key inspection what the tree
shape already knew. The redirect-allowlist gap that triggered this whole refactor exists precisely because of that
flattening. A recursive `Statement` owning its sub-statements is a faithful mirror, not an imposed abstraction.

MEASURED AST FACTS (probed against the live shfmt binary, 2026-09-14/15/16; re-verify if the shfmt version changes):

1. Redirects attach at FIVE distinct nesting paths: `Stmts[0]` (simple command, `&>`, `2>`, `<`, heredoc, background
   `&`); `Stmts[0].Cmd.Y` (pipeline, `&&`, `||`); `Stmts[0].Cmd.Stmts[0]` (subshell `( )`, brace group `{ }`);
   `Stmts[0].Cmd.Then[0]` (if/then); `Stmts[0].Cmd.Do[0]` (while/for loops).

2. A redirect belongs to a STATEMENT, and a statement is not always one command. Measured `Cmd.Type` with the CallExprs
   underneath: `{ cat a; cat b; } > out.txt` -> Block, [cat, cat]; `if true; then cat a; fi > out.txt` -> IfClause,
   [true, cat]; `while read l; do cat a; done > wh.txt` -> WhileClause, [read, cat]; `(cat a; cat b) > sub.txt` ->
   Subshell, [cat, cat]; `cat a | tee b > out.txt` -> CallExpr, [tee]. A `Statement` owning sub-statements models this
   exactly; a flat command-level model cannot.

3. `> /etc/passwd ; cat a` produces a statement with `Redirs` and NO `Cmd` — a redirect owned by no command at all.
   Natural for `Statement`, awkward for anything command-centric.

4. Statement nodes carry NO `Type` field in shfmt's JSON (CallExpr/BinaryCmd/Block/IfClause etc. do). Any structural
   walk must identify statements by position or key presence, NEVER by type string.

5. Redirect `Op` is an INTEGER, not a string. No mapping, constant set or fixture for these exists anywhere in the repo,
   and `analyze-bash-command.py` never reads `Op` at all today. `RedirectOperator` is in scope for this leaf (trunk
   decision).

6. BEYOND the five originally-measured shapes, five MORE composite `Cmd.Type` values exist and nest a nested
   `Stmt`/`Stmts`: `CaseClause` (`Items[].Stmts`, one extra level of indirection through each case item), `ForClause`
   (`Do`, a list of `Stmt`), `FuncDecl` (`Body`, a single `Stmt`, typically wrapping a `Block`), `TimeClause` (`Stmt`,
   single), `CoprocClause` (`Stmt`, single). All ten of these composite types are ALREADY enumerated together in the
   existing `COMMAND_HIDING_NODE_TYPES` set (`analyze-bash-command.py:899-912`), which also includes `CmdSubst` and
   `ProcSubst` — confirming they belong to the same 'this shape can hide or hold a command' domain concept as the five
   originally-measured redirect-nesting shapes.

7. `CmdSubst` (`$(...)`, backticks) and `ProcSubst` (`<(...)`, `>(...)`) are a SECOND, orthogonal nesting axis: they
   carry their own `Stmts` list exactly like `Block`/`Subshell`, but they live inside `CallExpr.Args[].Parts[]`
   (argument WORD content) or inside a redirect's `Word.Parts[]` — not inside the `Stmt`/`Cmd` tree. `echo $(rm -rf /)`
   looks like a plain leaf `CallExpr` but hides a full nested `Statement`. Verified nesting can be arbitrarily buried:
   inside double-quoting (`DblQuoted.Parts`), concatenated with other word parts with no separator
   (`ParamExp('PWD') + Lit('-') + CmdSubst(...)` as one word), inside array assignments, arithmetic expansions, case
   patterns, heredoc bodies, array indices, and nested 3 levels deep (`$(echo $(echo $(rm -rf /)))`) — all verified live
   against shfmt 3.13.1. The ONE verified miss: content inside an `ExtGlob` pattern (`!(...)`) is stored by shfmt's own
   parser as an OPAQUE STRING (`Pattern.Value`), never decomposed into `Parts`/`CmdSubst` at all — so no AST-based
   approach (today's `walk_ast`, or this leaf's `Statement`) can see a `$(...)` hidden inside an extglob pattern. This
   is a pre-existing `shfmt`-parser-level blind spot, not a regression introduced by this leaf: a blind dict/list
   recursion identical in shape to `walk_ast` was run against this exact case and found nothing either, proving parity
   with today's behaviour rather than a new gap. See `## Implementation Notes`.

8. THE COMPLETE REDIRECT Op TABLE, verified live against shfmt 3.13.1 by probing every standard bash redirect form:
   63='>', 64='>>', 65='<', 66='<>', 67='<&' (also covers dup-close '<&-' and move '3<&1-' — the trailing '-' is just
   Word text, not a distinct Op), 68='>&' (same pattern), 69='>|' (clobber), 71='<<' (heredoc), 72='<<-' (heredoc,
   tab-strip), 73='<<<' (here-string), 74='&>', 76='&>>'. These integers are NOT a dedicated redirect-operator enum —
   they are a sparse slice of ONE shared token space spanning mvdan/sh's entire grammar (pipe '|'=13, a case-pattern
   terminator=35, extglob '!('=143, process-substitution '<('/'>('=78/80 also verified elsewhere in this leaf's
   exploration). Gaps in the sequence (70, 75, ...) belong to other token categories, not missing redirect forms.
   RedirectOperator's mapping must therefore be an explicit finite table over these 12 values, not a derived or
   assumed-contiguous range.

9. `Background` (trailing `&`) and `Negated` (leading `!`) are booleans on the raw `Stmt` node itself, independent of
   which `Cmd.Type` (or absence of `Cmd`) sits underneath — verified live: `sleep 1 &` -> `{Cmd, Background: true}`;
   `! true` -> `{Cmd, Negated: true}`; both can co-occur. Exactly like `Redirs`, these belong on Statement's own
   base-class surface, not on any composite subclass. Confirmed against current code: `sole_command_call` checks
   `Background` (must stay checked) but does NOT check `Negated` (must stay unchecked —
   `! bypass-shfmt-permissions true` is still treated as a sole invoked program today).

THE SHAPE (from the trunk's captured sketch, refined during this leaf's own planning):
`statement.with_command("echo a; echo b")` performs a shallow copy of self and sets the copy's sub-statements to
`[self.with_command("echo a"), self.with_command("echo b")]` — sub-statements parsed from shfmt, decomposition
recursive, and everything unchanged shared between the copies.

TEST SURFACE: `TestCommandAstConstructorAndProperty` (`:2755`), `TestCommandAstImmutability` (`:2784`),
`TestCommandAstSafePatternDetection` (`:2818`), `TestCommandAstTransformationOutput` (`:2887`),
`TestCommandAstEdgeCases` (`:2927`), `TestRedirectTargetsOf` (`:3847`) and
`TestSensitiveRedirectTargetSharesTheCorrectedExtractor` (`:4080`) all poke `CommandAst(...).ast`'s raw dict by hand
(walking `Stmts[0].Cmd.Args`). They are a migration surface, not a safety net. `REDIRECT_NESTING_SHAPES` (used at
`:3851-3854`) is a parametrized table of (shape_name, command, expected_targets) and is the closest thing to a
specification of the nesting behaviour — preserve what it asserts.

## Context / Why This Exists

**Origin / trigger:** Leaf 2 of trunk 20260914-195111. `walk_ast` (analyze-bash-command.py:874) flattens the entire
shfmt AST into a stream of every reachable dict node, discarding nesting and sibling order, across 11 call sites;
`sole_command_call` and `redirect_targets_of` each re-derive structural facts from that flat stream. The
redirect-allowlist gap that triggered the whole trunk rewrite exists precisely because of this flattening — a recursive
Statement owning its sub-statements is a faithful mirror, not an imposed abstraction. This leaf depends on leaf
20260914-213049 (the golden-corpus/specification harness), which is the acceptance gate for 'no user-visible decision
change'.

**Consumer(s) of the output:** Primarily the pipeline leaf (20260914-213652), which composes Statement with Policy value
objects — Statement holds its policies and the pipeline is a map/filter/map over `policy.for_statement(statement)` ->
`policy.matches()` -> `policy.decision()`. Secondarily, this leaf's own migration of the 11 existing walk_ast call sites
(sole_command_call, redirect_targets_of, command_word_of) onto Statement directly. The specification tests from leaf
20260914-213049 are the acceptance gate this leaf's behaviour is checked against, not a direct API consumer.

User's own first sketch of the construction idea (captured verbatim during Problem-Framing, to seed the approach
discussion): 'First idea is the top level command is given the literal command string and the policies it must follow.
It grabs the shfmt ast for the command and starts subdividing itself. If it's a simple command the content becomes the
command itself. If it is multiple statements it becomes a list of sub-statements. We're basically rebuilding the AST,
maybe slightly simplified, with our own objects that know the policies and can apply them to see if they match and if
they do match we can ask their decision and why this decision is made.'

SCOPE-CALIBRATION PRINCIPLE the user stated explicitly during planning, worth carrying forward as a standing check on
this leaf's design: 'we're not writing a script parser we're just trying to decide if only allowed commands and only
allowed paths are used so we can auto allow something. The idea that we need to know where exactly in the tree the
command belongs goes together with the explain command which needs to tell us why a command was rejected.' The class
hierarchy is justified by this exact purpose (allow/deny detection plus locating WHERE a violation occurred for the
deny-reason/explain surface leaf 7 builds on), not by AST-fidelity for its own sake — the catch-all subclass
deliberately does NOT model the word-part vocabulary (Lit/ParamExp/DblQuoted/...) by name, which is the concrete
instance of this principle.

**Adjacent systems already covering part of the need:** CommandAst (analyze-bash-command.py:1106) is the nearest
existing precedent — a hand-rolled value object with a private `_from_ast()` bypass-constructor and a
`with_heredoc_normalized_to_lit()` transformer — but it wraps the raw shfmt dict as an opaque blob rather than
decomposing it recursively into sub-statements. No other adjacent system covers this; the recursive Statement is new.

## Proposed Approach

STATEMENT AS A CLASS HIERARCHY, DISPATCHED ON THE RAW NODE'S `Type` (or absence of `Cmd`):

Two categories of raw shfmt node, one build rule:

1. KNOWN/INTERESTING types get an explicit `Statement` subclass with named accessors, built by reading the node's own
   fixed fields directly (no generic scanning needed for these — the shape is known): `CallExpr` (the leaf — exposes its
   command word + args, becomes the `Command` subclass), `BinaryCmd` (`.left`/`.right`), `Block`/`Subshell`
   (`.sub_statements`, a flat list), `IfClause` (`.condition`/`.then_branch`/`.else_branch`), `WhileClause`
   (`.loop_condition`/`.loop_body`), `CaseClause` (its `Items[].Stmts` indirection), `ForClause` (`.loop_body`),
   `FuncDecl` (`.body`, a single Statement), `TimeClause`/`CoprocClause` (`.wrapped_statement`, a single Statement) —
   PLUS `CmdSubst` and `ProcSubst`, which are structurally in this same 'interesting' set even though they live inside
   word content rather than the Stmt/Cmd tree.

2. EVERYTHING ELSE collapses into ONE catch-all, `UnrecognizedCmd` (settled name — see naming design decision; occupies
   a Stmt's Cmd slot exactly like its siblings, just for a Cmd.Type this leaf does not model individually): it retains
   its raw `Type` string and raw content for diagnostics, and its `sub_statements()` is produced by a GENERIC RECURSIVE
   SCAN of its own attributes — blind dict/list recursion with no key-name assumptions, structurally identical to
   today's `walk_ast`, matching on the same fixed 'interesting type' set from (1) and recursively re-entering the build
   rule wherever it finds a hit. Today's real inhabitants of this catch-all: `ArithmCmd`, `DeclClause`, `LetClause`,
   `TestClause` (none nest a Stmt today, so they correctly report zero sub-statements) — the same generic-scan mechanism
   ALSO serves word-part content (Lit, ParamExp, DblQuoted, SglQuoted, ExtGlob, ...), which is never itself wrapped as a
   Statement instance — it is simply scanned through transparently in search of a buried CmdSubst/ProcSubst.

THE UNIFICATION: this ONE generic scan mechanism serves double duty — it is both UnrecognizedCmd's safety net against a
future/unrecognized Cmd.Type (fail-closed: 'may hide anything' rather than 'hides nothing'), AND the mechanism a known
node with free-form word content (a CallExpr's Args, a Redirect's Word) uses to discover CmdSubst/ProcSubst buried
arbitrarily deep in quoting/concatenation, WITHOUT needing to model the word-part vocabulary as its own class hierarchy.

IMPLEMENTATION PITFALL TO AVOID (flagged during planning, not yet implemented): the generic scan MUST STOP DESCENDING
the instant it hits a known/interesting match and hand reconstruction off to that match's own subclass construction,
rather than continuing to walk past it into the matched node's own children.

CONSUMPTION PATTERN: generic/structural consumers call `statement.sub_statements()` uniformly regardless of which
subclass produced them (works even for UnrecognizedCmd); role-aware consumers use `isinstance()` against the specific
subclass (e.g. `isinstance(x, BinaryCmd)`) rather than inspecting a parallel Type-string/enum field.

BASE-CLASS SURFACE (settled): `Statement`'s own properties, present on every subclass including UnrecognizedCmd:
`.redirects` (from `Redirs`), `.is_backgrounded` (from `Background`), `.is_negated` (from `Negated`) — all three are
properties of the raw Stmt node itself, independent of Cmd.Type, per measured fact 9.

REDIRECTOPERATOR (settled): an explicit finite mapping over the 12 verified Op integers (measured fact 8) —
63/64/65/66/67/68/69/71/72/73/74/76 — NOT a derived or contiguous range, since these integers are a sparse slice of one
shared token space across mvdan/sh's whole grammar. An Op integer outside this table produces a RedirectOperator
instance that RETAINS THE RAW INTEGER for diagnostics rather than raising or silently mapping to a lossy 'unknown'
sentinel — mirroring UnrecognizedCmd's own fail-visible philosophy (never silently drop information).

FREE-FUNCTION MIGRATION (settled): `command_word_of` becomes a property on `Command` (e.g. `.command_word`) — trivial,
no behaviour change. `sole_command_call`/`sole_invoked_program` becomes a `Statement` method (e.g.
`.as_sole_invoked_program() -> str | None`), computed as: root is a bare `Command`, that Command's own generic word-scan
found zero embedded sub-statements, and `.is_backgrounded` is false — `.is_negated` is deliberately NOT checked,
preserving today's behaviour that `! bypass-shfmt-permissions true` still counts as a sole invoked program.
`redirect_targets_of` becomes a `Statement` method that recursively collects redirects from itself and every
sub-statement, INCLUDING into `CmdSubst`/`ProcSubst` subtrees — this is not optional, since today's blind-recursion
implementation already catches a redirect nested inside command substitution (e.g. `echo $(cat < /etc/shadow)`), so the
replacement must cover the same territory or it is a silent regression. All three become genuine Statement
methods/properties rather than free functions operating on a raw dict or a thin adapter layer.

COMMANDAST / HEREDOC NORMALIZATION SCOPE SPLIT (settled): `with_heredoc_normalized_to_lit()`'s actual job — recognizing
the `$(cat <<'EOF' ...)` 'heredoc as string literal' idiom so filter matching doesn't wrongly treat it as command
substitution — is consumed by `_check_call_expr_against_entries`, which belongs structurally to the pipeline/filter leaf
(20260914-213652), not this one. THIS leaf builds the copy-on-write transformer itself
(`statement.with_heredoc_normalized_to_lit()`, matching CommandAst's existing precedent and the `with_*` idiom) since it
is fundamentally a Statement-shape operation; the pipeline/filter leaf decides how/when to invoke it, and owns any
widening of the pattern it recognizes (flagged during planning: today's pattern is narrow — only bare `cat` with a
quoted delimiter and no other args — and this narrowness is suspected of causing real over-denials historically; see
`## Implementation Notes`). Handed off via this leaf's `## Interface` section.

NAMING (settled, per the code-patterns skill's sibling-consistency check): the catch-all class is `UnrecognizedCmd`, not
the earlier working name `UnknownNode` — every other subclass is named directly after the shfmt `Cmd.Type` it wraps, and
'Node' was the one name that broke that convention despite the class only ever occupying a Cmd slot exactly like its
siblings.

FILE LAYOUT (settled, matching leaf 20260914-213153's established `lib/` convention — flat modules,
`import statement`/`import redirect_operator`, never `import lib.statement`): `packages/command-policy/lib/statement.py`
(the whole Statement hierarchy) and `packages/command-policy/lib/redirect_operator.py` (RedirectOperator), as two
separate concepts per Single Responsibility — one models shell structure, the other a redirect token.

STILL TO DECIDE (not yet settled): the exact method/property names on each subclass beyond what's sketched above — left
for the TDD refactor phase, per the tdd skill's own guidance that naming emerges during Refactor rather than being fully
pre-specified at planning time.

## Affected Components

**Files:**

- `packages/command-policy/lib/statement.py` (new — Statement class hierarchy: Statement, Command, BinaryCmd, Block,
  Subshell, IfClause, WhileClause, CaseClause, ForClause, FuncDecl, TimeClause, CoprocClause, CmdSubst, ProcSubst,
  UnrecognizedCmd)
- `packages/command-policy/lib/redirect_operator.py` (new — RedirectOperator)
- `packages/command-policy/tests/test_statement.py` (new)
- `packages/command-policy/tests/test_redirect_operator.py` (new)

**Classes/Functions:**

- Statement
- Command
- BinaryCmd
- Block
- Subshell
- IfClause
- WhileClause
- CaseClause
- ForClause
- FuncDecl
- TimeClause
- CoprocClause
- CmdSubst
- ProcSubst
- UnrecognizedCmd
- RedirectOperator

**Modules:**

- command-policy (`packages/command-policy/lib/statement.py`, `packages/command-policy/lib/redirect_operator.py`)

## Implementation Notes

OBSERVED DURING EXPLORATION (folded in per planning discipline — default action: leave alone unless noted otherwise;
recorded so nothing is silently lost):

1. EXTGLOB PATTERN CONTENT IS OPAQUE IN SHFMT'S AST (parity with current behaviour, not a regression). Content inside an
   shfmt `ExtGlob` pattern (`!(...)`, `@(...)`, etc.) is stored by shfmt's own parser as a single OPAQUE STRING (the
   `Pattern.Value` field), never decomposed into `Parts`/`CmdSubst`/`ProcSubst` nodes at all. Verified live:
   `echo !(rm -rf /|$(rm -rf /))` produces an `ExtGlob` node whose `Pattern.Value` is the literal text
   `"rm -rf /|$(rm -rf /)"` — no `CmdSubst` node exists anywhere in that AST for any traversal to find. A blind
   dict/list recursion structurally identical to today's `walk_ast` was run against this exact input and also found
   nothing, confirming this is a PRE-EXISTING blind spot in the current implementation too. Whether `shopt -s extglob`
   even makes this a live runtime risk is a separate execution-context question the static AST cannot answer either way.
   Not in scope for this leaf to fix (would require teaching shfmt's own parser to decompose extglob pattern internals).

2. `$?` IS PROVABLY SAFE AS A PATH/ARGUMENT COMPONENT — VERIFIED, NOT JUST ARGUED. The user recalled that the current
   engine has historically been unable to confirm `$?` is safe to allow and asked whether it can be actively set to
   something other than a numeric exit code (illustrating with a hypothetical
   `?="../../etc/passwd"; cat "/home/user/$?"`). Tested directly against real bash (not just AST parsing): a bare
   `?=value` line is NOT an assignment at all (`?` is not a valid identifier), so bash instead tries to EXECUTE a
   program literally named `?=value`, which fails and sets `$?` to the failure code (127) — not the intended string.
   Every other assignment mechanism also refuses `?` by name: `read ?`, `printf -v '?' ...`, `declare '?'=...`,
   `export '?'=...` all error with 'not a valid identifier'; `(( ? = 5 ))` is an arithmetic syntax error. `$?` is
   populated exclusively by the kernel/shell's wait-status reporting, truncated to 8 bits (verified: `exit 300` ->
   `$?`=44, `exit -1` -> `$?`=255). Its value space is therefore closed and purely numeric — decimal digits only, in [0,
   255], never containing `/`, `.`, or letters. CONCLUSION: there is no path-traversal or injection vector through `$?`;
   a historical conservative denial around it has no actual exposure behind it. This is a variable-safety-classification
   fact (belongs to `allowedVariables`/`sensitiveVariableResponse`-style policy, not to this leaf's Statement model),
   carried forward here for whichever leaf owns that classification (likely the pipeline/filter leaf or a follow-up) so
   it is not lost.

3. THE EXISTING 'SAFE HEREDOC' PATTERN RECOGNITION IS NARROW AND SUSPECTED OF CAUSING REAL OVER-DENIALS. User's own
   observation during planning: 'It feels like a lot of commands didn't pass because heredoc wasn't detected properly.'
   Cross-checked against `with_heredoc_normalized_to_lit()`'s own docstring: it recognizes exactly one shape —
   `$(cat <<'QUOTED_DELIM' ... QUOTED_DELIM)`, quoted delimiter required, `cat` with no other args, nothing else. Any
   heredoc idiom that deviates even slightly (a different program, an extra flag, a differently-quoted-but-still-safe
   delimiter) falls through to being treated as ordinary command substitution and gets blocked. Not this leaf's decision
   to widen (the consuming logic belongs to the pipeline/filter leaf — see the CommandAst/heredoc scope-split design
   decision), but recorded here as motivating context for that leaf, since it directly explains a class of historical
   false denials.

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions

## Test Architecture

**Existing helpers to reuse:**

- `packages/command-policy/tests/conftest.py` — provides the lib/ sys.path bootstrap (established by leaf
  20260915-010936) enabling direct `import statement` / `import redirect_operator` in unit tests

**New helpers to create:**

- ast_of(command: str) -> dict — wraps `shfmt --to-json` so every Statement-construction test can go straight from a
  command string to a raw AST dict, reusing this planning session's own probing methodology instead of reinventing it
  per test

**Fantasy callsites (test-facing API sketches):**

- `Statement.from_command("if true; then cat a; fi > out.txt")  # -> IfClause instance`
- `statement.sub_statements()  # uniform across all subclasses including UnrecognizedCmd`
- `statement.as_sole_invoked_program()  # -> str | None`
- `statement.all_redirect_targets()  # recursive, includes CmdSubst/ProcSubst subtrees`
- `statement.with_heredoc_normalized_to_lit()`

**Testability-driven production decisions:**

- Statement.from_command() takes a plain command string with no database or config coupling — directly constructible in
  tests from plain values, matching the Push-Persistence-to-the-Edge principle from code-patterns

## Assumptions

- **The 12 redirect Op integers documented in this leaf's objective are the complete set used by every standard bash
  redirect form** — confirmed (Probed every standard bash redirect form (<, >, >>, <>, <<, <<-, <<<, >|, &>, &>>,
  <&, >&, plus dup-close and move variants) against live shfmt 3.13.1 and recorded the exact Op integer for each:
  63,64,65,66,67,68,69,71,72,73,74,76. Also confirmed these integers are a sparse slice of one shared token space across
  mvdan/sh's whole grammar (pipe=13, case-pattern terminator=35, extglob=143, process-substitution=78/80), so gaps in
  the sequence are not missing redirect forms.)

- **A blind, key-agnostic recursive scan (matching the same shape as today's walk_ast) finds every CmdSubst/ProcSubst
  node regardless of how deeply it is buried in word construction** — confirmed (Ran the scan against 9 diverse cases
  live against shfmt 3.13.1: backtick substitution, array assignment, arithmetic expansion containing a substitution,
  single-quoting (correctly excluded), a case pattern, a heredoc body, an array index, and a 3-level-deep nested
  substitution — all 8 substitution-bearing cases found correctly. The one exception (content inside an ExtGlob pattern)
  is a shfmt-parser-level opacity, not a scan-algorithm gap: shfmt stores the pattern content as a raw string with no
  CmdSubst node produced at all, so no traversal — old or new — can see into it. Verified this is parity with today's
  behaviour, not a regression, by running the identical blind-recursion algorithm against the same input and confirming
  it also finds nothing.)

- **Background (trailing &) and Negated (leading !) are properties of the raw Stmt node itself, independent of which
  Cmd.Type occupies it** — confirmed (Verified live against shfmt 3.13.1: `sleep 1 &` produces
  `{Cmd, Background: true}`; `! true` produces `{Cmd, Negated: true}`; `! sleep 1 &` produces both simultaneously on the
  same Stmt node, alongside a CallExpr Cmd in every case.)

- **Today's sole_command_call checks Background but does not check Negated** — confirmed (Read
  analyze-bash-command.py:915-945 directly: the function checks `node.get('Background')` inside its walk_ast loop and
  returns None if true, but contains no reference to `Negated` anywhere in its body. This means
  `! bypass-shfmt-permissions true` is treated as a sole invoked program today, and the Statement-based replacement must
  preserve this exactly (not start checking Negated) to avoid a behaviour change outside this leaf's scope.)

- **Today's redirect_targets_of already recurses into CmdSubst/ProcSubst subtrees to find redirects nested inside
  command/process substitution** — confirmed (redirect_targets_of (analyze-bash-command.py:971) is implemented via the
  same blind walk_ast recursion used by sole_command_call, with no type-based filtering of which subtrees it descends
  into. Since walk_ast recurses into every dict/list value unconditionally, a redirect inside a CmdSubst's own nested
  Stmts (e.g. `echo $(cat < /etc/shadow)`) is already caught today. The Statement-based replacement must cover the same
  territory or it silently regresses a currently-working protection.)

- **$? can be actively set to a non-numeric or out-of-range value by some bash mechanism, making it unsafe to treat as
  an inherently-safe variable** — refuted (Tested every bash assignment mechanism directly: a bare `?=value` line is not
  a valid assignment (? is not a valid identifier) so bash instead tries to execute a program literally named `?=value`,
  which fails and sets
  $? to the failure code (127), not the intended string; `read ?`, `printf -v '?' ...`,
  `declare '?'=...`, `export '?'=...` all error with 'not a valid identifier'; `(( ? = 5 ))` is an arithmetic syntax
  error. $? is populated exclusively by the kernel/shell's wait-status reporting, truncated to 8 bits (`exit 300` ->
  $?=44,
  `exit -1` -> $?=255). Its value space is therefore closed and purely numeric, in [0,255], never containing '/', '.',
  or letters — there is no path-traversal or injection vector through it.)

## Design Decisions

### Sub-statement shape: uniform list vs. role-specific accessors vs. class hierarchy

- **Chosen:** A class hierarchy: `Statement` is the lean base; a specific subclass per known/interesting `Cmd.Type`
  (`BinaryCmd`, `Block`, `Subshell`, `IfClause`, `WhileClause`, `CaseClause`, `ForClause`, `FuncDecl`, `TimeClause`,
  `CoprocClause`, plus `CmdSubst`/`ProcSubst`) extends it and adds typed accessors. Generic consumers call
  `.sub_statements()` uniformly on any Statement; role-aware consumers use `isinstance()` (e.g.
  `filter(statement.sub_statements(), lambda x: isinstance(x, BinaryCmd))`) instead of inspecting a parallel
  Type-string/enum field.
- **Rationale:** User, verbatim: 'This actually sounds like a case of lean Statement, BinaryCmd extends Statement,
  consumer does filter statement.sub_statements, lambda x: isinstance(x, BinaryCmd)'. This reconciles both
  originally-offered options: a uniform generic-list interface for structural walks, and role-aware access for consumers
  that care about shell semantics — using Python's own type system as the discriminator rather than adding a parallel
  enum/string field.
- **Rejected alternatives:** Uniform flat list only, with no way to distinguish a pipeline's children from a block's
  (loses role information entirely); a single non-subclassed Statement class exposing named role-specific accessor
  properties gated by is_pipeline()/is_if_clause() helper methods (duplicates what isinstance already gives for free,
  more surface area on one class).
- **Date:** 2026-09-15

### How Statement handles a Cmd.Type without a dedicated subclass (unknown, future, or genuinely uninteresting types)

- **Chosen:** Explicit subclass per known/interesting Cmd.Type (the ten composite types plus CmdSubst/ProcSubst);
  everything else collapses into one catch-all (working name at the time: `UnknownNode`) that retains its raw Type and
  raw content AND still performs a fully generic recursive scan of its own attributes to find further Statement-shaped
  content, so it cannot silently blind-spot despite lacking named accessors.
- **Rationale:** User confirmed after being shown that four real Cmd.Type values already fall into this catch-all today
  (ArithmCmd, DeclClause, LetClause, TestClause — none nest a Stmt), so it is not a hypothetical case; the generic
  fallback protects against a future shfmt release introducing a new nesting shape. `redirect_targets_of`'s own existing
  docstring (analyze-bash-command.py:981) explicitly warns against enumerating container field names for exactly this
  reason ('would silently miss a shape it does not know about').
- **Rejected alternatives:** Subclass every currently-known type only, with no generic fallback for anything else —
  accepts a silent blind-spot risk on any future/unknown type, which is precisely the risk the existing code's own
  docstring warns against.
- **Date:** 2026-09-15

### Word-level nesting (CmdSubst/ProcSubst hidden inside argument words) and its relationship to the catch-all fallback

- **Chosen:** Unify into ONE mechanism: the same blind, key-agnostic recursive scan (structurally identical to today's
  walk_ast, filtered for the fixed 'interesting type' set) serves BOTH as the catch-all's generic sub_statements()
  discovery AND as the way any known node with free-form word content (a CallExpr's Args, a Redirect's Word) discovers
  CmdSubst/ProcSubst embedded arbitrarily deep in quoting/concatenation — rather than modelling the word-part vocabulary
  (Lit, ParamExp, DblQuoted, SglQuoted, ExtGlob, ...) as its own set of named classes. The scan must stop descending the
  instant it hits a known/interesting match, handing reconstruction off to that match's own subclass construction rather
  than continuing to walk past it.
- **Rationale:** User, verbatim: 'Build the tree properly on the known (and interesting) nodes. Collapse unknown or
  uninteresting nodes into UnknownNode which does a recursive scan of all its attributes for further Stmts or CmdNodes.'
  Verified via a 9-case probe against live shfmt 3.13.1 (backtick substitution, array assignment, arithmetic expansion,
  single-quoting correctly excluded, case patterns, heredoc bodies, array indices, and 3-level-deep nested substitution)
  that blind recursion finds every CmdSubst/ProcSubst regardless of how deeply it is buried in word construction. The
  one measured miss — content inside an ExtGlob pattern, which shfmt's own parser stores as an opaque string with no
  CmdSubst node produced at all — is a pre-existing shfmt-parser-level blind spot shared identically by today's
  walk_ast-based implementation, so it is parity, not a regression, and outside this leaf's power to fix.
- **Rejected alternatives:** A separate, differently-implemented ad hoc scan specifically for word-level
  CmdSubst/ProcSubst discovery, kept apart from the catch-all fallback mechanism (two mechanisms doing structurally the
  same job); modelling the word-part vocabulary (DblQuoted, ParamExp, SglQuoted, ExtGlob, ...) as its own explicit class
  hierarchy (adds a large surface of classes for a vocabulary this leaf has no reason to expose — only
  CmdSubst/ProcSubst matter to the permission engine).
- **Date:** 2026-09-15

### Fate of command_word_of, sole_command_call/sole_invoked_program, and redirect_targets_of as free functions operating on raw AST dicts

- **Chosen:** All three become Statement methods/properties instead of free functions over raw dicts. `command_word_of`
  -> `Command.command_word` property. `sole_command_call`/`sole_invoked_program` ->
  `Statement.as_sole_invoked_program() -> str | None`, computed as: root is a bare `Command`, that Command's own generic
  word-scan found zero embedded sub-statements, and `.is_backgrounded` is false. `redirect_targets_of` -> a recursive
  `Statement` method collecting redirects from itself and every sub-statement, including into `CmdSubst`/`ProcSubst`
  subtrees.
- **Rationale:** User confirmed. Preserves two behaviours verified against current code: `.is_negated` is deliberately
  NOT checked by the sole-invoked-program method, matching today's behaviour that `! bypass-shfmt-permissions true`
  still counts as a sole invoked program; `.is_backgrounded` IS checked, matching today's behaviour. This also surfaced
  that Background and Negated are properties of the raw Stmt node itself (measured fact 9 in the objective), independent
  of Cmd.Type — so they belong on Statement's base-class surface, not on composite subclasses only.
  redirect_targets_of's recursive-into-substitution behaviour is not a new choice but a preserved one: today's blind
  walk_ast recursion already catches a redirect nested inside command substitution (e.g. `echo $(cat < /etc/shadow)`),
  so the replacement must cover the same territory or it silently regresses.
- **Rejected alternatives:** Leaving these as free functions operating on Statement's raw underlying dict (keeps the
  migration cosmetic rather than real, and re-creates a parallel access path to structure Statement is supposed to own);
  a free-function adapter layer that wraps Statement but stays structurally separate from it (extra indirection with no
  benefit once Statement exposes the needed properties directly).
- **Date:** 2026-09-16

### Scope split for CommandAst / with_heredoc_normalized_to_lit between this leaf and the pipeline/filter leaf

- **Chosen:** This leaf builds the copy-on-write heredoc-normalizing transformer as a Statement method
  (`statement.with_heredoc_normalized_to_lit()`), matching CommandAst's existing precedent and the trunk's `with_*`
  idiom. The pipeline/filter leaf (20260914-213652) owns deciding how and when it is invoked for filter-matching
  purposes, and owns any widening of the narrow 'safe pattern' it currently recognizes. Handed off via this leaf's
  `## Interface` section rather than resolved here.
- **Rationale:** User confirmed. `with_heredoc_normalized_to_lit`'s actual consumer (`_check_call_expr_against_entries`,
  filter matching) belongs structurally to the pipeline/filter leaf, not this one — but the transformation itself is
  fundamentally a Statement-shape operation and fits the copy-on-write `with_*` idiom the trunk already established, so
  it is cheaper and more consistent for this leaf (which already has to build Statement traversal) to build the
  transformer than to leave the consuming leaf re-deriving Statement-level heredoc detection from scratch. The narrow
  scope of today's recognized 'safe pattern' (bare `cat`, quoted delimiter, no other args) is suspected of causing real
  historical over-denials — see `## Implementation Notes` — and is deliberately left for the consuming leaf to widen,
  not decided here.
- **Rejected alternatives:** This leaf leaves heredoc normalization entirely to the pipeline/filter leaf, providing no
  transformer at all (forces that leaf to duplicate Statement-traversal logic this leaf already has to write); this leaf
  both builds AND decides the filter-matching consumption logic (crosses into the pipeline/filter leaf's actual scope).
- **Date:** 2026-09-16

### Name of the catch-all Statement subclass for an unrecognized Cmd.Type

- **Chosen:** `UnrecognizedCmd` (was the working name `UnknownNode`)
- **Rationale:** User confirmed. Per the `code-patterns` skill's sibling-consistency check: every other subclass is
  named directly after the shfmt `Cmd.Type` it wraps (`BinaryCmd`, `Block`, `IfClause`, ...), mirroring the adjacent
  system's own vocabulary. `UnknownNode` broke that convention by introducing 'Node' vocabulary used nowhere else. The
  class's actual domain is precise — it only ever occupies a Stmt's Cmd slot, exactly like its siblings, just for a
  Cmd.Type this leaf does not model individually; word-part content (Lit, ParamExp, DblQuoted, ...) scanned along the
  way is never itself wrapped as a Statement instance, so 'Cmd' in the name is accurate, not aspirational.
- **Rejected alternatives:** Keeping `UnknownNode`; other candidates considered in passing (`OpaqueCmd`, `UnmodeledCmd`)
  that convey the same idea with a less direct verb-to-concept mapping than 'unrecognized'.
- **Date:** 2026-09-16

### RedirectOperator's fallback behaviour for an Op integer outside the 12 verified values

- **Chosen:** Retain the raw integer on a RedirectOperator instance rather than raising an exception or mapping to a
  lossy 'unknown' sentinel that discards the original value.
- **Rationale:** User confirmed. Mirrors `UnrecognizedCmd`'s own fail-visible philosophy established earlier in this
  same session (never silently drop information) — an Op integer outside the verified table most likely signals a shfmt
  version change or a genuine gap in this leaf's own verification, and losing the raw value would make that gap harder
  to diagnose later, not easier.
- **Rejected alternatives:** Raise an exception on construction (fails loud but makes Statement construction partial — a
  single unrecognized redirect anywhere in a command would abort building the whole tree); silently map to a generic
  UNKNOWN sentinel with no raw value retained (loses the exact information needed to diagnose a future shfmt version
  bump).
- **Date:** 2026-09-16

## Success Criteria

- [x] `packages/command-policy/lib/statement.py` implements Statement plus all 13 named subclasses (Command, BinaryCmd,
      Block, Subshell, IfClause, WhileClause, CaseClause, ForClause, FuncDecl, TimeClause, CoprocClause, CmdSubst,
      ProcSubst) and UnrecognizedCmd
- [x] Statement.from_command() dispatches to the correct subclass for every one of the ten composite Cmd.Types plus
      CallExpr/CmdSubst/ProcSubst, verified against a test table equivalent to REDIRECT_NESTING_SHAPES
- [x] sub_statements() works uniformly on every subclass including UnrecognizedCmd — correctly empty for
      ArithmCmd/DeclClause/LetClause/TestClause, and correctly non-empty for a synthetic/mocked unrecognized type that
      does nest a Stmt (proves the fallback isn't just accidentally correct for today's four cases)
- [x] The generic word-scan finds CmdSubst/ProcSubst in all 9 verified shapes from planning (backtick, array assignment,
      arithmetic, case pattern, heredoc body, array index, triple-nested substitution; single-quoting correctly
      excluded) — the ExtGlob miss is captured as an explicitly-documented, expected limitation, not a silently-passing
      gap
- [x] The scan's stop-at-match rule is regression-tested against the triple-nested case specifically (no
      double-processing)
- [x] `.redirects`, `.is_backgrounded`, `.is_negated` are correct on the base Statement surface across multiple
      subclasses
- [x] `as_sole_invoked_program()` matches today's behavior exactly: Background excludes, Negated does NOT exclude, any
      hidden-command shape excludes
- [x] `all_redirect_targets()` replicates redirect_targets_of's current behavior, including recursion into
      CmdSubst/ProcSubst subtrees and heredoc-body-word exclusion
- [x] `packages/command-policy/lib/redirect_operator.py` implements RedirectOperator over the 12 verified Op values; an
      out-of-table integer retains its raw value rather than raising or discarding it
- [x] `with_heredoc_normalized_to_lit()` exists as a Statement method, preserving CommandAst's documented safe-pattern
      semantics
- [x] `packages/command-policy/lib/placeholder.py` is gone (defensive check only — leaf 20260914-213153 should already
      have removed it)
- [x] cd packages/command-policy/tests && nix-shell --run "pytest -v" runs with every test of THIS leaf
      (test_statement.py, test_redirect_operator.py) passing, and the only failures being test_permission_decisions.py's
      by-design RED specification cases (80 failures, unchanged from before this leaf — `Config.decision_for` is still
      leaf 20260914-213652's NotImplementedError stub)
- [x] ## Interface is written, handing off with_heredoc_normalized_to_lit()'s consumption question and the $?-safety
  finding to the pipeline/filter leaf

## Implementation TODO

- [x] Update status to in-progress
- [x] Write test for RedirectOperator construction from verified Op integers
- [x] Implement RedirectOperator with 12-value mapping to pass test
- [x] Refactor RedirectOperator structure
- [x] Write test for RedirectOperator handling unrecognized Op
- [x] Implement unrecognized Op retention to pass test
- [x] Refactor RedirectOperator diagnostic surface
- [x] Write test for Statement.from_command() with simple CallExpr
- [x] Implement Statement base class and Command subclass to pass test
- [x] Refactor Statement construction interface
- [x] Write test for BinaryCmd left/right sub-statements
- [x] Implement BinaryCmd subclass to pass test
- [x] Refactor BinaryCmd accessors
- [x] Write test for Block/Subshell uniform sub_statements()
- [x] Implement Block and Subshell subclasses to pass test
- [x] Refactor Block/Subshell common behaviour
- [x] Write test for IfClause condition/then_branch/else_branch
- [x] Implement IfClause subclass to pass test
- [x] Refactor IfClause structure
- [x] Write test for WhileClause loop_condition/loop_body
- [x] Implement WhileClause subclass to pass test
- [x] Refactor WhileClause structure
- [x] Write test for CaseClause Items[].Stmts indirection
- [x] Implement CaseClause subclass to pass test
- [x] Refactor CaseClause nested traversal
- [x] Write test for ForClause/FuncDecl/TimeClause/CoprocClause
- [x] Implement remaining known-type subclasses to pass test
- [x] Refactor consistent subclass patterns
- [x] Write test for UnrecognizedCmd generic scan finding nested Statement
- [x] Implement UnrecognizedCmd with blind recursive scan to pass test
- [x] Refactor UnrecognizedCmd scan stopping at known match
- [x] Write test for CmdSubst/ProcSubst found in CallExpr Args
- [x] Implement word-content CmdSubst/ProcSubst discovery to pass test
- [x] Refactor unified scan mechanism
- [x] Write test for Statement base properties (redirects/is_backgrounded/is_negated)
- [x] Implement base-class surface to pass test
- [x] Refactor Statement base initialization
- [x] Write test for Command.command_word property
- [x] Implement command_word accessor to pass test
- [x] Refactor Command property surface
- [x] Write test for Statement.as_sole_invoked_program() positive case
- [x] Implement as_sole_invoked_program() logic to pass test
- [x] Refactor sole-program detection
- [x] Write test for Statement.as_sole_invoked_program() rejecting background
- [x] Implement Background check to pass test (Negated deliberately unchecked)
- [x] Refactor sole-program preconditions
- [x] Write test for recursive redirect_targets collection
- [x] Implement all_redirect_targets() method to pass test
- [x] Refactor redirect collection recursion
- [x] Write test for redirect_targets including CmdSubst subtree
- [x] Implement CmdSubst/ProcSubst traversal to pass test
- [x] Refactor substitution-aware redirect collection
- [x] Write test for with_heredoc_normalized_to_lit() transformation
- [x] Implement heredoc normalization transformer to pass test
- [x] Refactor copy-on-write heredoc handling
- [x] Migrate existing CommandAst test assertions onto Statement
- [x] Update status to completed

## Interface

**What this leaf produced:** `packages/command-policy/lib/statement.py` (the `Statement` value-object hierarchy — base
`Statement` plus `Command`, `BinaryCmd`, `Block`, `Subshell`, `IfClause`, `WhileClause`, `CaseClause`, `ForClause`,
`FuncDecl`, `TimeClause`, `CoprocClause`, `CmdSubst`, `ProcSubst`, and the `UnrecognizedCmd` catch-all) and
`packages/command-policy/lib/redirect_operator.py` (`RedirectOperator`), together with
`packages/command-policy/tests/test_statement.py` (85 tests) and
`packages/command-policy/tests/test_redirect_operator.py` (6 tests), plus an `ast_of` fixture added to
`tests/conftest.py`.

**Contract for downstream leaves / integrate:**

- `Statement.from_command(command)` is the sole entry point: parses via shfmt, returns a `Statement` tree, or `None` on
  any parse failure (missing binary, non-zero exit, timeout, malformed JSON) — mirroring `CommandAst`'s own fail-open
  contract. A single top-level statement is returned UNWRAPPED as its own subclass instance (e.g. an `if` line returns
  an `IfClause` directly, not a one-element wrapper); zero or multiple top-level statements collapse into a bare
  `Statement` synthetic container. The same unwrap-or-wrap rule (`_statement_from_stmt_list`) is reused everywhere a raw
  `;`-list occurs: the top-level `File.Stmts`, an `IfClause`'s `Cond`/`Then`, a `WhileClause`'s `Cond`/`Do`.
- Generic/structural consumers call `.sub_statements()` uniformly on ANY `Statement`, including `UnrecognizedCmd`.
  Role-aware consumers use `isinstance()` against the specific subclass (e.g. `isinstance(x, BinaryCmd)`), never a
  parallel Type-string/enum field.
- Base-class surface on every instance: `.redirects` (a tuple of
  `Redirect(operator: RedirectOperator, target_text: str, is_heredoc: bool)`), `.is_backgrounded`, `.is_negated`.
- Derived queries, all Statement methods (no free functions over raw dicts remain):
  `.as_sole_invoked_program() -> str | None` (root must be a bare `Command`, zero embedded sub-statements, not
  backgrounded — negation is deliberately NOT checked, preserving today's `! some-program true` behaviour),
  `.all_redirect_targets() -> tuple[str, ...]` (recursive, heredoc bodies excluded, includes `CmdSubst`/`ProcSubst`
  subtrees), `.with_heredoc_normalized_to_lit() -> Statement` (copy-on-write, preserves `CommandAst`'s exact
  safe-pattern semantics: bare `cat`, a quoted heredoc delimiter, no other args, no pipe).
- `RedirectOperator.from_op(op: int)` maps the 12 verified redirect Op integers to their symbol (`.symbol`); an
  out-of-table integer retains the raw `.op` with `.symbol is None` and `.is_recognized is False` rather than raising or
  discarding it. Every `Redirect.operator` is a `RedirectOperator`, so this is already wired into `Statement`
  construction, not a standalone unused value object.
- The generic recursive scan (`_find_embedded_statements`, module-private) is the ONE mechanism serving both
  `UnrecognizedCmd`'s blind fallback and every node's word-content substitution discovery (`Command` scans its own
  `Args` AND `Assigns` — a bare/array/arithmetic assignment can bury a `CmdSubst` in `Assigns` exactly like `Args`, a
  fact NOT called out in this leaf's own planning notes and discovered live during implementation; `CaseClause` scans
  its `Word` and `Patterns`; `ForClause` scans its `Loop`). Base `Statement.sub_statements()` ALSO always scans the raw
  `Redirs` list generically (a redirect's target word or a heredoc body can hide a substitution too), composed with each
  subclass's own structural children — this compositional wiring is new relative to this leaf's own Proposed Approach,
  which had described the scan as per-subclass; centralizing it once on the base class avoids re-deriving it nine times.
  No downstream leaf should re-implement a bespoke scan; extend `_find_embedded_statements`'s matcher set if a future
  gap is found instead.
- `IfClause` is built from a `Cond`/`Then`/`Else`-shaped dict which may or may not carry its own `Type` field (the outer
  `if` has `Type: IfClause`; a nested `elif`/`else` clause does not) — `IfClause._from_node` is reused recursively for
  both. `.condition` is `None` for a bare trailing `else` (no `Cond` key), which is how a plain else naturally falls out
  of the same shape rather than needing a separate class.
- **Handing off to the pipeline/filter leaf (`20260914-213652`):** `with_heredoc_normalized_to_lit()`'s actual
  CONSUMPTION — when/how filter matching should invoke it, and any widening of the safe-pattern it recognizes (this
  leaf's own Implementation Notes record the user's suspicion that its narrowness has caused real historical
  over-denials) — is that leaf's decision, not settled here. This leaf only built the transformer.
- **Handing off the `$?`-safety finding (`20260914-213321`'s own Implementation Notes, note 2):** `$?` is provably safe
  as a path/argument component — its value space is closed, purely numeric, `[0, 255]`, and no bash mechanism can set it
  to an attacker-controlled string. This is a variable-safety-classification fact belonging to whichever leaf owns
  `allowedVariables`/sensitive-variable policy (likely the pipeline/filter leaf or a follow-up), not to `Statement`
  itself — carried forward here so it is not lost.

**New dependency edges discovered:** None that change the Leaf Stream order.

**Follow-ups for integrate / other leaves:**

1. `Command.sub_statements()` scans BOTH `Args` and `Assigns` — the trunk's and this leaf's own planning notes describe
   the word-content scan only in terms of `CallExpr.Args`/a redirect's `Word`, never mentioning `Assigns`. Verified live
   (`arr=($(echo a) b)`, `x=$((1+$(echo 2)))`, `x=${arr[$(echo 0)]}` are all `CallExpr` with an empty/no `Args` and the
   substitution living in `Assigns`) — without this, three of the nine verified substitution-bearing shapes from
   planning (array assignment, arithmetic expansion, array index) would have silently gone undetected. Worth correcting
   in the trunk's own measured-facts copy at INTEGRATE.
2. The full `cd packages/command-policy/tests && nix-shell --run "pytest -v"` run shows 80 pre-existing failures, all in
   `test_permission_decisions.py` (the golden-corpus specification from leaf `20260914-213049`) — unchanged in count
   from before this leaf started. They are BY DESIGN: that suite calls `Config.decision_for(command)`, which leaf
   `20260914-213652` (the pipeline) has not yet implemented. This leaf's own two test files (`test_statement.py`,
   `test_redirect_operator.py`, 91 tests) are fully green.
