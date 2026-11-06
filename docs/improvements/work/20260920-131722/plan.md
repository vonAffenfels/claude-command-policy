# Improvement 20260920-131722: Align StructuredParser with DefaultParser's Path-Candidacy Rule

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-20
- Updated: 2026-09-20
- Plan started: 2026-09-20T13:17:08+02:00
- Plan finished: 2026-09-20T14:00:59+02:00
- Impl started: 2026-09-20T14:30:29+02:00
- Impl finished: 2026-09-20T14:54:07+02:00
- Depends on: 20260919-112214

## This Improvement's Objective

Bring `StructuredParser` (`packages/command-policy/lib/structured_parser.py`) in line with the path-candidacy rule
`DefaultParser` adopted in improvement `20260919-112214`: treat EVERY argument as a path candidate by default, and let
explicit config DECLARATIONS — never a shape heuristic — rule a slot out. Today `StructuredParser` still carries the
exact hole `DefaultParser` lost: its `_detect_path_heuristic` fallback, used for any positional not named in
`pathPositionals`, is the same "does this look path-shaped" guess, so an unknowable value in an undeclared slot is
silently exempted from containment, and an option's value is only ever a candidate when the option is named in
`pathOptions`. There is no live exposure today (both operator configs declare zero structured parsers, verified by
reading them), so this is a consistency and correctness improvement, not an incident. The change replaces the four
parallel structured-parser config keys with ONE per-slot declaration schema (operator decision: the general per-slot
schema, because command-policy is a full rewrite meant to shed old cruft and a self-describing per-slot declaration is
the superior shape), makes `paths_for_validation` default to path-active for every slot while keeping
`paths_for_filtering` precise for `PathsFilter`'s `exactly` semantics, mirrors `DefaultParser`'s `--name=value` split so
the candidate is the VALUE not the whole word, and updates `lib/config_migration.py` and the
`/command-policy:migrate-config` skill because migration emits structured-parser configs. It completes the deliberate
ladder the decision model names: no parser means no knowledge means everything is a candidate; `StructuredParser` means
DECLARED knowledge; a provided/custom parser means code-level knowledge — making the sanctioned "a parser that
classifies the slot" route to carrying unknowable content reachable DECLARATIVELY rather than only by writing Python.
Depends on improvement `20260919-112214`.

## Context / Why This Exists

**Origin / trigger:** Flagged by the implementor of improvement `20260919-112214` during its second fix round, in that
file's "Observed during implementation" section, and deliberately NOT acted on there: "`StructuredParser` keeps the same
hole the default parser just lost. Its `_detect_path_heuristic` fallback for positionals not named in `pathPositionals`
is the identical 'does it look path-shaped' guess, so an unknowable value in an undeclared slot is exempted there
exactly as it used to be everywhere. Left alone on scope discipline: the operator's rule names the DEFAULT parser, and
the live config uses zero structured parsers, so there is no live exposure. Worth its own decision." This improvement is
that decision.

**Consumer(s) of the output:** No consumer today — write-only, and deliberately recorded as such. Both operator configs
declare zero structured parsers (verified by reading `~/.claude/command-policy.json`, 59 entries, and
`.claude/command-policy.json`, 3 entries; every non-default parser in them is `type: "provided"`). The consumer is a
FUTURE config author — very likely the operator — who needs a program's argument grammar declared so that an unknowable
value in a known-not-a-path slot can be carried without escalation, plus anyone running `/command-policy:migrate-config`
on an old `shfmt-permissions` config that did declare a structured parser. The value delivered is that the DECLARATIVE
route up the knowledge ladder exists at all.

**Adjacent systems already covering part of the need:** `DefaultParser` (`lib/default_parser.py`) owns the rule being
mirrored and is the reference implementation — its actual shape, not any prose description of it, is what this
improvement copies. `lib/config_migration.py` plus the `/command-policy:migrate-config` skill EMIT structured-parser
configs (`_migrate_command_parser`), so a schema change here changes what every future migration produces, and the
operator has already run that migration once against their real config. `lib/sensitive_paths_policy.py` (raw-text
substring scan, its own documented residual gap) and the realpath seam in `lib/path_resolution.py` both compose with
containment and are scope-fenced OUT of this improvement.

## Proposed Approach

**Planned against the working tree at commit `8a1948b`** (improvement `20260919-112214` marked `completed`, its second
fix round landed, `command-policy` at `0.3.3`). Every claim below about current behaviour was MEASURED against that
tree, not read off a description — see `## Assumptions`. If that improvement is reopened again and `DefaultParser`
moves, re-measure `lib/default_parser.py` before implementing and mirror what is actually there.

### The hole, measured — and it is wider than "the same hole DefaultParser lost"

`DefaultParser` now treats every argument as a path candidate. `StructuredParser` does the opposite: it treats an
argument as a path candidate only when a declaration positively names it, and guesses with `_detect_path_heuristic` for
positionals nobody named. Measured consequence, same command against two entries differing only in whether a structured
parser is attached:

| Command                     | Default parser (no `commandParser`) | `structured` parser declaring `{}`             |
| --------------------------- | ----------------------------------- | ---------------------------------------------- |
| `tool $(echo /etc/passwd)`  | DENY `UnknowablePathArgument`       | **ALLOW**                                      |
| `tool --colors=/etc/passwd` | DENY `ArgumentPathOutsideAllowed…`  | **ALLOW**                                      |
| `tool --colors /etc/passwd` | DENY `ArgumentPathOutsideAllowed…`  | **ALLOW** (with `--colors` declared consuming) |

**Attaching a structured parser currently makes the engine WEAKER than attaching no parser at all.** That inverts the
ladder the decision model is built on, where more declared knowledge is supposed to buy precision, never exemption. The
literal twin exists here exactly as it did for `DefaultParser` — no substitution needed — and it is wider: an option's
consumed VALUE escapes containment entirely unless the option is named in `pathOptions`, in BOTH the
`--colors=/etc/passwd` joined form and the `--colors /etc/passwd` separated form.

### The rule

**Everything is a path candidate unless a DECLARATION rules it out.** A config author who declares nothing gets maximum
strictness; every relaxation is an explicit, auditable, falsifiable statement about the program's real grammar. This is
the same character `hasNoPathParameters` has after `20260919-112214`: a TRUE factual claim about the program, never a
waiver used to dodge a denial. A `path: false` declaration on a slot that really can carry a path is a defect of the
same kind as a wrong parser.

This completes the ladder, and the completion is the point:

- **No parser** — no knowledge — every argument is a path candidate, nothing can ever be ruled out.
- **`structured` parser** — DECLARED knowledge — a slot is ruled out exactly when the config says so, and the config
  says so in a form a reader can check against the program's man page.
- **`provided`/`command` parser** — CODE-level knowledge — a script classifies each slot.

The middle rung is what this improvement makes real. Before it, the sanctioned "a parser that classifies the slot as
something other than a path" route to carrying unknowable content (route 2 of the three in the decision model) was
reachable only by writing Python. After it, that route is reachable DECLARATIVELY, which offsets a real part of the
strictness cost `20260919-112214` imposed.

### The schema: one declaration per slot

The four parallel keys (`options`, `optionsWithArguments`, `pathOptions`, `pathPositionals`) collapse into two per-slot
lists. `doubleDashStops` survives untouched — it is a parser-level fact, not a slot-level one.

```json
"commandParser": {
  "type": "structured",
  "doubleDashStops": true,
  "options": [
    { "option": "--colors", "arguments": 1, "path": false },
    { "option": "-o", "arguments": 1 },
    { "option": "--verbose" },
    "-v"
  ],
  "positionals": [{ "index": 0, "path": false }]
}
```

- **`arguments` defaults to `0`** — a declaration with no `arguments` is a bare flag. A bare STRING item is shorthand
  for exactly that (`"-v"` ≡ `{"option": "-v"}`), which is precisely what the retired `options` key already meant, so a
  stale `options: ["-v"]` list keeps its exact former meaning rather than acquiring a new one.
- **`path` defaults to `true`** — the secure default, deliberately chosen over the friendlier one. It governs the
  option's consumed VALUES, not the option token.
- **A positional needs a declaration only to be ruled OUT.** `{"index": 0, "path": false}` is the whole point of the
  list; `{"index": 0}` is legal but says nothing the default did not already say.

### Candidacy, per field

`paths_for_validation` — the containment boundary, conservative, wants every candidate it cannot rule out:

- Every positional's value, unless that index is declared `path: false`.
- Every consumed value of every option, unless that option is declared `path: false`.
- Every option TOKEN itself, declared or not, exactly as `DefaultParser` treats any dash-word — split on `=` so
  `--name=value` contributes `value` alone (see below), otherwise the whole token. Harmless: a token resolves
  project-relative and stays contained. Chosen for uniformity with `DefaultParser` rather than special-cased.
- Never the empty string — the one thing this parser can rule out, mirroring `DefaultParser`'s own exclusion, and never
  the `--` separator when `doubleDashStops` consumed it (declared knowledge that it is syntax).

**The candidate for a joined form is the VALUE, not the whole word.** `--colors=/etc/passwd` must contribute
`/etc/passwd`. Resolving the whole word instead buries an absolute value under the project root
(`<project>/--colors=/etc/passwd`) where it reads as CONTAINED — that is exactly how the literal twin survived
undetected in `DefaultParser`, and `_path_operand_of` in `lib/default_parser.py` is the shape to mirror.
`StructuredParser` already splits `--name=value` during tokenization, so the value is in hand; the fix is that the value
must now become a candidate by default rather than only when `pathOptions` names the option.

`paths_for_filtering` — feeds `PathsFilter`'s `exactly` set-membership semantics, where a surplus entry is not a spare
check but a WRONG MEMBER that fails the filter. It therefore does **not** follow the widening, exactly as
`DefaultParser`'s does not:

- Declared path slots (an explicitly declared option or positional whose `path` is not `false`), plus
- the existing shape heuristic over UNDECLARED positionals — i.e. today's `_detect_paths` behaviour, minus anything
  declared `path: false`.

**The heuristic survives, but only here.** Measured: an entry with a structured parser and a
`{"type": "paths", "exactly": ["allowed.txt"]}` filter currently DENIES `tool ./other-file.txt` via `FilterRejected`,
and containment cannot catch that one because the path is inside the project. Dropping the heuristic from the filtering
field would silently turn that DENY into an ALLOW — a fail-open, in the one direction this engine cannot tolerate.
Confining the heuristic to the filtering field is safe precisely because validation no longer depends on it, so it can
no longer manufacture an exemption.

### Retired keys fail loudly

`options: [{...}]` is the only shape the new schema reads; `optionsWithArguments`, `pathOptions` and `pathPositionals`
raise `ConfigError` naming the replacement. Silently ignoring them is not available: ignoring `optionsWithArguments`
changes TOKENIZATION (an option's value becomes a stray positional, shifting every later index), and ignoring
`pathOptions`/`pathPositionals` would leave an author believing they had declared something. That is exactly the "config
no author could have meant" class the engine's load-time rejection doctrine exists for.

The raise belongs in `StructuredParser.from_definition`, i.e. at `decision_for` time against an actually-matching entry
— NOT eagerly in `Config.from_dict`. That is the established split: `from_dict` eagerly collects only
uncompilable-filter warnings, while every other parser/filter config defect raises from `decision_for`.

### Migration is a reshape, not a rename

`lib/config_migration.py`'s `_migrate_command_parser` currently renames two snake_case keys and passes
`pathOptions`/`pathPositionals` through verbatim. It must now TRANSLATE an old `shfmt-permissions` structured parser
into the new shape (the old schema is `options_with_arguments`, `double_dash_stops`, `pathOptions`, `pathPositionals` —
read from `packages/shfmt-permissions/scripts/analyze-bash-command.py`, which stays untouched):

- each `options_with_arguments` item (string ⇒ 1 argument, or `{option, arguments}`) becomes an `options` entry;
- each `pathOptions` member gets `"path": true` written EXPLICITLY on its option entry, so the author's original
  assertion survives as an assertion rather than dissolving into the default;
- each `pathPositionals` index becomes `{"index": N, "path": true}`;
- `double_dash_stops` → `doubleDashStops`, unchanged.

Two warnings, both new `Warning` kinds in `lib/warning_value.py`:

- **`structured_parser_defaults_to_path_active`**, fired UNCONDITIONALLY for every migrated structured parser — the same
  posture `dead_decision_knob_removed` already takes, and for the same reason: the user is materially affected either
  way. Slots the old engine guessed as non-paths are now path candidates, so their commands may start denying, and the
  fix is to declare `path: false` on the ones that genuinely are not paths.
- **`structured_parser_inert_path_option`**, fired when `pathOptions` names an option absent from
  `options_with_arguments`. Measured: that combination contributes NOTHING today (the value is parsed as a stray
  positional and the option's own `arguments` list stays empty), so it is a declaration the old author believed in and
  never got. The migration emits the entry without inventing an `arguments` count the source config never asserted, and
  says so.

The operator has already run this migration once against their real config, so any change to its output is a change to
something a human has executed. Their current result carries zero structured parsers, so nothing they hold today is
altered — but the next run of it produces the new shape.

## Affected Components

Measured, not guessed: exactly seven files in the tree mention any of the four structured-parser keys (`grep -rln` over
`packages/command-policy/{tests,lib,parsers,skills,bin}` and `docs/knowledgebase`). All seven are below; nothing else in
the package reads the structured schema.

**Files:**

- `packages/command-policy/lib/structured_parser.py` — the subject. `from_definition` (new schema + `ConfigError` for
  the four retired keys), `parse` (candidacy split across the two path fields), `_detect_paths` (rewritten),
  `_detect_path_heuristic` (survives, but consumed ONLY by the filtering field), `consumes_value_for_option` (now
  answers from a declaration's `arguments` count, so a declared bare flag correctly answers `False`).
- `packages/command-policy/lib/config_migration.py` — `_migrate_command_parser` becomes a reshape;
  `_STRUCTURED_PARSER_KEY_RENAMES` is replaced rather than extended.
- `packages/command-policy/lib/warning_value.py` — two new `Warning` classmethods
  (`structured_parser_defaults_to_path_active`, `structured_parser_inert_path_option`), following the existing
  one-classmethod-per-kind shape.
- `packages/command-policy/skills/migrate-config/SKILL.md` — its step 2 already instructs which warnings to surface and
  how loudly (it singles out `dead_decision_knob_removed` and `propagate_reshaped_to_nested_command`); the path-active
  default change needs the same treatment, because it can turn a previously-allowed command into a denial.
- `packages/command-policy/tests/test_structured_parser.py` — unit level. Nine tests, several of which assert the
  behaviour being removed (`test_an_unconfigured_positional_still_uses_heuristic_path_detection` asserts the heuristic
  drives `paths_for_validation`, which is precisely what stops being true).
- `packages/command-policy/tests/test_permission_decisions.py` — the decision specification. Six structured-parser
  configs, including the four-case `optionValue` capability block at lines ~2301–2389, plus the new cases this
  improvement owes.
- `packages/command-policy/tests/test_config_migration.py` —
  `test_structured_command_parser_field_names_are_normalised_to_camel_case` (line 261) asserts the rename that is being
  replaced by a reshape.
- `packages/command-policy/tests/test_allowed_command.py` — mentions a structured key; check whether it is load-bearing
  or incidental before touching it.
- `docs/knowledgebase/command-policy-decision-model.md` — four passages state the behaviour being changed; see
  Implementation Notes for the specific list.
- `packages/command-policy/.claude-plugin/plugin.json` + root `.claude-plugin/marketplace.json` — version bump in
  lockstep, so the operator's plugin cache picks the change up.

**Classes/Functions:**

- `StructuredParser.from_definition` / `.parse` / `._detect_paths` / `._detect_path_heuristic` /
  `.consumes_value_for_option`
- `config_migration._migrate_command_parser`
- `Warning.structured_parser_defaults_to_path_active` / `Warning.structured_parser_inert_path_option` (new)
- Read-only consumers whose behaviour changes without their code changing:
  `AllowedCommandPolicy._first_path_outside_allowed_prefixes`,
  `AllowedCommandPolicy._an_unknowable_argument_occupies_a_path_operand` (its marker probe already works against
  `StructuredParser` — measured), `PathsFilter.matches`, `AllowedCommandPolicy._require_parser_declares_option_value`

**Explicitly NOT touched (trunk scope fences):** `lib/sensitive_paths_policy.py`; the realpath seam in
`lib/path_resolution.py`; `Argument.text` semantics and no reintroduced `literal_text` accessor; `lib/default_parser.py`
itself (it is the reference, not the subject); everything under `packages/shfmt-permissions/` (read for the old schema
only).

## Implementation Notes

**Testing Strategy:** TDD (Red-Green-Refactor), per the global project conventions, with this trunk's additional
NON-VACUOUS bar: every new test is run against pre-change code and observed to FAIL for the right reason before the fix
lands, and the red counts are recorded here. Recent improvements in this trunk hit 59-of-61 and 11-of-11 genuinely red;
that is the standard. Coverage is owed at BOTH levels — unit (`tests/test_structured_parser.py`) and the decision
specification (`tests/test_permission_decisions.py`), the latter with `MATCHING_BRANCH_COVERAGE` manifest entries so the
two guard tests stay green.

**Verify by driving the working tree's `lib/` directly, NEVER by whether your own Bash call was approved.** The live
PreToolUse hook runs from the installed plugin cache, which is at `0.3.0` and predates all of this work, so editing
`packages/command-policy/` changes nothing about what this session is allowed to run, and a landed, fully-tested change
can appear not to work purely because the cache still serves the old version. The planning probe
(`docs/improvements/experiments/20260920-131722/probe_structured_parser_today.py`) does this correctly —
`sys.path.insert` on `packages/command-policy/lib`, then `Config.from_dict(...).decision_for(command)` — and every
measurement in this file came from it. Keep that method.

**Running the suite:** `cd packages/command-policy/tests && bypass-policy nix-shell --run "pytest -q"`. Plain
`nix-shell` is itself denied (its entry carries a `nestedCommand` filter that the bundled `parsers/nix-shell.py` cannot
satisfy), and `python3 -m pytest` fails because pytest is not on the bare interpreter's path. Expect a human prompt on
the bypass. This is a pre-existing environment fact, not this improvement's to fix.

**Baseline to confirm before starting, and to hold at the end:** `packages/command-policy/tests` 737 passed / 0 failed,
`packages/shfmt-permissions/tests` 751 passed. There is NO sanctioned red — any failure at all belongs to this change.

**The marker probe already works against `StructuredParser`, so containment needs no new wiring.** Measured:
`tool $(echo /etc/passwd)` against a parser declaring `pathPositionals: [0]` already denies with
`UnknowablePathArgument`. `_an_unknowable_argument_occupies_a_path_operand` appends its marker to the unknowable
argument's text and re-parses, asking only whether any resulting path carries the marker — it is parser-agnostic. So
widening candidacy in the parser is sufficient; `allowed_command_policy.py` needs no change. Check this by measurement
rather than assumption once the parser change lands: for the separated form the unknowable argument's text is `""`, so
the marked text is the bare marker, which must land as the option's consumed value and therefore as a candidate.

**Why `_detect_path_heuristic` must survive rather than being deleted.** It is tempting to remove it with the rest of
the guessing, and that would be a fail-open. Measured: an entry with a structured parser and a
`{"type": "paths", "exactly": ["allowed.txt"]}` filter currently DENIES `tool ./other-file.txt` via
`FilterRejected(paths)` — and containment cannot catch that one, because `./other-file.txt` is inside the project. The
only thing standing between that command and an ALLOW is the heuristic populating `paths_for_filtering`. Keep it, scoped
to that field alone, where a surplus member costs precision rather than safety.

**The `options` key is already in the specification's vocabulary but the engine has never read it, and two spec tests
pass for the wrong reason.** `tests/test_permission_decisions.py`'s four-case `optionValue` block declares
`{"type": "structured", "options": ["-m"], "optionsWithArguments": []}` to mean "`-m` is declared, but as a bare flag".
`StructuredParser.from_definition` reads only `optionsWithArguments`/`doubleDashStops`/`pathOptions`/`pathPositionals`,
so `options` is inert (measured: a parser given `{"options": ["-v"]}` produces output identical to one given `{}`). The
two `pytest.raises(ConfigError)` cases in that block therefore pass because the option is absent from
`optionsWithArguments`, NOT because it was declared a flag — the distinction the block's own docstring says it exists to
prove ("Knowing the option exists is not enough; the filter needs the option to CONSUME") is currently untested. The new
schema makes that distinction real for the first time: `{"option": "-m"}` is a declared flag and
`consumes_value_for_option("-m")` must answer `False`, while `{"option": "-m", "arguments": 1}` answers `True`. Rewrite
those four cases onto the new shape and confirm case 3 now fails for the intended reason — check it by making
`consumes_value_for_option` temporarily lenient and watching case 3 go green when it should not.

**`pathOptions` without `optionsWithArguments` is a silent no-op today.** Measured: a parser given
`{"pathOptions": ["-o"]}` and arguments `["-o", "out.txt"]` produces NO path candidates at all — `-o` consumes nothing,
so `out.txt` lands as positional 0, and the heuristic then declines it. The author declared a path operand and got
nothing. The new schema makes this shape unwritable (path-ness lives on the same declaration as the argument count), and
the migration warns when it converts one.

**Knowledgebase passages that state the behaviour being changed** — CONVERT them, do not append:

- "A Filter Sees Only What the Parser Produced" (~line 342): "Only a `structured` parser told which options consume
  values (`options_with_arguments`)…" — wrong key name, wrong schema; it must name the new per-slot declaration.
- The `DefaultParser`-total-candidacy passage under argument-path containment (~lines 296-302): it currently explains
  total candidacy as a property of the default parser alone; it becomes the general rule, with the structured parser as
  the rung where declarations rule slots out.
- The three ways an entry earns unknowable content (~lines 304-318): route 2 ("a parser that knows the grammar well
  enough to classify the slot") must say that route is now reachable declaratively, not only by writing Python.
- The `ParsedResult` two-field passage (~lines 400-408): "The two have since genuinely diverged in the default parser" —
  the divergence now exists in both pure parsers, for the same reason and with different mechanics (everything-vs-
  heuristic in the default parser, declarations-vs-heuristic in the structured one).
- The migration translation bullet (~lines 626-629): "field names are normalised to the new engine's camelCase spelling
  … silently … and there is nothing to warn about" is exactly inverted by this change — it becomes a structural reshape
  with two warnings.

**Accepted residual, carried over deliberately:** an attached short-option value with no `=` (`-f/etc/passwd`) is still
read as one project-relative word. The new schema does not add a way to declare attached-value syntax; an entry needing
`-f` understood that way declares a `provided` parser. Recorded rather than fixed, matching `default_parser.py`'s own
docstring.

### Progress: schema + parser rewrite landed (TDD round 1)

Baseline confirmed at start: `packages/command-policy/tests` 754 passed / 0 failed (not the plan's stale 737 - later
commits on this trunk added tests since planning), `packages/shfmt-permissions/tests` 751 passed. `CLAUDE_PROJECT_DIR`
is unset in this session's Bash tool environment (confirmed by measurement, matching the plan's warning); all
`decision_for` measurements below were driven with `cwd_pinned_inside_project` (which sets it explicitly per-case) or,
for ad-hoc probing, by setting it explicitly before constructing `PathResolutionContext`/`Config`.

`tests/test_structured_parser.py` was rewritten wholesale onto the new `options`/`positionals` schema (22 tests, up from
9). Run against pre-change `structured_parser.py`: **13 of 22 genuinely RED**, each for the right reason (new schema
keys unread, candidacy not widened, retired keys not yet rejected); the other 9 assert tokenization/doubleDashStops
behaviour this change does not touch and correctly stayed green throughout.

`tests/test_permission_decisions.py` gained a new "StructuredParser path candidacy" section plus rewrote the four
`optionValue` capability cases and two other pre-existing structured-parser configs onto the new schema. Run against
pre-change code: **13 of 171 relevant cases genuinely RED** (12 parametrized instances collapse the count differently in
pytest's own listing - 13 distinct FAILED lines). Two cases originally written with `$(echo ...)` substitutions turned
out to pass pre-change for the WRONG reason (the marker text `__command_policy_unknowable_operand__` never looks
path-shaped to the old heuristic, so the old code accidentally "allowed" without ever reading the new declaration) -
caught by checking each RED case's failure reason, not just its color, and rewritten to use a literal `/etc/passwd`
positional/option-value instead (which the old heuristic WOULD have caught, making the pre-change DENY genuine and the
post-change declared-exemption ALLOW a real behavioural pin). One headline comparison case (`tool --colors /etc/passwd`
against a parser declaring `--colors` consumes an argument) also already passed pre-change, because the old heuristic
happened to catch the visibly-path-shaped separated-form value by accident - kept as a legitimate (if already-green) pin
of the pair, not removed.

After rewriting `lib/structured_parser.py` onto the new schema (per-slot `OptionDeclaration`/`PositionalDeclaration`
value objects built once in `from_definition`; `_paths_for_validation`/`_paths_for_filtering` as two separately-named
builders; `_detect_path_heuristic` survives, consumed only by the filtering builder): full suite is **779 passed / 0
failed** in `packages/command-policy/tests` (754 baseline + 25 new cases, all green). `packages/shfmt-permissions/tests`
not yet re-run in this round (untouched by this change so far; will be re-confirmed before completion).

### Adjudication of every existing test whose meaning legitimately changed

- **`test_an_unconfigured_positional_still_uses_heuristic_path_detection`** (unit) - its claim (the heuristic drives
  `paths_for_validation`) is precisely what stopped being true. Rewritten as
  `test_an_undeclared_positional_is_a_validation_candidate_even_when_it_does_not_look_like_a_path`, asserting the
  opposite for validation (`notafile`, which the heuristic would have rejected, is still a validation candidate) while
  pinning that the heuristic survives, scoped to `paths_for_filtering` alone, in the same assertion.
- **The `pathOptions`/`pathPositionals` unit cases**
  (`test_a_configured_path_option_resolves_its_argument_via_the_ injected_context`,
  `test_a_configured_path_positional_resolves_via_the_injected_context`) - rewritten onto the new schema
  (`options: [{"option": "-o", "arguments": 1}]`, `positionals: [{"index": 0, "path": true}]`), now pinning the
  DEFAULT-active behaviour rather than an explicit legacy declaration, since under the new rule these examples no longer
  need the old positive declaration to earn their candidacy - only a `path: false` declaration would change the outcome
  now.
- **The four `optionValue` capability cases**
  (`test_option_value_filter_is_rejected_when_the_parser_declares_no_such_ option` through
  `...loads_when_the_parser_declares_both_kinds_of_option`) - rewritten onto `options` bare-string/dict-record
  declarations. Case 3 in particular now genuinely tests what its docstring always claimed ("knowing the option exists
  is not enough; the filter needs the option to CONSUME") - verified non-vacuous by temporarily making
  `consumes_value_for_option` return `True` unconditionally and observing case 3 wrongly pass (see the RED-round note
  above).
- **`tests/test_allowed_command.py:62`** (`test_an_object_entry_carries_its_command_parser`) - incidental use of the old
  schema in a fixture whose actual subject (`AllowedCommand` stores `commandParser` opaquely) is schema-agnostic.
  Updated to the new schema as a one-line honesty fix, per the plan's "fold in only if it stays that cheap" guidance -
  it did.
- **`test_structured_command_parser_field_names_are_normalised_to_camel_case`** (`test_config_migration.py:261`) - its
  claim (migration is a pure rename) is exactly what stopped being true. Renamed to
  `test_structured_command_parser_reshapes_into_the_new_per_slot_schema` and rewritten to assert the full reshape plus
  the two new warnings, in three separate test functions for independent failure diagnosis.
- **Two structured-parser configs unrelated to path candidacy**
  (`test_a_nested_command_filter_needs_a_parser_that_ publishes_sub_commands`'s `{"optionsWithArguments": []}` and the
  `_git_commit_structured_config` helper's `{"optionsWithArguments": ["-m"]}`) - neither test's SUBJECT is the retired
  key (one tests nested-command capability rejection, the other `optionValue`'s knowable-only re-parse path with
  `hasNoPathParameters: true` already disabling containment) - updated to the new schema's equivalent shape with no
  behavioural change to what either test actually specifies.

**Declared-exemption success criterion confirmed for the substitution form too, not only the literal form pinned in the
committed tests.** The committed decision-spec exemption tests use a literal `/etc/passwd` deliberately (so the
pre-change run is genuinely RED against the old shape-heuristic, per the note above), but the success criterion's own
wording uses `$(echo anything)`. Measured directly against the finished tree: `tool $(echo anything)` with positional 0
declared `path: false` ALLOWs, and `tool --colors $(echo anything)` with `--colors` declared `arguments: 1, path: false`
ALLOWs - both confirm the exemption generalises to unknowable content, not only to literals.

### Before/after verdict table (re-measured against the finished tree)

Re-running `probe_structured_parser_today.py` verbatim against the finished tree fails at its very first call using a
retired key (`pathPositionals`) - itself a measurement, not a defect: a config author who did not migrate would now get
a loud `ConfigError` instead of a silent exemption. A second probe (`probe_structured_parser_after.py`, same directory,
deleted alongside the first after this table was recorded) exercised the equivalent scenarios on the new schema:

| Command                                                                         | Before (measured pre-change)               | After (measured post-change)                                            |
| ------------------------------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------- |
| `tool $(echo /etc/passwd)`, parser `{}`                                         | ALLOW                                      | DENY `UnknowablePathArgument`                                           |
| `tool --colors=/etc/passwd`, parser `{}`                                        | ALLOW                                      | DENY `ArgumentPathOutsideAllowedPaths(path='/etc/passwd')`              |
| `tool --colors /etc/passwd`, `--colors` declared consuming                      | ALLOW                                      | DENY `ArgumentPathOutsideAllowedPaths(path='/etc/passwd')`              |
| `tool /etc/passwd`, positional 0 declared `path: false`                         | ALLOW (heuristic never asked)              | ALLOW (declared exemption)                                              |
| `tool --colors /etc/passwd`, `--colors` declared `path: false`                  | DENY (old key unread, heuristic caught it) | ALLOW (declared exemption)                                              |
| `tool /etc/passwd /etc/hosts`, only positional 0 declared false                 | DENY                                       | DENY (positional 1 still undeclared)                                    |
| `tool ./other-file.txt` + `paths` filter `exactly: [allowed.txt]`               | DENY `FilterRejected(paths)`               | DENY `FilterRejected(paths)` (unchanged, heuristic scoped to filtering) |
| `commandParser` carrying `optionsWithArguments`/`pathOptions`/`pathPositionals` | silently accepted, guessed                 | `ConfigError` naming the replacement                                    |

The whole `docs/improvements/experiments/20260920-131722/` directory was deleted after this table was recorded, per the
Implementation TODO.

**Marker-probe assumption confirmed by direct measurement** (not inference from Bash-tool behaviour -
`CLAUDE_PROJECT_DIR` was unset in the ambient Bash environment, so it was set explicitly before constructing `Config`,
matching this file's own warning): `tool --colors $(echo x)` against a structured parser declaring `--colors` consumes
one argument, with `echo` allow-listed for the substitution check, denies via `UnknowablePathArgument('tool')`.
`_an_unknowable_argument_occupies_a_path_operand` needed no change.

### Observed during exploration

Recorded so they are not silently lost. **Default action for each is to leave it alone.**

- **`tests/test_allowed_command.py:62` uses a retired key incidentally.** Its subject is that `AllowedCommand` stores
  `commandParser` opaquely, and the dict content is arbitrary — so it is not load-bearing. It will however be asserting
  the storage of a config the engine would reject, which is cosmetically stale. Updating the fixture to the new shape is
  a one-line honesty fix, not a behaviour change; fold it in only if it stays that cheap.
- **`explain-policy` is still not allow-listed**, so `command-policy:find-auto-allowed-command` — the skill every deny
  reason points at — still dead-ends on its own first step. Unchanged since `20260919-112214` recorded it.
- **Redirecting to `/dev/null` is denied** (`redirect target outside the project/allowed prefixes`), which makes the
  reflexive `2>/dev/null` in an exploratory `grep` fail the whole command. Hit twice while exploring. Behaving as
  designed; noted because it costs a retry every time.
- **`improvement-plan-context` crashes on a long free-text argument** — `OSError: File name too long` from
  `resolve_improvement_file`. Already owned by the separate plan-skill argument-handling improvement
  (`20260919-230721`); hit again at the start of this session.

**Pattern-enforcement passes (Step 2.5/2.5b) were not run:** every affected file is Python, and the available enforcers
(`patterns:anti-pattern-detector`, `patterns:pattern-enforcer`, `patterns:react-anti-pattern-detector`) cover PHP and
React only. Recorded rather than silently skipped — same as `20260919-112214`.

## Test Architecture

**Existing helpers to reuse** (verified present, not quoted from a sibling improvement):

- `tests/test_permission_decisions.py:102` — `assert_decision(command, config, expected_decision)`, the decision-spec
  workhorse; returns the result for further reason inspection. `:97` `decision_for` for the `pytest.raises(ConfigError)`
  cases, which this improvement adds several of.
- `tests/test_permission_decisions.py:116` / `:128` — `assert_reason_includes` / `assert_primary_reason`, structural
  assertions over `Reason` value objects rather than substring matching on rendered prose. Every new deny case asserts
  at reason level, because a deny for the wrong reason (a missing parser, a rejected filter) looks identical otherwise —
  this trunk's own recorded trap.
- `tests/test_permission_decisions.py:78` / `conftest.py:150` — `assert_config_is_reachable`, which fails a case whose
  config no real `command-policy.json` could produce. Every new case inherits it through `decision_for`, and it is the
  guard that will catch a new-schema config written in a shape the engine would reject.
- `tests/test_permission_decisions.py:3058` — the `MATCHING_BRANCH_COVERAGE` manifest plus its two guard tests; new
  branches need entries or the guards fail.
- `tests/conftest.py:112` — `assert_migration_warns_about`, exactly the helper the two new `Warning` kinds need.
- `tests/conftest.py:79` — `cwd_pinned_inside_project(tmp_path)`, required by every containment case (it pins both the
  process cwd and `CLAUDE_PROJECT_DIR`).
- `tests/test_structured_parser.py:9` — the local `context(exists_predicate=None)` factory returning a
  `PathResolutionContext` with a fixed cwd, for unit-level parser assertions with no `Config` involved.

**New helpers to create:**

- A table-driven matrix over the SLOT KINDS × DECLARATION STATES — why_needed: the rule has one outcome per cell
  (positional/option-value/option-token × undeclared/declared-path/declared-non-path, each for a literal path, an
  in-project literal, and an unknowable value), and a hand-written case per cell invites silent gaps. The table makes a
  missing cell visible, the way the sibling improvement's matcher-type table did.
- A two-entry config factory yielding the SAME command against a default-parser entry and a structured-parser entry —
  why_needed: the headline defect is that attaching a structured parser is currently weaker than attaching none, and
  that is only expressible as a comparison. Pinning the pair prevents the two parsers silently diverging again.

**Fantasy callsites (test-facing API sketches):**

- `StructuredParser.from_definition({"options": [{"option": "--colors", "arguments": 1, "path": False}]}, context())`
- `StructuredParser.from_definition({"positionals": [{"index": 0, "path": False}]}, context())`
- `pytest.raises(ConfigError)` around `from_definition({"pathPositionals": [0]}, context())` — the retired-key rejection
- `parser.consumes_value_for_option("-m")` answering `False` for a declared bare flag and `True` for `arguments: 1`

**Testability-driven production decisions:**

- The new schema is parsed into declaration value objects ONCE in `from_definition` (a per-option record carrying its
  argument count and path-ness, a per-index record for positionals), so `parse` reads settled declarations rather than
  re-interpreting raw config dicts mid-parse, and a unit test can assert the parsed declarations directly instead of
  inferring them from `ParsedResult`.
- `paths_for_validation` and `paths_for_filtering` are built by two separately-named private methods, not one method
  with a mode flag — the whole reason `ParsedResult` split the fields is that the two answers diverge, and a shared
  method with a branch would be the first step back toward re-coupling them.

## Assumptions

Every claim below was settled by MEASUREMENT against the working tree at `8a1948b` — by running
`docs/improvements/experiments/20260920-131722/probe_structured_parser_today.py` (which drives
`Config.from_dict(...).decision_for(...)` and `StructuredParser` directly via `sys.path`, never the installed 0.3.0
plugin cache), by running the suites, or by reading the named file. Nothing here is inferred from whether one of this
session's own Bash calls was approved.

- **An unknowable value in an UNDECLARED structured slot escapes containment today** — confirmed (probe section A:
  `tool $(echo /etc/passwd)` against a `structured` parser declaring `{}` ALLOWs, while the same command against a
  parser declaring `pathPositionals: [0]` DENYs with `UnknowablePathArgument`)
- **The literal twin exists for `StructuredParser` too, with no substitution involved, and is wider than
  `DefaultParser`'s was** — confirmed (probe section B: `tool --colors=/etc/passwd` and `tool --colors /etc/passwd` both
  ALLOW with `--colors` declared as consuming an argument, and `tool --colors=/etc/passwd` ALLOWs against a parser
  declaring nothing)
- **Attaching a `structured` parser currently makes the engine WEAKER than attaching no parser at all** — confirmed
  (probe sections A/B vs E: all three of `tool $(echo /etc/passwd)`, `tool --colors=/etc/passwd`,
  `tool --colors /etc/passwd` DENY under the default parser and ALLOW under a structured one)
- **The `options` config key is in the decision specification's vocabulary but the engine never reads it** — confirmed
  (probe section C: a parser given `{"options": ["-v"]}` produces output identical to one given `{}`;
  `StructuredParser.from_definition` reads only
  `optionsWithArguments`/`doubleDashStops`/`pathOptions`/`pathPositionals`)
- **`pathOptions` naming an option absent from `optionsWithArguments` contributes no path candidate at all** — confirmed
  (probe section C: `{"pathOptions": ["-o"]}` with arguments `["-o", "out.txt"]` yields empty `paths_for_validation` and
  empty `paths_for_filtering`)
- **Dropping the shape heuristic from `paths_for_filtering` would fail OPEN for a `paths` filter** — confirmed (probe
  section D: `tool ./other-file.txt` against a structured entry with `{"type": "paths", "exactly": ["allowed.txt"]}`
  DENIES today via `FilterRejected(paths)`, and containment cannot catch it because the path is inside the project;
  `PathsFilter.matches` returns True for an empty `paths_for_filtering`, read at `lib/paths_filter.py:29-30`)
- **`_an_unknowable_argument_occupies_a_path_operand`'s marker probe is parser-agnostic and already works against
  `StructuredParser`, so containment needs no new wiring** — confirmed (probe section A row 2 denies via
  `UnknowablePathArgument`, which is only reachable through that probe)
- **Both operator configs declare zero structured parsers, so this change has no live false-denial cost** — confirmed
  (read `~/.claude/command-policy.json`: 59 entries, every non-default parser `type: "provided"`; and
  `.claude/command-policy.json`: 3 bare-string entries, no parsers at all)
- **`/command-policy:migrate-config` emits structured parsers, and currently passes `pathOptions`/`pathPositionals`
  through verbatim while renaming only the two snake_case keys** — confirmed (read `lib/config_migration.py:127-141`;
  pinned by `tests/test_config_migration.py:261`)
- **The old `shfmt-permissions` structured schema is `options_with_arguments` / `double_dash_stops` / `pathOptions` /
  `pathPositionals`, with no `options` key** — confirmed (read
  `packages/shfmt-permissions/scripts/analyze-bash-command.py:164-185`; the `options` key at line 374 there is parser
  OUTPUT shape, not config)
- **`commandParser` content is stored opaquely and is never validated at `Config.from_dict` time, so a retired-key
  rejection belongs in `StructuredParser.from_definition` and will surface from `decision_for`** — confirmed (read
  `lib/allowed_command.py:50-57` storing it as-is, and `lib/config.py`, whose only eager parser/filter work is
  `_collect_allowed_command_filter_warnings` for uncompilable patterns)
- **The `migrate-config` skill enumerates warnings and instructs which to surface loudly, so a new warning kind needs a
  line there** — confirmed (read `skills/migrate-config/SKILL.md` lines 26/32/36, which single out
  `dead_decision_knob_removed` and `propagate_reshaped_to_nested_command`)
- **The suite baseline is 737 passed / 0 failed (command-policy) and 751 passed (shfmt-permissions), with no sanctioned
  red** — confirmed (ran both: `cd packages/command-policy/tests && bypass-policy nix-shell --run "pytest -q"` reports
  737 passed in 6.88s; the same in `packages/shfmt-permissions/tests` reports 751 passed in 9.55s)

## Design Decisions

### Shape of the structured-parser declaration schema

- **Chosen:** Replace the four parallel keys (`options`, `optionsWithArguments`, `pathOptions`, `pathPositionals`) with
  one general per-slot declaration — an `options` list of `{option, arguments, path}` records and a `positionals` list
  of `{index, path}` records — with `arguments` defaulting to `0`, `path` defaulting to `true`, and a bare string item
  as shorthand for a valueless flag. `doubleDashStops` is untouched.
- **Rationale:** The operator's own words: "command-policy is a full rewrite to get rid of old cruft and this sounds
  like the superior way of declaring this config." The four keys describe one subject — a slot — from four directions,
  which is what let `pathOptions` name an option that consumes nothing and silently mean nothing at all.
- **Rejected alternatives:** Keep `pathOptions`/`pathPositionals` with their exact current meaning (feeding the precise
  filtering set) and add a `nonPathOptions`/`nonPathPositionals` complement for the opt-out — smallest change, no
  rewrite, and a stale config would get strictly MORE protection rather than less, but it keeps a slot's facts spread
  across four keys and preserves the inert-declaration trap. Retire the positive keys entirely in favour of a
  non-path-only complement — loses any way to name a precise "these slots are definitely paths" set, which collapses
  `paths_for_validation` and `paths_for_filtering` into one noisier set and degrades `PathsFilter`'s `exactly`
  semantics.
- **Date:** 2026-09-20

### The default when a slot is undeclared

- **Chosen:** PATH-ACTIVE. A slot nobody declared is a path candidate for validation; only an explicit `path: false`
  rules it out.
- **Rationale:** Operator decision, taken with the trade-off named: "not-a-path is more user friendly" was weighed
  against "keeping path active until actively disabled is the secure default" and the secure default won. It is also the
  only reading consistent with the rule `DefaultParser` already implements — if the engine cannot rule out that an
  argument is a path, it IS a path candidate — and with `hasNoPathParameters`' settled character as a TRUE factual claim
  rather than a waiver. A config author who declares nothing gets maximum strictness; every relaxation is an explicit,
  auditable, falsifiable statement.
- **Rejected alternatives:** Default `path: false` for slots the author did not mention (friendlier, and it would keep
  every existing config's verdicts stable — but it re-creates the exemption this improvement exists to remove, and makes
  silence a grant); keep the shape heuristic as the default for undeclared slots (the status quo, which measurement
  shows is weaker than having no parser at all).
- **Date:** 2026-09-20

### What happens to a config still carrying a retired key

- **Chosen:** `ConfigError` from `StructuredParser.from_definition`, naming the replacement — raised at `decision_for`
  time against an actually-matching entry, not eagerly at `Config.from_dict`.
- **Rationale:** Silently ignoring `optionsWithArguments` would change TOKENIZATION (an option's value becomes a stray
  positional and every later index shifts), and silently ignoring `pathOptions`/`pathPositionals` would leave an author
  believing they declared something — both are the "config no author could have meant" class the load-time rejection
  doctrine exists for. The match-time placement matches the established split rather than inventing a new one. Zero live
  configs use a structured parser, so the blast radius of failing loudly is nil; the cost lands only on someone who
  writes the old shape from stale documentation, which is exactly who should be stopped.
- **Rejected alternatives:** Accept the old keys as aliases (preserves a schema this rewrite exists to shed, and makes
  the misleading reading of `pathPositionals` permanently available); ignore them silently (the fail-open direction);
  accept-and-warn via `Config.warnings()` (a warning is not read by anyone at decision time, so the author's broken
  declaration would still be in force)
- **Date:** 2026-09-20

### Value-consuming and path-ness: one declaration or two

- **Chosen:** One. An option's argument count and its value's path-ness live on the same record.
- **Rationale:** They are two facts about the same slot, and separating them is what produced the measured silent no-op
  (`pathOptions` naming an option that consumes nothing contributes no candidate at all). It also satisfies the
  project-wide rule that configuration is defined in ONE place. The value-consumption fact is load-bearing twice over —
  once to tokenize correctly, once to know what the path candidate even is — which argues for keeping it adjacent to the
  classification rather than in a parallel list.
- **Rejected alternatives:** Keep `optionsWithArguments` as-is and add a parallel `nonPathOptions` list, with new
  validation rejecting an entry naming an option absent from `optionsWithArguments` — less rewrite, but preserves the
  two-places-per-option duplication and needs the extra cross-list validation precisely because the duplication is
  unsafe
- **Date:** 2026-09-20

### Whether a bare valueless flag's own token is a path candidate

- **Chosen:** Yes — mirror `DefaultParser` exactly. Every option token is a validation candidate (split on `=` so a
  joined form contributes its value alone), declared or not.
- **Rationale:** Keeps the two pure parsers' behaviour identical for the same input, so there is no edge where the more
  knowledgeable parser is quietly more permissive — which is the whole defect being fixed. The cost is nil: a token
  resolves project-relative and stays contained, so it can never manufacture a denial; declaring a flag is therefore
  optional, never required.
- **Rejected alternatives:** Exempt option tokens on the grounds that an option name is syntax from a finite vocabulary
  rather than runtime data — a defensible and slightly cleaner mental model, but it puts `StructuredParser` and
  `DefaultParser` on different answers for one identical input, and this improvement exists to remove exactly that kind
  of divergence
- **Date:** 2026-09-20

### Keeping the shape heuristic for `paths_for_filtering`

- **Chosen:** Keep `_detect_path_heuristic`, scoped strictly to `paths_for_filtering`; `paths_for_validation` never
  consults it again.
- **Rationale:** Measured fail-open if removed: a structured entry with a `paths` filter currently DENIES
  `tool ./other-file.txt`, and containment cannot substitute for it because the path is inside the project, so dropping
  the heuristic silently converts that DENY into an ALLOW. The split exists for exactly this reason — validation wants
  every candidate it cannot rule out (a surplus entry is a spare check), while filtering feeds `exactly` set-membership
  (a surplus entry is a wrong member). Confining a guess to the field where it cannot manufacture an exemption is the
  same trade `DefaultParser` already makes.
- **Rejected alternatives:** Delete the heuristic entirely for consistency with "declarations, not guesses" (fail-open,
  measured); widen `paths_for_filtering` to match validation (breaks `exactly` semantics with wrong members, the
  divergence `ParsedResult` split the fields to prevent)
- **Date:** 2026-09-20

### How migration translates an old structured parser

- **Chosen:** A structural reshape into the new schema, writing `path: true` EXPLICITLY for every former
  `pathOptions`/`pathPositionals` member, plus two new `Warning` kinds — one fired unconditionally for every migrated
  structured parser (the path-active default change), one fired when `pathOptions` named an option that consumed
  nothing.
- **Rationale:** The migrated config is materially stricter than its source — slots the old engine guessed as non-paths
  become candidates — and the user is affected whether or not they notice, which is the same test
  `dead_decision_knob_removed` already applies for firing unconditionally. Writing `path: true` explicitly preserves the
  author's original assertion as an assertion instead of dissolving it into a default that happens to agree today. The
  inert-`pathOptions` warning reports a declaration the old author believed in and measurably never got.
- **Rejected alternatives:** Reshape silently, as the current camelCase normalisation does (the knowledgebase's own
  reasoning for silence — "there is nothing to warn about beyond what the diff already shows" — stops being true once
  the semantics flip); leave migration emitting the old keys and let the engine reject them (hands the user a config
  their own engine refuses); infer an `arguments: 1` count for an inert `pathOptions` entry (invents a fact the source
  config never asserted)
- **Date:** 2026-09-20

### Version bump: MINOR, not PATCH

- **Chosen:** `0.4.1` → `0.5.0` for `packages/command-policy/.claude-plugin/plugin.json` and its root
  `.claude-plugin/marketplace.json` mirror.
- **Rationale:** The precedent set by improvement `20260919-112214` (the closely analogous `DefaultParser`
  total-candidacy change) was PATCH (`0.3.1` → `0.3.3`), but that change altered runtime behaviour with NO config schema
  change - no key was added, removed, or reinterpreted. This improvement retires THREE config keys
  (`optionsWithArguments`, `pathOptions`, `pathPositionals`) outright - a config that used any of them now raises
  `ConfigError` instead of loading - and replaces them with a new `options`/`positionals` per-slot schema. That is a
  breaking change to the `commandParser.structured` config surface, which this project's 0.x versioning treats as
  MINOR-worthy even though live exposure is zero (both operator configs declare no structured parsers today).
- **Rejected alternatives:** PATCH, matching the `20260919-112214` precedent - rejected because that precedent's
  justification (no schema change) does not hold here; a schema-breaking change should not hide behind a patch-level
  version number even when nothing live is affected today.
- **Date:** 2026-09-20

## Success Criteria

Each of these is a measured verdict against `Config.from_dict(...).decision_for(...)` driving the working tree's `lib/`,
not a description of code that exists.

- [x] The three shapes that currently ALLOW under a `structured` parser and DENY under no parser at all now DENY under
      both: `tool $(echo /etc/passwd)` (parser declaring `{}`), `tool --colors=/etc/passwd` and
      `tool --colors /etc/passwd` (parser declaring `--colors` as consuming one argument)
- [x] For every one of those three, the default-parser entry and the structured-parser entry reach the SAME verdict —
      pinned as an explicit pair, so "the more knowledgeable parser is more permissive" cannot silently return
- [x] A declared non-path slot earns its exemption in both directions: with
      `positionals: [{"index": 0, "path": false}]`, `tool $(echo anything)` ALLOWs, and with
      `options: [{"option": "--colors", "arguments": 1, "path": false}]`, `tool --colors $(echo anything)` ALLOWs —
      while the SAME parser still DENIES an unknowable value in a slot it did not rule out
- [x] `--colors=/etc/passwd` contributes `/etc/passwd` as the candidate, never `<project>/--colors=/etc/passwd` —
      asserted on the resolved path, so the "buried under the project root and reads as contained" failure is
      structurally excluded rather than merely absent
- [x] An undeclared bare flag (`tool --verbose plain`) still ALLOWs: its token becomes a project-relative, contained
      candidate, so declaring valueless flags is optional and never required to avoid a denial
- [x] `consumes_value_for_option` answers `False` for a declared bare flag (`{"option": "-m"}`) and `True` for
      `{"option": "-m", "arguments": 1}`, and the four `optionValue` capability cases in the decision specification are
      rewritten onto the new schema so case 3 fails for the reason its docstring claims rather than because the option
      was absent from a list
- [x] Each of `optionsWithArguments`, `pathOptions`, `pathPositionals` raises `ConfigError` naming its replacement, and
      a bare-string `options` item still means a valueless flag
- [x] `paths_for_filtering` is unchanged for every shape that does not involve a `path: false` declaration —
      specifically, the structured entry with `{"type": "paths", "exactly": ["allowed.txt"]}` still DENIES
      `tool ./other-file.txt` via `FilterRejected(paths)`
- [x] Migrating an old `shfmt-permissions` structured parser produces the new per-slot shape with `path: true` written
      explicitly for every former `pathOptions`/`pathPositionals` member, and fires
      `structured_parser_defaults_to_path_active` unconditionally plus `structured_parser_inert_path_option` when
      `pathOptions` named an option absent from `options_with_arguments`
- [x] `skills/migrate-config/SKILL.md` instructs surfacing the path-active default warning with the same prominence it
      already gives `dead_decision_knob_removed`
- [x] Every new test was run against pre-change code and observed to FAIL for the right reason; the red counts are
      recorded in the implementation notes
- [x] `packages/command-policy/tests` is green with ZERO failures (baseline 737 passed, measured) and
      `packages/shfmt-permissions/tests` is unchanged at 751 passed
- [x] `docs/knowledgebase/command-policy-decision-model.md` describes the engine that now exists — the five passages
      named in Implementation Notes are CONVERTED, not appended to, and the article carries no "currently only the
      default parser" framing and no reference to this improvement as a tracker

## Implementation TODO

- [x] Update status to in-progress
- [x] Confirm the starting baseline: `cd packages/command-policy/tests && bypass-policy nix-shell --run "pytest -q"`
      reports 737 passed 0 failed, and `packages/shfmt-permissions/tests` reports 751 passed (plain `nix-shell` is
      denied; see Implementation Notes)
- [x] Re-read `lib/default_parser.py` as it actually stands and confirm it still matches what this plan mirrors
      (`_path_operand_of`'s `=` split, `_every_argument_as_a_path_candidate`'s empty-argument exclusion, the
      validation/filtering divergence); if improvement `20260919-112214` was reopened again and the shape moved, mirror
      what is there and note the divergence rather than this plan's description
- [x] RED: add the headline comparison cases to the decision specification — the same three commands
      (`tool $(echo /etc/passwd)`, `tool --colors=/etc/passwd`, `tool --colors /etc/passwd`) against a default-parser
      entry and a structured-parser entry, asserting the SAME verdict for both at `Reason` level; confirm the structured
      half fails pre-change and the default half already passes
- [x] RED: add the declared-exemption cases (`path: false` on a positional and on an option's value earn an unknowable
      value; the same parser still denies a slot it did not rule out) and confirm they fail pre-change because the new
      schema keys are not read at all
- [x] RED: add the joined-form candidate case asserting the resolved path is `/etc/passwd`, not
      `<project>/--colors=/etc/passwd`; confirm it fails pre-change
- [x] RED: add the retired-key rejection cases (`optionsWithArguments`, `pathOptions`, `pathPositionals` each raising
      `ConfigError`) and the bare-string-shorthand case; confirm each fails pre-change
- [x] RED: add the regression guards that must STAY green — `tool --verbose plain` still ALLOWs (bare flag token is
      contained), and the `paths` filter entry still DENIES `tool ./other-file.txt` via `FilterRejected(paths)`; confirm
      both already pass pre-change so they are genuine guards rather than new behaviour
- [x] Parse the new schema into declaration value objects in `StructuredParser.from_definition`, raising `ConfigError`
      for each retired key, and unit-test the declarations directly
- [x] GREEN: rewrite `_detect_paths` into two separately-named builders — validation (every slot not declared
      `path: false`, option tokens included, `=`-split, empty and the consumed `--` excluded) and filtering (declared
      path slots plus `_detect_path_heuristic` over undeclared positionals only)
- [x] GREEN: make `consumes_value_for_option` answer from the declaration's `arguments` count, and rewrite the four
      `optionValue` capability cases in the decision specification onto the new schema — verify case 3 is non-vacuous by
      temporarily making the check lenient and watching it go green when it should not
- [x] Confirm by measurement that `_an_unknowable_argument_occupies_a_path_operand` needs no change: the separated form
      `tool --colors $(echo x)` must deny via `UnknowablePathArgument`, which only the marker probe can produce
- [x] Reshape `config_migration._migrate_command_parser` into the new schema, writing `path: true` explicitly for every
      former `pathOptions`/`pathPositionals` member, and add the two `Warning` classmethods in `lib/warning_value.py`
- [x] Update `tests/test_config_migration.py`'s camelCase-normalisation case (line 261) to the reshape, and cover both
      new warnings via `assert_migration_warns_about`
- [x] Update `skills/migrate-config/SKILL.md` so the path-active default warning is surfaced with the same prominence as
      `dead_decision_knob_removed`
- [x] Adjudicate IN WRITING every existing test whose meaning legitimately changes (at minimum
      `test_an_unconfigured_positional_still_uses_heuristic_path_detection`, the `pathOptions`/`pathPositionals` unit
      cases, and `tests/test_allowed_command.py:62`'s incidental fixture) — rewrite each to pin what is now true, and
      add no declaration merely to keep a test green
- [x] REFACTOR: review the new declaration objects and the two path builders against the Yes/No clarity test, and fold
      the module docstring's rationale into names wherever a name can carry it
- [x] Add `MATCHING_BRANCH_COVERAGE` entries for every new branch and confirm the two manifest guard tests stay green
- [x] Run both suites: `packages/command-policy/tests` green with ZERO failures, `packages/shfmt-permissions/tests`
      unchanged at 751 passed
- [x] Re-run `docs/improvements/experiments/20260920-131722/probe_structured_parser_today.py` and record the
      before/after verdict table in this file, then delete the probe directory
- [x] Update `docs/knowledgebase/command-policy-decision-model.md` by CONVERTING the five passages named in
      Implementation Notes — the parser-produces-what-filters-see paragraph, the total-candidacy passage, the three ways
      to earn unknowable content, the `ParsedResult` divergence paragraph, and the migration translation bullet
- [x] Confirm the updated article reads timelessly: it should describe a three-rung ladder in which declared knowledge
      rules slots out, with no "currently only the default parser" framing and no reference to this improvement
- [x] Bump `packages/command-policy/.claude-plugin/plugin.json` and the root `.claude-plugin/marketplace.json` entry in
      lockstep so the operator's plugin cache picks the change up
- [x] Update status to completed

## Related Past Improvements

- improvement-20260919-112214: introduced the per-argument path-candidacy rule for `DefaultParser` that this improvement
  now extends to `StructuredParser`; this improvement's `Depends on` Meta line points to it.
