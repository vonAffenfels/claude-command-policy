# Improvement 20260920-142519: Fix spawn-claude Path Parameter Validation

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-20
- Updated: 2026-09-20
- Plan started: 2026-09-20T14:24:49+02:00
- Plan finished: 2026-09-20T15:27:19+02:00
- Impl started: 2026-09-20T15:47:44+02:00
- Impl finished: 2026-09-20T16:01:09+02:00
- Depends on: 20260919-112214

## This Improvement's Objective

`spawn-claude`'s `allowedCommands` entry in the operator's live `~/.claude/command-policy.json` declares
`hasNoPathParameters: true`, but that claim is false: `spawn-claude` forwards every argument before a literal `--`
separator verbatim to `claude`, which accepts path-valued flags (`--add-dir`, `--settings`, `--mcp-config`,
`--plugin-dir`, and others) that can read or write arbitrary filesystem locations. Measured against the real merged
config: `spawn-claude foo --settings /etc/passwd` and `spawn-claude foo --add-dir /etc` currently ALLOW. This
improvement ships a bundled `provided`-type parser (`packages/command-policy/parsers/spawn-claude.py`) that splits
`spawn-claude`'s arguments at the first literal `--` the same way the real nushell script does: the session name
(positional 0) and everything after the separator (the seed prompt, joined with spaces) are never treated as path
candidates; every token between them (the args forwarded to `claude`) is published as a path candidate using the same
total-candidacy, `=`-splitting logic `DefaultParser` already uses, with no flag-name enumeration or block-list at all.
This closes the hole for every current and future `claude` path-valued flag without needing to track `claude`'s flag
surface, while correctly NOT denying real orchestrator dispatches whose seed prompt starts with `/` or merely mentions
flag names in prose. The improvement documents (but does not write) the corrected operator config entry: drop
`hasNoPathParameters`, add `commandParser: {type: provided, name: spawn-claude}`, no filters needed. Two things
originally in scope were dropped after verification: `shfmt-session-approvals` has no entry at all in the live
`command-policy.json` (the false `pathValidation` claim exists only in the deprecated, out-of-scope
`shfmt-permissions.json`) so there is no live hole to fix there; and `cleanup-claude`'s current bare entry already
behaves correctly in both directions (allows real names, denies substitutions) so no change is recommended for it
despite `hasNoPathParameters:true` being a technically-true claim for it. Depends on improvement `20260919-112214`
(per-argument knowability / total path candidacy), which is already completed. No overlap with the independently-scoped,
not-yet-implemented improvement `20260920-131722` (StructuredParser path candidacy) — that one only touches
`lib/structured_parser.py` and never touches `provided/command-type` bundled parsers.

## Context / Why This Exists

**Origin / trigger:** An audit of the operator's live `~/.claude/command-policy.json`, driven against the working-tree
engine, found `hasNoPathParameters: true` declared on entries whose programs do take path operands. The flag only became
load-bearing security when improvement `20260919-112214` made path candidacy TOTAL — before that it was a convenience
that skipped a heuristic check, and a false declaration cost little; after it, a false declaration is the single thing
standing between an unknowable or absolute path argument and containment.

**Consumer(s) of the output:** The operator's live Bash permission decisions — `command-policy` is ENABLED and deciding
for real on this machine via the PreToolUse hook. Second, and more sharply than for most entries in this trunk: the
improvement orchestrator itself, since every session dispatch in the `/improvement:*` workflow goes through
`spawn-claude`. A false ALLOW here widens filesystem access silently; a false DENY here stops unattended orchestration
dead. Both directions land in daily work immediately.

**Adjacent systems already covering part of the need:** `DefaultParser` (`lib/default_parser.py`) owns the
total-candidacy rule this parser mirrors for its forwarded-args span — its actual shape, not a prose description of it,
is what gets copied. The containment machinery from `20260919-112214` (`_first_path_outside_allowed_prefixes`,
`_an_unknowable_argument_occupies_a_path_operand`) already does all the adjudicating; this improvement adds NO new
mechanism, it only feeds the existing one an honest path-candidate set. `packages/shfmt-permissions/` is the deprecated
old engine and is where the only remaining false claim (`shfmt-session-approvals`, `"pathValidation": false`) now lives
— deliberately out of scope, behaviourally untouched. Improvement `20260920-131722` (StructuredParser path candidacy) is
queued and touches the same conceptual ground but no shared file; see Implementation Notes for the overlap check.

## Proposed Approach

**Planned against the working tree at commit `503e192`**, `command-policy` at `0.4.1`. Every claim below about current
behaviour was MEASURED by driving `Config.from_dict(...)`/`load_config_from_environment().decision_for(...)` against
this tree's `lib/` — never inferred from whether one of this session's own Bash calls was approved, and never against
the installed plugin cache. See `## Assumptions`.

### The hole, measured

`spawn-claude`'s live entry is exactly `{"program": "spawn-claude", "hasNoPathParameters": true}`. That claim is false,
and the falseness is reachable:

| Command                                     | Today     | Should be |
| ------------------------------------------- | --------- | --------- |
| `spawn-claude foo --settings /etc/passwd`   | **ALLOW** | DENY      |
| `spawn-claude foo --add-dir /etc`           | **ALLOW** | DENY      |
| `spawn-claude foo --mcp-config /etc/passwd` | **ALLOW** | DENY      |
| `spawn-claude foo --plugin-dir /etc`        | **ALLOW** | DENY      |

`--add-dir` is access-widening by design: it hands the spawned session tool access to a directory the current one may
not have. `--settings` and `--mcp-config` load configuration — including hooks and MCP servers — from an arbitrary file.

### Why filters cannot fix this, and a parser must

Three measured properties of the default parse make a filter-only fix unavailable. All three were asserted in the
originating brief and re-verified here.

1. **The seed prompt reads as an absolute path.** An orchestrator dispatch's prompt begins with `/` because it is a
   slash command. Under the default parser every argument is a path candidate, so that word resolves to an absolute path
   outside the project and containment denies it. Measured: with the flag removed and NOTHING in its place, the real
   dispatch
   `spawn-claude claude-marketplace-impl-1 --permission-mode acceptEdits -- /improvement:implement docs/improvements/…`
   DENIES with `ArgumentPathOutsideAllowedPaths`. **The false flag is currently the only thing keeping orchestration
   alive.**
2. **`parameterRegex` is polluted by the prompt.** `ParameterRegexMatcher.match` joins ALL argument texts with spaces
   and regex-searches the result, and orchestrator seed prompts routinely quote flag names in their prose — the briefs
   in this very workflow contain the literal text `--permission-mode acceptEdits`. A block-list over joined argument
   text would fire on a prompt that merely MENTIONS a flag.
3. **Positional indices are unstable.** `DefaultParser` never pairs an option with its value, so `acceptEdits` occupies
   positional 1 only when `--permission-mode` is present. Any `positionalArgAtIndex` filter silently means something
   different depending on which flags the caller passed.

A parser is the sanctioned answer: route 2 of the decision model's three ways an entry earns the right to carry
unknowable content — "a parser that knows the grammar well enough to classify the slot as something other than a path."

### The grammar, read from the real script

Read from the resolved nix-store script (`spawn-claude` is a home-manager nushell command), not assumed:

```
main [name: string, ...args: string]
```

- `name` is the session name — passed to `claude --name` (a **display name**: prompt box, /resume picker, terminal
  title) and used as the zellij pane/stack title. It never names a file.
- The FIRST literal `--` token in `args` is the prompt separator (`$args | enumerate | where item == "--" | first`).
- Everything BEFORE it is forwarded to `claude` verbatim, minus `--focus`, which is spawn-claude's own flag.
- Everything AFTER it is joined with single spaces into the seed first message. It is never forwarded as flags.

**There is no malformed invocation to fail closed on.** The grammar is total: no `--` means every arg is forwarded and
there is no prompt (a documented, ordinary case — "Omit `--` to open claude with no first message"); a second `--` is
simply ordinary prompt text, because only the first one is the separator; a dash-prefixed word after `--` is prompt text
too. The brief anticipated needing an error path for these; measurement shows every argv shape is well-defined, so the
parser mirrors the split and has no error branch to write.

### The rule: three spans, three treatments

| Span                          | Path candidate? | Why                                                                      |
| ----------------------------- | --------------- | ------------------------------------------------------------------------ |
| `name` (argument 0)           | **No**          | Positively known not to be a path — a display name and a pane title      |
| Forwarded args (before `--`)  | **Every token** | Not knowable in detail; no knowledge means no exemption                  |
| Prompt (after the first `--`) | **No**          | Positively known not to be a path — it is a chat message, joined to text |

The forwarded-args span reuses `DefaultParser`'s exact treatment: dash-prefixed word becomes an option, everything else
a positional, and EVERY token becomes a path candidate, split on `=` so `--settings=/etc/passwd` contributes
`/etc/passwd` rather than burying an absolute value under the project root as `<project>/--settings=/etc/passwd` (the
mistake `_path_operand_of` exists to prevent).

**No flag-name block-list, and that is the central design choice.** The parser never asks which claude flags are
dangerous; it treats the whole forwarded span the way the engine already treats an argument it knows nothing about. This
is self-maintaining across claude releases: measured, the candidate design denies `--plugin-dir /etc` — a path-valued
flag the originating brief never named and no block-list of its would have contained. A block-list that silently goes
stale is a hole with a good reputation; this design has no list to go stale.

The prompt and the session name are published on `named` only (`sessionName`, `prompt`, `forwardedFlags`). `named` is
invisible to `ParameterRegexMatcher`/`PositionalArgRegexMatcher` — `ParsedResult.all_argument_texts()` reads only
`options` and `positionals` — so a prompt quoting `--add-dir /etc/passwd` in prose cannot pollute any regex filter or
contribute a path candidate. That is consequence 2 above, closed structurally rather than by escaping.

### Measured outcome of the candidate parser

Driven through the real merged config with `spawn-claude`'s entry swapped for the candidate parser:

| Command                                                                              | Verdict  | Reason                            |
| ------------------------------------------------------------------------------------ | -------- | --------------------------------- |
| `spawn-claude foo --settings /etc/passwd`                                            | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --settings=/etc/passwd`                                            | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --add-dir /etc`                                                    | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --mcp-config /etc/passwd`                                          | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --plugin-dir /etc`                                                 | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --settings $(echo /etc/passwd)`                                    | **DENY** | `UnknowablePathArgument`          |
| `spawn-claude <name> --permission-mode acceptEdits -- /improvement:implement docs/…` | ALLOW    | — (orchestration survives)        |
| `spawn-claude foo -- mentions --add-dir /etc/passwd in prose only`                   | ALLOW    | — (prompt cannot pollute)         |
| `spawn-claude foo --add-dir ./subdir`                                                | ALLOW    | — (in-project, contained)         |
| `spawn-claude foo --focus --permission-mode acceptEdits`                             | ALLOW    | —                                 |
| `spawn-claude $(echo /etc/passwd)`                                                   | ALLOW    | — (see below)                     |
| `spawn-claude foo` / `spawn-claude foo -- -- literal dashes`                         | ALLOW    | —                                 |

**`spawn-claude $(echo /etc/passwd)` still ALLOWs, and that is correct rather than a residual hole.** The substitution
occupies the session-name slot, which the parser positively classifies as not-a-path. It allows today too, but for the
wrong reason — a blanket false claim that exempts everything. After this change it allows because of a narrow claim that
is true. That distinction is exactly what the decision model means by `hasNoPathParameters` being a factual claim rather
than a waiver, and it is why the fix is a parser rather than flag removal.

### What the operator changes, and what this improvement does NOT do

**This improvement never edits `~/.claude/command-policy.json` or `.claude/command-policy.json`.** Those are the
operator's live permission configs and only the operator edits them. This improvement SHIPS the parser and DOCUMENTS the
entry; applying it is a separate, human act.

The entry the operator should write once this lands — `hasNoPathParameters` dropped, no filters needed, because
containment alone closes the hole:

```json
{
  "program": "spawn-claude",
  "commandParser": { "type": "provided", "name": "spawn-claude" }
}
```

**Until this lands and the operator applies it, the false flag STAYS.** Removing it early is not a partial improvement,
it is an outage: measured above, the dispatch every `/improvement:*` session depends on denies the moment the flag goes
away with no parser in its place. Nobody should take the flag out as a quick win.

## Affected Components

**Files:**

- `packages/command-policy/parsers/spawn-claude.py` — **NEW**, the subject. A bundled reference parser following the
  established stdin-JSON/stdout-JSON protocol (`{"arguments": [...]}` in; `options`/`positionals`/`named`/`paths` out),
  self-contained with no import from `lib/` — matching every other script in that directory.
- `packages/command-policy/tests/test_bundled_parsers.py` — unit level. Its module docstring currently scopes itself to
  "only the four parsers this improvement touches (`timeout`, `nix`, `nix-shell`, `xargs`)"; that sentence becomes false
  and must be updated in the same change, not left to rot.
- `packages/command-policy/tests/test_permission_decisions.py` — the decision specification, plus its
  `MATCHING_BRANCH_COVERAGE` manifest (line ~3058) whose two guard tests fail if a new branch has no entry.
- `docs/knowledgebase/command-policy-decision-model.md` — two passages, both CONVERTED rather than appended to; see
  Implementation Notes.
- `packages/command-policy/.claude-plugin/plugin.json` + root `.claude-plugin/marketplace.json` — version bump in
  lockstep, `0.4.1` → `0.4.2`, so the operator's plugin cache serves the new parser. **Without this bump the shipped
  parser is unreachable to the live hook**, which resolves `ProvidedParser` scripts out of the installed cache
  directory, not this working tree.

**Classes/Functions:**

- `parse_spawn_claude_args` (new, in the new parser script) plus its two small helpers mirroring
  `DefaultParser._path_operand_of` (the `=` split) and the bundled parsers' shared `resolve_path` shape.
- Read-only consumers whose behaviour changes without their code changing: `ProvidedParser` (resolves the script by
  name), `CommandParser.interpret` (turns its JSON into a `ParsedResult`),
  `AllowedCommandPolicy._first_path_outside_allowed_prefixes` and
  `AllowedCommandPolicy._an_unknowable_argument_occupies_a_path_operand` (do all the actual adjudicating).

**Explicitly NOT touched:**

- `~/.claude/command-policy.json` and `.claude/command-policy.json` — the operator's live configs. Documented, never
  written. This is a hard constraint, not a preference.
- Everything under `packages/shfmt-permissions/` — including its own `shfmt-session-approvals` entry with
  `"pathValidation": false`, which is a false claim in a DEPRECATED engine and is deliberately left alone.
- Trunk scope fences, unchanged: `lib/sensitive_paths_policy.py`; the realpath seam in `lib/path_resolution.py`;
  `Argument.text` semantics and no reintroduced `literal_text` accessor; `DefaultParser`'s path-candidate rule (it is
  the reference being mirrored, never the subject).
- `lib/structured_parser.py` — belongs to improvement `20260920-131722`.

## Implementation Notes

**Testing Strategy:** TDD (Red-Green-Refactor), per the global project conventions, with this trunk's additional
NON-VACUOUS bar: every new test is run against pre-change code and observed to FAIL for the right reason before the fix
lands, and the red counts are recorded in this file. Recent improvements in this trunk hit 59-of-61 and 11-of-11
genuinely red; that is the standard. Coverage is owed at BOTH levels — unit (`tests/test_bundled_parsers.py`) and the
decision specification (`tests/test_permission_decisions.py`).

**A missing parser and a working parser both produce `deny`, so assert at `Reason` level.** This trunk's own recorded
trap: before the script exists, a `{"type": "provided", "name": "spawn-claude"}` entry denies via
`ParserCouldNotInterpretInvocation` (`ProvidedParser._resolve_command` yields `""` for a script that is not there, and
the factory collapses every failure to `None`). A decision-spec case asserting only `deny` would therefore pass RED for
entirely the wrong mechanism and keep passing afterwards. Use `assert_primary_reason` / `assert_reason_includes`, and
pair every deny case with an ALLOW case that would break if the parser were absent.

**Baseline, MEASURED 2026-09-20 — the originating brief's stated baseline is stale.** `packages/command-policy/tests` is
**782 passed, 0 failed**, not the 749 the brief states. `packages/shfmt-permissions/tests` is **751 passed**, matching.
There is NO sanctioned red — any failure at all belongs to this change. (A stale brief baseline has now happened twice
in this trunk; `20260919-112214` found the same thing. Re-measure rather than quoting the brief.)

**Running the suite:** `cd packages/command-policy/tests && bypass-policy nix-shell --run "pytest -q"`. Plain
`nix-shell` is itself denied (its entry carries a `nestedCommand` filter the bundled `parsers/nix-shell.py` cannot
satisfy), and `python3 -m pytest` fails because pytest is not on the bare interpreter's path. Expect a human prompt on
the bypass. Pre-existing environment fact, not this improvement's to fix.

**Verify by driving this working tree's `lib/` directly, NEVER by whether your own Bash call was approved.** The live
PreToolUse hook runs from the installed plugin cache, so editing `packages/command-policy/` changes nothing about what
this session is allowed to run, and a landed, fully-tested change can appear not to work purely because the cache still
serves the old version. Every measurement in this file came from `sys.path`-injecting `packages/command-policy/lib` and
calling `load_config_from_environment().decision_for(...)`, swapping only the `spawn-claude` entry via
`Config.with_allowed_commands` so the rest of the real merged config stays intact. Keep that method. Note
`Config.allowed_commands` is a PROPERTY, not a method, and the factory is `AllowedCommand.from_entry`, not
`from_definition` — both cost a retry when guessed.

**A minimal hand-rolled test config is not a substitute for the real merged one.** While probing, a config containing
ONLY the `spawn-claude` entry reported `SubstitutedCommandNotAllowListed` for `spawn-claude $(echo /etc/passwd)` — an
artifact of `echo` not being allow-listed in that config, under `commandSubstitutionResponse: "via-allowed-commands"`.
The same command against the real merged config allows. A probe that omits the surrounding config measures the probe.

**The `provided`-parser protocol has one `paths` key feeding BOTH path fields.** `CommandParser.interpret` assigns
`paths_for_validation=paths, paths_for_filtering=paths` from the single key. So unlike `DefaultParser`, a bundled parser
cannot publish a conservative validation set and a precise filtering set separately. Consequence, accepted rather than
fixed here: if anyone later attaches a `{"type": "paths", "exactly": [...]}` filter to `spawn-claude`, its membership
domain will be the whole forwarded-args span including non-path tokens like `--permission-mode`, which would produce
spurious `FilterRejected` denials. Nobody attaches such a filter today and the recommended entry carries no filters at
all, so there is no live cost. Recorded so a future author meets it as a known limit rather than a surprise; changing
the protocol is a separate concern.

**Paths must be resolved to absolute form INSIDE the parser script.** `CommandParser.interpret` passes the `paths` list
through verbatim with no resolution of its own. Follow `parsers/git.py`'s `resolve_path` shape (`~` expansion, absolute
passthrough, `os.path.abspath` otherwise). An empty operand contributes no candidate, mirroring
`DefaultParser._every_argument_as_a_path_candidate`'s one genuine exclusion.

**Overlap check with improvement `20260920-131722` (StructuredParser path candidacy): none.** Read that file in full. It
touches `lib/structured_parser.py`, `lib/config_migration.py`, `lib/warning_value.py`, `skills/migrate-config/SKILL.md`
and four test modules. This improvement touches a new bundled parser script plus `tests/test_bundled_parsers.py`. The
only shared file is `docs/knowledgebase/command-policy-decision-model.md` and `tests/test_permission_decisions.py`, in
different passages and different cases. The two are conceptual siblings — both make a parser's path candidacy honest —
and can land in either order; neither blocks the other. If both are in flight, expect a textual merge in the
knowledgebase's route-2 paragraph, which they both want to extend for different reasons (declarative rung vs. code
rung).

**Knowledgebase passages to CONVERT, not append to:**

- The three ways an entry earns unknowable content (~lines 304-326), route 2: the worked examples are all single-program
  parsers that classify a positional by its meaning (`grep`'s pattern, `chmod`'s mode). This parser adds a genuinely
  different shape worth naming — a parser that classifies SPANS, ruling out the two it positively knows and applying the
  no-knowledge-no-exemption default to the one it does not. That is the general form other wrapper entries should copy.
- The Glossary row for "Bundled reference parser scripts" (~line 765): it currently says "most are copies of
  `packages/shfmt-permissions/scripts/parsers/`; the four wrapper parsers … deliberately diverge". `spawn-claude.py` has
  no counterpart there at all — it is the first bundled parser written FOR this engine rather than ported to it, and the
  row should say so rather than leaving a reader to assume a copy exists upstream.

### Implementation results, recorded 2026-09-20

**RED counts.** 11 unit-level cases (`test_bundled_parsers.py`, two new classes) and 12 decision-specification cases
(`test_permission_decisions.py`, 5 of them one parametrized function) — 23 new tests total, all genuinely RED
pre-change. The 5 parametrized deny cases and the 1 substitution-deny case failed via
`ParserCouldNotInterpretInvocation`, never via a coincidentally-correct verdict; every one of the 6 ALLOW guard cases
(real orchestrator dispatch, prose-mentions-a-flag, in-project `--add-dir`, session-name-looks-like-a-path,
substitution-in-session-name, substitution-in-prompt) also failed via `ParserCouldNotInterpretInvocation` rather than
passing vacuously — confirmed by running `pytest -k` against the new test names before `parsers/spawn-claude.py`
existed. GREEN: all 805 tests pass (782 baseline + 23 new), zero failures.

**Path-candidate design note, settled during GREEN.** The forwarded-args span does NOT mirror
`default_parser.py::_path_operand_of` byte-for-byte: that function returns a bare dash-prefixed argument (no `=`) AS ITS
OWN path candidate (measured: `DefaultParser.parse(["--settings", "/etc/passwd"])` puts BOTH `<cwd>/--settings` and
`/etc/passwd` in `paths_for_validation`). This parser's `_path_operand_of` instead returns `None` for a bare flag with
no `=`, so only real VALUES — a bare positional's whole text, or the value half of a `--name=value` word — become
candidates. This is a deliberate, narrower divergence, not an oversight: the option NAME is a static grammar word this
parser's own grammar controls, never attacker-influenced content, so excluding it costs no security margin while keeping
`paths` free of noise like `<project>/--settings` that a `{"type": "paths", "exactly": [...]}` filter would otherwise
have to account for. Every measured deny/allow outcome in this file's Proposed Approach table holds under this narrower
rule; see the re-measurement below.

**Re-measured against the REAL merged config, 2026-09-20** (`load_config_from_environment()`, `spawn-claude`'s entry
swapped via `Config.with_allowed_commands`, exactly per this file's own Implementation Notes method) — every row matches
the Proposed Approach's predicted table exactly, no surprises:

| Command                                                                              | Verdict  | Reason                            |
| ------------------------------------------------------------------------------------ | -------- | --------------------------------- |
| `spawn-claude foo --settings /etc/passwd`                                            | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --settings=/etc/passwd`                                            | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --add-dir /etc`                                                    | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --mcp-config /etc/passwd`                                          | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --plugin-dir /etc`                                                 | **DENY** | `ArgumentPathOutsideAllowedPaths` |
| `spawn-claude foo --settings $(echo /etc/passwd)`                                    | **DENY** | `UnknowablePathArgument`          |
| `spawn-claude <name> --permission-mode acceptEdits -- /improvement:implement docs/…` | ALLOW    | — (orchestration survives)        |
| `spawn-claude foo -- mentions --add-dir /etc/passwd in prose only`                   | ALLOW    | — (prompt cannot pollute)         |
| `spawn-claude foo --add-dir ./subdir`                                                | ALLOW    | — (in-project, contained)         |
| `spawn-claude --focus --permission-mode acceptEdits`                                 | ALLOW    | —                                 |
| `spawn-claude $(echo /etc/passwd)`                                                   | ALLOW    | — (session-name slot, honest now) |
| `spawn-claude foo` / `spawn-claude foo -- -- literal dashes`                         | ALLOW    | —                                 |

**Version-bump target was stale.** The plan assumed `command-policy` was at `0.4.1` (measured at planning time, commit
`503e192`). By implementation time, improvement `20260920-131722` (the independently-scoped StructuredParser sibling
this file's own Assumptions/Related-Past-Improvements sections named as having "no shared implementation file") had
already landed and bumped the plugin to `0.5.0` (confirmed via
`git log --oneline -- packages/command- policy/.claude-plugin/plugin.json`). Bumped from the REAL current version
instead of blindly overwriting to the stale `0.4.2` target, which would have been a silent downgrade of
`20260920-131722`'s own work: both `packages/command-policy/.claude-plugin/plugin.json` and the root
`.claude-plugin/marketplace.json` now read `0.5.1`.

**The operator entry to apply** (unchanged from the Proposed Approach's prediction — swap `spawn-claude`'s live
`~/.claude/command-policy.json` entry for):

```json
{
  "program": "spawn-claude",
  "commandParser": { "type": "provided", "name": "spawn-claude" }
}
```

Neither `~/.claude/command-policy.json` nor this repository's `.claude/command-policy.json` was modified by this
implementation — confirmed via `git status`/`git diff` showing no changes under `.claude/` and no tool call in this
session touching either path.

### Observed during exploration

Recorded so they are not silently lost. **Default action for each is to leave it alone** — none is in this improvement's
scope, and none should be folded in.

- **The only surviving false `hasNoPathParameters`-class claim is in the deprecated engine.**
  `~/.claude/shfmt-permissions.json` declares `{"program": "shfmt-session-approvals", "pathValidation": false}`, and
  that program genuinely takes `--project-dir`. It is harmless while `command-policy` is the live engine, and
  `shfmt-permissions` is explicitly not to be behaviourally changed, so it stays. It becomes relevant only if someone
  re-runs `command-policy:migrate-config`, which would faithfully translate the false claim into the new schema — worth
  knowing before that migration is run again.
- **`Config.explain()` renders a filtered entry as "must pass N filter(s)" without naming the filters.** That text is
  what the `find-auto-allowed-command` AGENT receives via the `SubagentStart` hook and is all it has to reason from, so
  a denied invocation of a filtered entry tells the recovery agent nothing about HOW to comply. Considered and
  deliberately left out of scope — see the Design Decision. It is a pre-existing, general defect that this improvement
  does not aggravate, because the entry it documents carries zero filters. Worth its own improvement.
- **`explain-policy` is still not allow-listed**, so the recovery route every deny reason points at still dead-ends on
  its own first step. Unchanged since `20260919-112214` recorded it; now recorded a third time across three sessions,
  which is itself a signal.
- **`cat`/`grep`/`find` cannot read paths outside the project**, which is correct and by design, but means reading the
  operator's own config during an audit must go through `python3` (allow-listed, unfiltered). Cost a retry twice this
  session; noted because every future config-auditing session will hit it.

**Pattern-enforcement passes (Step 2.5/2.5b) were not run:** every affected file is Python, and the available enforcers
(`patterns:anti-pattern-detector`, `patterns:pattern-enforcer`, `patterns:react-anti-pattern-detector`) cover PHP and
React only. Recorded rather than silently skipped — same as `20260919-112214` and `20260920-131722`.

## Test Architecture

**Existing helpers to reuse** (verified present at these lines, not quoted from a sibling improvement):

- `tests/test_bundled_parsers.py:24` — `run_parser(parser_name, arguments)`, which runs a bundled parser exactly as the
  engine does (subprocess, JSON on stdin, JSON back on stdout) and returns the decoded output. This is the whole
  unit-level harness; the new parser needs no new one.
- `tests/test_permission_decisions.py:102` — `assert_decision(command, config, expected_decision)`, the decision-spec
  workhorse; returns the result for further reason inspection. `:97` `decision_for` for cases wanting the raw result.
- `tests/test_permission_decisions.py:116` / `:128` — `assert_reason_includes` / `assert_primary_reason`, structural
  assertions over `Reason` value objects rather than substring matching on rendered prose. **Every deny case here MUST
  use these**, for the reason recorded in Implementation Notes: a missing parser script denies identically to a working
  one.
- `tests/test_permission_decisions.py:78` and `tests/conftest.py:150` — `assert_config_is_reachable`, which fails a case
  whose config no real `command-policy.json` could produce. Every new case inherits it through `decision_for`.
- `tests/conftest.py:79` — `cwd_pinned_inside_project(tmp_path)`, required by every containment case (it pins both the
  process cwd and `CLAUDE_PROJECT_DIR`).
- `tests/test_permission_decisions.py:3058` — the `MATCHING_BRANCH_COVERAGE` manifest plus its two guard tests.

**New helpers to create:**

- A table-driven matrix over SPAN × CONTENT — why_needed: the rule has one outcome per cell (session name / forwarded
  arg / prompt, each carrying an absolute outside path, an in-project path, an unknowable substitution, and an ordinary
  non-path word), and a hand-written case per cell invites silent gaps and copy-paste drift. The table makes a missing
  cell visible, the way this trunk's earlier matcher-type and slot-kind tables did. The diagonal is the point: the same
  `/etc/passwd` must DENY in the forwarded span and ALLOW in the prompt span.

**Fantasy callsites (test-facing API sketches):**

- `run_parser("spawn-claude", ["name", "--settings", "/etc/passwd"])["paths"] == ["/etc/passwd"]`
- `run_parser("spawn-claude", ["name", "--", "/improvement:implement", "docs/x.md"])["paths"] == []`
- `run_parser("spawn-claude", ["name", "--", "a", "--", "b"])["named"]["prompt"] == "a -- b"`
- `run_parser("spawn-claude", [])` — returns an empty shape rather than raising

**Testability-driven production decisions:**

- The separator split, the span classification and the path-candidate construction are three separately-named functions
  in the parser script rather than one loop with flags, so a unit test can assert the split directly instead of
  inferring it from the emitted `paths` list.
- The parser stays a pure function of its argument list plus `os.path` resolution, exactly like every other bundled
  parser — no environment reads beyond the cwd that `resolve_path` already implies, so `run_parser` needs no fixture.

## Assumptions

Every claim below was settled by MEASUREMENT against the working tree at `503e192` — by driving
`load_config_from_environment().decision_for(...)` with `packages/command-policy/lib` on `sys.path` (never the installed
plugin cache), by running the suites, or by reading the named file. Nothing here is inferred from whether one of this
session's own Bash calls was approved.

- **`spawn-claude`'s live entry declares `hasNoPathParameters: true`** — confirmed (read `~/.claude/command-policy.json`
  via `python3`; the entry is exactly `{"program": "spawn-claude", "hasNoPathParameters": true}`)
- **`spawn-claude` forwards every pre-`--` argument verbatim to `claude` and joins post-`--` words into a seed prompt**
  — confirmed (read the resolved nix-store script at
  `/nix/store/zmk8ds62ykac0yff6w198i6qdmhqjxll-spawn-claude/bin/spawn-claude`: `main [name, ...args]`, separator found
  via `$args | enumerate | where item == "--" | first`, `--focus` filtered out of the forwarded set)
- **`claude` accepts path-valued flags, and MORE of them than the brief named** — confirmed (`claude --help` via a
  `python3` subprocess: `--add-dir <directories...>`, `--settings <file-or-json>`, `--mcp-config <configs...>`, and also
  `--plugin-dir <path>`, which the brief never listed — direct evidence that a hand-maintained block-list would already
  be incomplete)
- **`claude --name` is a display name, not a path** — confirmed (`claude --help`: "Set a display name for this session
  (shown in the prompt box, /resume picker, and terminal title)")
- **The false flag is currently the only thing keeping the orchestrator alive** — confirmed (with the flag removed and
  nothing in its place, the real dispatch
  `spawn-claude claude-marketplace-impl-1 --permission-mode acceptEdits -- /improvement:implement docs/improvements/…`
  DENIES with `ArgumentPathOutsideAllowedPaths`, because the slash-command prompt reads as an absolute path)
- **The candidate parser closes every path-valued flag while preserving orchestration** — confirmed (measured verdict
  table in Proposed Approach: `--settings`, `--settings=`, `--add-dir`, `--mcp-config`, `--plugin-dir` all DENY; the
  real dispatch, an in-project `--add-dir ./subdir`, and a prompt quoting `--add-dir /etc/passwd` in prose all ALLOW)
- **A prompt cannot pollute a regex filter or contribute a path candidate once it is published only on `named`** —
  confirmed (read `lib/parsed_result.py`: `all_argument_texts()` reads only `options` and `positionals`; read
  `lib/matcher.py`: `ParameterRegexMatcher`/`PositionalArgRegexMatcher` consume exactly those)
- **Before the parser script exists, a `provided` entry naming it denies via `ParserCouldNotInterpretInvocation` for
  BOTH the must-deny and must-allow cases** — confirmed (measured; this is the RED state, and it is why a deny-only
  assertion would be vacuous and the paired ALLOW case is the one that genuinely goes red)
- **The brief's stated test baseline of 749 passed** — refuted (measured 2026-09-20: `packages/command-policy/tests` is
  **782 passed, 0 failed**; `packages/shfmt-permissions/tests` is 751 passed, matching the brief)
- **The brief's premise that `shfmt-session-approvals` is allow-listed in the live `command-policy.json` with a false
  `hasNoPathParameters`** — refuted (listed all 59 program names in `~/.claude/command-policy.json`; it is absent from
  both scopes, and `decision_for` returns `deny` / `ProgramNotAllowListed` for both shapes the brief said ALLOW — the
  false claim exists only in the deprecated `~/.claude/shfmt-permissions.json` as
  `{"program": "shfmt-session-approvals", "pathValidation": false}`)
- **`cleanup-claude` genuinely takes no path operands, so `hasNoPathParameters: true` would be a TRUE claim for it** —
  confirmed (read its resolved nix-store script: `main [name, ...args]` where `...args` is documented and implemented as
  "Ignored; present only so `--wrapped` has a rest parameter", and `name` reaches only the provider's pane-title lookup)
- **`cleanup-claude`'s current bare entry already behaves correctly in both directions, so the true claim would buy
  nothing** — confirmed (measured: `cleanup-claude claude-marketplace-impl-1` ALLOWs and
  `cleanup-claude $(echo /etc/passwd)` DENIEs today; adding the flag flips only the second to ALLOW)
- **The `provided`-parser protocol cannot publish separate validation and filtering path sets** — confirmed (read
  `lib/command_parser.py`: `interpret` assigns `paths_for_validation=paths, paths_for_filtering=paths` from one key)
- **A bundled parser must resolve paths to absolute form itself** — confirmed (read `lib/command_parser.py`, which
  passes `paths` through verbatim, and `parsers/git.py`, which carries its own `resolve_path`)
- **Improvement `20260920-131722` shares no implementation file with this one** — confirmed (read its Affected
  Components in full: `lib/structured_parser.py`, `lib/config_migration.py`, `lib/warning_value.py`,
  `skills/migrate-config/SKILL.md` and four test modules; the only overlap is two shared documents, in different
  passages)
- **`command-policy` is at `0.4.1` in both the plugin manifest and the marketplace entry, and no `spawn-claude.py`
  exists in `parsers/`** — confirmed (read both JSON files; listed the 16 scripts in `packages/command-policy/parsers/`)

## Design Decisions

### How the forwarded-args span earns its path candidacy

- **Chosen:** Total candidacy over the whole pre-`--` span — every token is a path candidate, `=`-split for joined forms
  — with no enumeration of claude's flags in any direction: no block-list of dangerous ones, and no allow-list of
  path-valued ones.
- **Rationale:** Measurement killed the alternatives rather than taste. A block-list over joined argument text is
  unusable because `ParameterRegexMatcher` joins every argument including the seed prompt, so it fires on a prompt that
  merely mentions a flag name. A block-list by flag NAME is already incomplete: `claude --help` carries
  `--plugin-dir <path>`, which the originating brief's own list omitted, and new flags arrive with Claude Code releases.
  Enumerating the path-valued flags instead has the identical staleness problem with the failure pointing the other way
  — a flag added upstream and not added here fails OPEN, which is the one direction this engine cannot tolerate. Total
  candidacy has nothing to keep in sync: it is the same "no knowledge means no exemption" rule `DefaultParser` already
  applies, scoped to the one span where the parser genuinely has no knowledge. Measured, it denies `--plugin-dir /etc`
  without ever having heard of the flag.
- **Rejected alternatives:** `paths: []` plus a `block` `namedValue` filter over a `forwardedFlags` channel (the brief's
  own sketch — simpler to read, but it is a block-list, so it goes stale silently and fails open, and it needs a filter
  where containment already does the job); publishing only the values of known path-valued flags as paths (same
  staleness, same fail-open direction, plus it must also track which flags consume a value).
- **Date:** 2026-09-20

### Whether the session name and the prompt are path candidates

- **Chosen:** Neither. Both are positively classified as not-a-path, and only those two spans get that exemption.
- **Rationale:** This is the route-2 claim the decision model sanctions, and it has to be earned by real knowledge, not
  convenience. It is earned here: `--name` is documented as a display name (prompt box, /resume picker, terminal title),
  and the prompt is joined into a chat message that `spawn-claude` never treats as a filename. Exempting the prompt is
  also load-bearing rather than a nicety — it is the entire reason the orchestrator survives, since its seed prompt
  starts with `/`. The honest consequence is stated rather than hidden: `spawn-claude $(echo /etc/passwd)` still ALLOWs,
  because the substitution lands in the name slot. It allowed before too, but on a blanket false claim; now it allows on
  a narrow true one.
- **Rejected alternatives:** Treat the session name as a path candidate too (would deny
  `spawn-claude $(project-name-slug)-impl-3`, a plausible dispatch shape, to protect a slot with no filesystem
  consequence); publish `paths: []` for the whole invocation (the brief's framing — it is exactly the false claim this
  improvement exists to remove, just relocated from config into code that cannot justify it either).
- **Date:** 2026-09-20

### Whether the documented entry needs filters at all

- **Chosen:** No filters. The recommended entry is the program plus the `commandParser`, nothing else.
- **Rationale:** Operator decision ("Parser only, no filters"), taken with the alternative named. Containment alone
  closes the measured hole, so a filter would be additional machinery guarding nothing that is currently reachable. It
  also keeps the entry clear of `Config.explain()`'s "must pass N filter(s)" opacity, which would otherwise make a
  denial of this specific entry harder for the recovery agent to act on.
- **Rejected alternatives:** Additionally pin `sessionName` to a safe character set with a `required` `namedValue`
  filter (defence in depth the brief sketched; the parser publishes `sessionName` so this stays available to add later
  with no code change, but nothing measured requires it today and the session name has no filesystem consequence).
- **Date:** 2026-09-20

### Scope: `shfmt-session-approvals`

- **Chosen:** Dropped from this improvement entirely. No parser, no entry, no change.
- **Rationale:** The operator's own words when shown the measurement: "I removed that between its discovery and now. It
  belongs to shfmt-permissions which is now deprecated - being replaced by command-policy." The brief's audit table was
  measured before that removal. Verified independently first: the program has no entry in either `command-policy.json`
  scope and already denies via `ProgramNotAllowListed`. The surviving `"pathValidation": false` in the deprecated
  `shfmt-permissions.json` is inside a package this trunk forbids changing behaviourally.
- **Rejected alternatives:** Ship its parser anyway as preparatory work so the operator could allow-list it safely later
  (builds an artifact with no consumer, for a deprecated program, against a config nobody intends to extend); fix the
  claim in `shfmt-permissions.json` (forbidden — that package stays behaviourally untouched).
- **Date:** 2026-09-20

### Scope: `cleanup-claude`

- **Chosen:** Leave it untouched. No entry change recommended, contradicting the brief's lean toward declaring
  `hasNoPathParameters: true` as "the cheapest correct fix".
- **Rationale:** Operator decision, taken with the trade-off named. The claim WOULD be true — its script ignores every
  argument but the name, and the name is only a pane title — but a true claim is not automatically worth making. The
  bare entry already allows every real invocation and denies the substitution shape, so the flag buys nothing today, and
  it creates a standing obligation: if `cleanup-claude`'s script ever grows a path argument, the flag silently becomes
  exactly the kind of false claim this improvement exists to remove. Declaring nothing stays correct on its own.
- **Rejected alternatives:** Declare the honest flag anyway (the brief's suggestion — correct today, zero benefit, and
  it converts a currently-safe entry into one whose correctness depends on nobody changing an unrelated nushell script
  without remembering this config).
- **Date:** 2026-09-20

### Scope: `Config.explain()`'s unnamed filters

- **Chosen:** Out of scope for this improvement, and specifically NOT spun into a blocking dependency. Recorded under
  "Observed during exploration" as deserving its own improvement.
- **Rationale:** The brief flagged it on the assumption that this fix would add filters, which would make the opacity
  more consequential. That assumption no longer holds: the recommended entry carries zero filters, so a denied
  `spawn-claude` invocation never renders a "must pass N filter(s)" line at all — it renders a containment reason, which
  names the offending path. The defect is real, pre-existing and general to every filtered entry, but this improvement
  neither triggers nor worsens it, and folding a renderer change into a parser change would couple two unrelated
  subjects.
- **Rejected alternatives:** Fix the rendering here (unrelated subject, widens a focused change into
  `reason_renderer.py`/`config.py` and their specs); leave it unconsidered (the brief explicitly forbade that, and it
  would lose the finding).
- **Date:** 2026-09-20

## Success Criteria

Each is a measured verdict against the working tree's `lib/`, not a description of code that exists.

- [x] `packages/command-policy/parsers/spawn-claude.py` exists and speaks the bundled-parser protocol: JSON
      `{"arguments": [...]}` on stdin, JSON with `options`/`positionals`/`named`/`paths` on stdout, self-contained with
      no import from `lib/`
- [x] With that parser attached and `hasNoPathParameters` absent, every one of
      `spawn-claude foo --settings     /etc/passwd`, `--settings=/etc/passwd`, `--add-dir /etc`,
      `--mcp-config /etc/passwd` and `--plugin-dir /etc` DENIES at `Reason` level with `ArgumentPathOutsideAllowedPaths`
- [x] `spawn-claude foo --settings $(echo /etc/passwd)` DENIES with `UnknowablePathArgument` — the unknowable value
      occupies a slot the parser calls a path
- [x] A real orchestrator dispatch
      (`spawn-claude <name> --permission-mode acceptEdits -- /improvement:implement docs/improvements/<file>.md`)
      ALLOWS, and this is asserted as an explicit regression guard, because it is what the false flag is currently
      protecting
- [x] A seed prompt whose prose quotes `--add-dir /etc/passwd` ALLOWS — the prompt reaches no regex matcher and
      contributes no path candidate
- [x] `spawn-claude foo --add-dir ./subdir` (an in-project directory) still ALLOWS, so the change costs no legitimate
      forwarded path
- [x] The joined form contributes the VALUE as the candidate — asserted on the resolved path being `/etc/passwd`, never
      `<project>/--settings=/etc/passwd`, so the burying failure is structurally excluded rather than merely absent
- [x] Separator handling is pinned at unit level for all four shapes: no `--` (everything forwarded, empty prompt), one
      `--`, a second `--` inside the prompt (ordinary prompt text), and a dash-prefixed word after `--` (prompt text,
      not a forwarded flag)
- [x] `run_parser("spawn-claude", [])` returns an empty shape rather than raising
- [x] Every new test was run against pre-change code and observed to FAIL for the right reason — specifically, deny
      cases are asserted at `Reason` level so they cannot pass RED via `ParserCouldNotInterpretInvocation`, and each is
      paired with an ALLOW case that genuinely flips; the red counts are recorded in this file
- [x] `tests/test_bundled_parsers.py`'s module docstring no longer claims the file covers "only the four parsers"
- [x] `MATCHING_BRANCH_COVERAGE` has entries for every new branch and both manifest guard tests stay green
- [x] `packages/command-policy/tests` is green with ZERO failures (baseline 782 passed, measured) and
      `packages/shfmt-permissions/tests` is unchanged at 751 passed
- [x] `packages/command-policy/.claude-plugin/plugin.json` and the root `.claude-plugin/marketplace.json` are both
      bumped in lockstep so the operator's plugin cache can serve the new parser — **not to `0.4.2` as originally
      planned**; see Implementation Notes for the stale-target correction (actual bump: `0.5.0` → `0.5.1`)
- [x] `docs/knowledgebase/command-policy-decision-model.md` has both named passages CONVERTED — route 2 describes the
      span-classifying parser shape, and the Glossary row no longer implies every bundled parser is a port from
      `shfmt-permissions`
- [x] This file records the exact entry the operator should write, and neither `~/.claude/command-policy.json` nor
      `.claude/command-policy.json` was modified by the implementation

## Implementation TODO

- [x] Update status to in-progress
- [x] Confirm the starting baseline: `cd packages/command-policy/tests && bypass-policy nix-shell --run "pytest -q"`
      reports 782 passed 0 failed, and `packages/shfmt-permissions/tests` reports 751 passed (plain `nix-shell` is
      denied; see Implementation Notes)
- [x] Re-read `lib/default_parser.py` as it actually stands and confirm the shape being mirrored is still there
      (`_path_operand_of`'s `=` split, `_every_argument_as_a_path_candidate`'s empty-argument exclusion); if improvement
      `20260919-112214` was reopened again and it moved, mirror what is there and note the divergence rather than this
      plan's description
- [x] Re-read the resolved `spawn-claude` nushell script and confirm the grammar has not changed since planning
      (`main [name, ...args]`, first literal `--` is the separator, `--focus` filtered from the forwarded set)
- [x] RED: add the unit-level separator and span cases to `tests/test_bundled_parsers.py` via `run_parser` — the four
      separator shapes, the three spans, the joined `--settings=/etc/passwd` form, and the empty-argument-list case;
      confirm each fails pre-change because `parsers/spawn-claude.py` does not exist
- [x] RED: add the decision-specification cases — the five path-valued flags denying at `Reason` level with
      `ArgumentPathOutsideAllowedPaths`, the substitution denying with `UnknowablePathArgument`, and the three ALLOW
      guards (real orchestrator dispatch, prose mentioning a flag, in-project `--add-dir`); confirm the ALLOW cases go
      genuinely RED pre-change (they deny via `ParserCouldNotInterpretInvocation`) rather than accepting the deny cases
      as evidence, which pass pre-change for the wrong reason
- [x] GREEN: write `packages/command-policy/parsers/spawn-claude.py` — split at the first literal `--`, publish
      `sessionName`/`prompt`/`forwardedFlags` on `named`, emit `options`/`positionals` for the forwarded span only, and
      resolve every forwarded token to an absolute path candidate with the `=` split and the empty exclusion
- [x] Verify the joined form at the resolved-path level, not just the verdict: `--settings=/etc/passwd` must yield
      `/etc/passwd`, never `<project>/--settings=/etc/passwd`
- [x] Update `tests/test_bundled_parsers.py`'s module docstring, which currently claims the file covers only the four
      wrapper parsers
- [x] Add `MATCHING_BRANCH_COVERAGE` entries for every new branch and confirm the two manifest guard tests stay green
- [x] REFACTOR: review the parser's three functions against the Yes/No clarity test — a reader should see the three
      spans and their three treatments from the names alone, without the module docstring
- [x] Run both suites: `packages/command-policy/tests` green with ZERO failures, `packages/shfmt-permissions/tests`
      unchanged at 751 passed
- [x] Re-measure the full verdict table from Proposed Approach against the REAL merged config with the shipped parser
      attached (`Config.with_allowed_commands`, swapping only the `spawn-claude` entry) and record the before/after
      results in this file
- [x] Bump `packages/command-policy/.claude-plugin/plugin.json` and the root `.claude-plugin/marketplace.json` entry in
      lockstep — target corrected at implementation time from the stale `0.4.1 → 0.4.2` to the real `0.5.0 → 0.5.1` (see
      Implementation Notes)
- [x] Update `docs/knowledgebase/command-policy-decision-model.md` by CONVERTING the two named passages — route 2's
      three-ways-to-earn-unknowable-content list (add the span-classifying parser shape) and the Glossary's bundled
      reference parser row (it no longer holds that every script is a port from `shfmt-permissions`)
- [x] Confirm the updated article reads timelessly — it describes a parser shape, not this improvement, and carries no
      reference to this improvement as a tracker
- [x] Record in this file the exact operator config entry to apply, and confirm NEITHER `~/.claude/command-policy.json`
      NOR `.claude/command-policy.json` was modified — the implementation ships and documents, the operator applies
- [x] Update status to completed

## Related Past Improvements

- improvement-20260919-112214: per-argument knowability — made path candidacy TOTAL for `DefaultParser`, which is what
  turned `hasNoPathParameters` from a convenience into load-bearing security and created this defect's severity. Its
  containment machinery does all the adjudicating here; this improvement's `Depends on` Meta line points at it.
- improvement-20260920-131722: StructuredParser path candidacy — the conceptual sibling, making the DECLARATIVE rung of
  the same ladder honest while this one adds a CODE rung. Queued, independently scoped, no shared implementation file.
- improvement-002: command-parser-system — established the parser system foundation
- improvement-007: additional-command-parsers — extended parser coverage
