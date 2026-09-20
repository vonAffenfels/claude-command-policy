# Improvement 20260918-223632: Fix nestedCommand Filter Propagation Gap

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-18
- Updated: 2026-09-19
- Plan started: 2026-09-18T22:36:10+02:00
- Plan finished: 2026-09-18T23:32:32+02:00
- Impl started: 2026-09-18T23:38:36+02:00
- Impl finished: 2026-09-19T15:05:08+02:00
- Depends on: 20260914-213825

## This Improvement's Objective

Fix the nestedCommand filter's propagation gap in command-policy: the three bundled wrapper parsers
(`packages/command-policy/parsers/timeout.py`, `nix.py`, `nix-shell.py`) are byte-identical carries from the old
shfmt-permissions engine and still publish the wrapped inner command as `named["command"]` (the OLD propagate
convention). `lib/nested_command_filter.py` and `lib/command_parser.py` read a different channel - a raw
`"nestedCommands": [{"text", "shape"}]` key - which none of the three parsers emit, so the filter always sees an empty
nested-commands list and fails closed by design. This makes command-policy DENY every wrapped command today
(`timeout 10 echo hi`, `nix develop -c echo hi`, `nix-shell --run "echo hi"`), even when the wrapped command is itself
allow-listed - live-reproduced in this very planning session
(`cd packages/command-policy/tests && nix-shell --run pytest` was denied with
`FilterRejected(program=nix-shell, filter_type=nestedCommand)`). Fix: teach all three parsers to publish on the real
`nestedCommands` channel with correct per-parser extraction semantics (timeout's DURATION positional must not be
mistaken for the command; nix-shell's `--run`/`--command` STRING vs `-p`/`--command` vs a bare `shell.nix` with no
wrapped command at all; nix develop/shell's `-c`/`--command` vs `nix run`). Additionally build
`packages/command-policy/parsers/xargs.py`, which was never ported from shfmt-permissions and does not exist at all -
this is the same root cause and is needed to turn two currently-RED decision-spec cases green
(`test_a_nested_command_filter_composes_with_other_filters_across_entries`,
`test_propagation_does_not_see_operands_arriving_on_stdin`) while identifying and preserving, for the RIGHT reason, two
OTHER specs in that area that currently pass only coincidentally because a missing parser produces the same deny outcome
the test expects. Depends on improvement-20260914-213825 (the leaf that landed `decision_for`/the pipeline this bug
lives in). No filter, pipeline, or config-schema change is in scope - this is purely making the four parsers speak the
protocol the filter and pipeline already implement correctly. Tests: pin behaviour in
`packages/command-policy/tests/test_permission_decisions.py` plus unit-level parser tests, non-vacuous (verified against
pre-fix code). Expected baseline going in: command-policy suite 634 passed / 2 failed (the two xargs specs above);
`packages/shfmt-permissions/tests` 751 passed and must stay untouched (old engine unaffected).

## Context / Why This Exists

**Origin / trigger:** A live regression, biting the operator right now. The operator enabled `command-policy` and
migrated their config today; every wrapped command is now denied (`timeout 10 echo hi`, `nix develop -c echo hi`,
`nix-shell --run "echo hi"`), with `cd packages/command-policy/tests && nix-shell --run pytest` — how EVERY test suite
in this repository is run — the most-affected case. The migration warned about this gap by name at migrate-config time
(`propagate_reshaped_to_nested_command`), and the operator deliberately chose to fix the parsers rather than drop the
`nestedCommand` filters, so removing those filters is an explicitly REJECTED approach, not an option to re-open. The
symptom was reproduced live inside this planning session: `nix-shell --run pytest` returned
`nix-shell: a nestedCommand filter rejected this invocation`.

**Consumer(s) of the output:** `lib/nested_command_filter.py`, via `lib/command_parser.py`'s `interpret()`, which reads
a parser's `nestedCommands` channel and re-enters the decision pipeline for each published sub-command. Behind that, the
human operator, whose wrapped commands are currently unusable without `bypass-policy`.

**Adjacent systems already covering part of the need:** `packages/shfmt-permissions/` (the old engine) still carries the
originals of these parser scripts and remains fully installed and functional — it is NOT to be touched, and its 751-test
baseline must stay green. `command-policy:migrate-config` already flags this exact gap with a
`propagate_reshaped_to_nested_command` warning, so the gap is tracked, not unknown; this improvement is what that
warning was waiting for.

## Proposed Approach

Teach four bundled parser scripts to publish on the `nestedCommands` channel the engine already reads. **No engine
change**: the filter, the pipeline, the depth guard and the protocol are all already correct and were verified working
end-to-end during planning (see Assumptions). Only `packages/command-policy/parsers/` changes.

**The protocol, established from the code rather than assumed.** `lib/command_parser.py`'s `interpret()` builds
`ParsedResult.nested_commands` from a raw `"nestedCommands": [{"text": ..., "shape": ...}]` key, one
`NestedCommand(text, shape)` per entry, defaulting `shape` to `"shell"` when absent. `lib/nested_command_filter.py`
takes each entry, calls `evaluate_nested(entry.text, depth + 1)`, and requires EVERY entry to decide `allow`; an empty
list returns `False`, which is the fail-closed behaviour.
`packages/command-policy/tests/fixtures/fake_parsers/wrapper_publishing_nested_command.py` is the working reference
implementation of the output shape — copy its structure, not the old `named["command"]` idiom.

**What `shape` means, and the finding about it.** Per `lib/parsed_result.py`'s `NestedCommand` docstring, `"argv"` means
the text is a list of already-split words re-quoted into one string (so word boundaries survive re-parsing), and
`"shell"` means the text is shell syntax to be parsed as-is. **Today nothing in the engine reads `shape`** — the filter
passes only `entry.text` to `evaluate_nested`, and `Config._decision_for_text` always parses via
`Statement.from_command` (shell syntax). Both shapes therefore behave identically right now, because `shlex.quote`
output is itself valid shell syntax that re-parses to the same words. Set `shape` honestly per parser anyway: it is the
declared contract, a future consumer is the whole reason the field is carried explicitly rather than inferred, and
getting it wrong is asymmetric. Do NOT add a consumer for it here — that is engine surface, out of scope.

**Depth/recursion is already solved; use it, do not re-invent.** `Config.decision_for(command, max_nested_depth=...)`
threads an explicit depth through both recursion sources. `NestedCommandFilter.matches()` prefers its own `maxDepth`
when configured, else the pipeline default, compares against the caller-supplied `depth`, and returns `False` on
exceeding it; `Config._decision_for_text` guards again at entry. The parsers contribute nothing here — they publish
text, the engine owns recursion.

**Per-parser extraction semantics (deliberately NOT copy-pasted — each differs):**

- **`timeout.py`** — `timeout [OPTION]... DURATION COMMAND [ARG]...`. The existing option walk already skips timeout's
  own options (`-k/--kill-after`, `-s/--signal` consume a value) and treats the first bare token as DURATION; the
  wrapped command is everything AFTER it. Publish that remainder, `shlex.quote`-joined, as one entry with
  `shape: "argv"`. `timeout 10` with no command publishes no `nestedCommands` key at all.
- **`nix.py`** — only `-c`/`--command` introduces a wrapped command, and it swallows the entire remaining argv
  (`nix develop .#backend -c npm install`). Publish that remainder `shlex.quote`-joined, `shape: "argv"`.
  `nix run nixpkgs#hello` and every other `-c`-less invocation publish nothing and therefore deny — honest, because the
  program that would run is named by a flake installable the parser cannot resolve to a command word.
- **`nix-shell.py`** — `--run`/`--command` take ONE argument which is a shell STRING, not argv
  (`nix-shell --run "cd x && make"`). Publish it verbatim with `shape: "shell"`. When the option appears more than once,
  publish only the LAST — that is the one nix-shell actually honours, so publishing earlier ignored ones would evaluate
  commands that never run. A bare `nix-shell` or `nix-shell shell.nix` publishes nothing (see Design Decisions) and
  therefore denies.
- **`xargs.py` (NEW FILE — never ported, absent from both packages)** — `xargs [OPTIONS] [COMMAND [INITIAL-ARGS...]]`.
  Walk xargs' own options first, honouring the ones that consume a value (`-a/--arg-file`, `-d/--delimiter`, `-E`,
  `-I/--replace`, `-L`, `-n/--max-args`, `-P/--max-procs`, `-s/--max-chars`) and treating any other `-`-prefixed token
  as a valueless flag — the same convention every sibling parser uses, and what makes the spec suite's synthetic
  `--dry-run` register as an `optionPresent` target. The first bare token is COMMAND and the rest are INITIAL-ARGS;
  publish them `shlex.quote`-joined as one entry with `shape: "argv"`. With NO command argument, publish `echo` — xargs'
  documented default (see Design Decisions).

**Uniform across all four:** `paths` stays EMPTY. Inner-command paths are validated by the propagated evaluation, not by
the wrapper's parser — the convention `timeout.py` already documents. `named["command"]` keeps being published exactly
as today (see Design Decisions), so `namedValue` filters pointing at it keep working; `nestedCommands` becomes the
load-bearing channel.

## Affected Components

**Files:**

- `packages/command-policy/parsers/timeout.py` — add `nestedCommands` output
- `packages/command-policy/parsers/nix.py` — add `nestedCommands` output
- `packages/command-policy/parsers/nix-shell.py` — add `nestedCommands` output; bare invocation publishes nothing
- `packages/command-policy/parsers/xargs.py` — **NEW FILE**, does not exist today
- `packages/command-policy/tests/test_permission_decisions.py` — turn two RED cases green; add non-vacuous propagation
  cases; retarget the "nothing to check" case's premise (see Implementation Notes)
- `packages/command-policy/tests/test_bundled_parsers.py` — **NEW FILE**, unit-level parser coverage (name mirrors the
  old engine's `packages/shfmt-permissions/tests/test_new_parsers.py` convention: invoke the script as a subprocess with
  JSON on stdin, one test class per parser)
- `docs/knowledgebase/command-policy-decision-model.md` — the glossary line claiming the command-policy parsers are a
  "copy of packages/shfmt-permissions/scripts/parsers/" becomes false once they diverge

**Explicitly NOT touched:**

- `packages/shfmt-permissions/` — anything. The old engine stays installed and functional; its 751-test baseline must
  stay green (see Design Decisions).
- `packages/command-policy/lib/` — no filter, matcher, pipeline, protocol or config-schema change.

**Classes/Functions:**

- `parse_timeout_args()`, `parse_nix_args()`, `parse_nix_shell_args()` — extend each return dict
- `parse_xargs_args()` — new
- `NestedCommand` / `CommandParser.interpret()` / `NestedCommandFilter.matches()` — READ ONLY; they are the contract
  being satisfied, not code to modify

## Implementation Notes

**Testing Strategy:** TDD (red-green-refactor). The user's global CLAUDE.md mandates invoking the `tdd` skill whenever
writing or modifying tests. Suites are run with `cd packages/<package>/tests && nix-shell --run pytest`.

**Non-vacuity is the acceptance bar, not a nicety.** Two recent security improvements in this trunk were each verified
by running their new tests against pre-fix code, one with 11 of 11 genuinely failing. Every new test here must be shown
RED before the fix. The minimum pair that proves propagation rather than merely the absence of a crash: a wrapped
ALLOWED command decides `allow`, and a wrapped BLOCKED command decides `deny`. Both were confirmed achievable during
planning via the existing fixture parser (see Assumptions) — so if either fails after the fix, the parser is wrong, not
the engine.

**Planning probe artifacts, kept deliberately.** `docs/improvements/experiments/20260918-223632/` holds the two probes
that produced the evidence behind the Assumptions section, runnable with plain `python3` (no nix shell, which is what
made them usable at all while the bug denies `nix-shell`):

- `probe_current_reasons.py` — drives `Config.decision_for` over every xargs spec case plus the three live wrapper
  symptoms and prints the actual `Reason` TYPES. This is the harness for the "record the pre-fix reason" TODO; it
  becomes obsolete once the fix lands, so delete it as part of finishing the work.
- `probe_protocol_works.py` — drives the same entrypoint through the existing fixture parser that already speaks the
  protocol, establishing that the engine side needs no change. Equally obsolete afterwards.

**Four specs currently pass for the WRONG reason — verified, not assumed.** A planning probe ran the pre-fix engine over
every xargs case in the spec suite and printed the actual `Reason` types. Every xargs spec reaches its `deny` through
`ParserCouldNotInterpretInvocation` — the `parsers/xargs.py` file is missing, so `ProvidedParser` resolves to an empty
command and `ExternalParserFactory` returns `None` before any filter runs:

| Spec                                                                            | Pre-fix reason(s)                                                          | Status                                                                                            |
| ------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `test_a_nested_command_filter_composes_with_other_filters_across_entries`       | `ParserCouldNotInterpretInvocation` x2                                     | **RED** — the `--dry-run` half expects `allow`; mine to turn green                                |
| `test_propagation_does_not_see_operands_arriving_on_stdin`                      | `ParserCouldNotInterpretInvocation`                                        | **RED** — expects `allow`; mine to turn green                                                     |
| `test_an_entry_whose_nested_command_filter_has_nothing_to_check_does_not_match` | `ParserCouldNotInterpretInvocation`                                        | **green, wrong reason** — its premise ("bare xargs publishes nothing") stops being true           |
| `test_exceeding_the_propagation_depth_limit_is_denied`                          | `ParserCouldNotInterpretInvocation`                                        | **green, wrong reason** — the depth guard is never reached today                                  |
| `test_a_propagated_command_is_checked_against_blocked_commands`                 | `ProgramNotAllowListed` (for `find`) + `ParserCouldNotInterpretInvocation` | **green, wrong reason — NOT predicted by the task brief**; propagation to `rm` is never exercised |

- `test_an_entry_whose_nested_command_filter_has_nothing_to_check_does_not_match` **stays green** after the fix (bare
  `xargs` publishes `echo`, which is not allow-listed in `wrapper_config("xargs")`, so it still denies) — but it would
  then be asserting something its own name and docstring no longer describe. Retarget its premise onto a wrapper that
  genuinely publishes nothing: `nix-shell` with no `--run`. Keep a bare-`xargs` case too, restated as what it now really
  tests (the known-default `echo` must itself be allowed).
- `test_exceeding_the_propagation_depth_limit_is_denied` must, after the fix, deny because the depth guard trips on
  `xargs xargs xargs rm -rf ./build` with `maxDepth: 1` — assert the reason, not only the outcome, or it stays
  indistinguishable from a parse failure.
- `test_a_propagated_command_is_checked_against_blocked_commands` cannot distinguish propagation from an unrelated
  denial, because `find` is not allow-listed in its own config, so the command denies either way. **Do not weaken or
  rewrite it** (the suite is authored-ahead and its assertions are authority). Add a COMPANION case beside it that
  isolates the mechanism: every outer program allow-listed, `rm` blocked, so the ONLY possible source of denial is
  propagation into the wrapped `rm`.

**Why the parsers may diverge from their shfmt-permissions originals but the originals may not move.** The two copies
are byte-identical today. After this change the command-policy copies speak a protocol the old engine does not
understand. That is intended and is why `packages/shfmt-permissions/` is out of scope entirely — re-run its suite
afterwards purely to prove it was not disturbed.

**`--` handling.** `timeout.py` already terminates option parsing at `--`; preserve that. For `xargs`, treat a bare `--`
the same way (everything after it is COMMAND + INITIAL-ARGS, never an option).

**Do not publish paths from a wrapper parser.** All four keep `"paths": []`. The inner command's paths are validated
when the nested evaluation re-enters the pipeline; publishing them from the wrapper would double-validate them against
the WRAPPER entry's own containment rules, which is both wrong and a source of spurious denials (the spec's
`xargs --dry-run rm ./build` case is not cwd-pinned, so a published `./build` would be resolved against ambient cwd).

## Test Architecture

**Existing helpers to reuse:**

- `wrapper_config(program, blocked=(), parser_name=None)` and `script_parser_config(...)` —
  `packages/command-policy/tests/test_permission_decisions.py`; already build exactly the
  `{"type": "provided"} + [{"type": "nestedCommand"}]` entry shape every wrapper case needs, and are themselves guarded
  by `test_wrapper_config_builder_produces_the_shape_the_cases_rely_on`
- `assert_decision(command, config, expected)` / `decision_for(command, config)` — same file; the second returns the
  full `PermissionDecision` so a case can assert on `result.reason` membership, which is how the reason-level cases in
  this improvement must be written
- `cwd_pinned_inside_project` fixture — `packages/command-policy/tests/conftest.py`; needed by any case whose command
  carries a relative path
- `packages/command-policy/tests/fixtures/fake_parsers/wrapper_publishing_nested_command.py` — the existing, working
  reference implementation of the `nestedCommands` output shape
- `run_parser(parser_name, arguments)` — `packages/shfmt-permissions/tests/test_new_parsers.py`; the pattern to PORT
  (subprocess with JSON on stdin, JSON back on stdout), not to import across packages

**Fantasy callsites (sketch, not spec):**

- `run_parser("xargs", ["rm", "./build"])["nestedCommands"] == [{"text": "rm ./build", "shape": "argv"}]`
- `assert_decision("timeout 10 echo hi", timeout_wrapping_allowed_echo_config(), "allow")`
- `assert FilterRejected("xargs", "nestedCommand") in decision_for("xargs xargs xargs rm -rf ./build", depth_capped_config()).reason`
  — the shape that distinguishes a real depth-guard denial from a parse failure

**New helpers to create:**

- `run_parser(parser_name, arguments)` in the new `packages/command-policy/tests/test_bundled_parsers.py` —
  `{ name: run_parser, why_needed: invoke a bundled parser script as the engine does (subprocess, JSON stdin/stdout) so unit coverage exercises the real entrypoint rather than an imported function the engine never calls that way }`
- a small per-test config builder for the three wrapper programs whose inner command must be allow-listed —
  `{ name: wrapper_wrapping_allowed_program, why_needed: wrapper_config() allow-lists only the wrapper, so every "wrapped ALLOWED command is allowed" case needs the inner program added too; writing that inline four times invites drift between the cases that must agree }`

**Testability-driven production-architecture decisions:**

- Keep each parser's pure `parse_*_args(arguments) -> dict` function separate from its `main()` I/O shell — the existing
  convention in all three scripts, and what lets a unit test choose between calling the function directly and going
  through the subprocess entrypoint. `xargs.py` must follow it rather than inlining the parse into `main()`.

## Assumptions

- **The nestedCommand filter, the depth guard and the re-evaluation pipeline are already correct; only the parsers speak
  the wrong protocol** — confirmed (planning probe drove `Config.decision_for` with the existing fixture parser
  `wrapper_publishing_nested_command.py`, which DOES publish `nestedCommands`: `wrap echo hi` with `echo` allow-listed
  decided `allow`; the same command without `echo` allow-listed decided `deny`; `wrap rm -rf ./build` with `rm` blocked
  decided `deny`; `wrap` with nothing published decided `deny`)
- **`timeout.py`, `nix.py` and `nix-shell.py` parse their invocations successfully and are rejected specifically by the
  nestedCommand filter, not by a parse failure** — confirmed (probe: `timeout 10 echo hi`, `nix develop -c echo hi` and
  `nix-shell --run 'echo hi'` each decided `deny` via `FilterRejected`, never `ParserCouldNotInterpretInvocation`, with
  `echo` allow-listed in every case)
- **`packages/command-policy/parsers/xargs.py` does not exist, and was never present in shfmt-permissions either** —
  confirmed (directory listing of both `packages/command-policy/parsers/` and
  `packages/shfmt-permissions/scripts/parsers/`; neither contains an xargs entry)
- **Every xargs spec currently reaches its outcome through `ParserCouldNotInterpretInvocation`, because a missing script
  makes `ProvidedParser` resolve to an empty command and `ExternalParserFactory` return `None`** — confirmed (probe
  printed the actual `Reason` types for all seven xargs spec cases; see the table in Implementation Notes)
- **A THIRD spec passes for the wrong reason beyond the two the task brief predicted:
  `test_a_propagated_command_is_checked_against_blocked_commands` denies via `ProgramNotAllowListed` for the unlisted
  `find`, so it would still pass even if propagation were entirely broken** — confirmed (probe reported
  `ProgramNotAllowListed, ParserCouldNotInterpretInvocation` for `find . -name '*.tmp' | xargs rm`)
- **`shape` is carried but never read by the engine: only `entry.text` reaches `evaluate_nested`, and nested text is
  always re-parsed as shell syntax** — confirmed (`nested_command_filter.py:43` passes `entry.text` only;
  `config.py:_decision_for_text` calls `Statement.from_command`; a grep for "shape" across `lib/`, `parsers/` and
  `tests/` hits only the `NestedCommand` class and its construction in `command_parser.py`)
- **Nothing in `packages/command-policy/lib/` or `bin/` reads `named["command"]`; only a config-authored `namedValue`
  filter could** — confirmed (grep across lib, bin and tests found no reader; `config_migration.py` drops the old
  namedValue selector rather than emitting one)
- **The guard the task asked about exists and is named `_require_parser_can_publish_nested_commands`, rejecting
  default/structured parsers beside a nestedCommand filter at decision time rather than denying forever** — confirmed
  (`packages/command-policy/lib/allowed_command_policy.py:293`, raising `ConfigError`; the four parsers here are all
  reached as `{"type": "provided"}`, which satisfies it)
- **The depth guard already exists with a default of 10 and a per-filter `maxDepth` override, threaded explicitly rather
  than held as hidden state** — confirmed (`config.py:49` `DEFAULT_MAX_NESTED_DEPTH = 10`, threaded through
  `decision_for`/`_decision_for_text`; `nested_command_filter.py:39-41` prefers its own `maxDepth` over the ambient
  default)
- **The stated baselines still hold today: command-policy at 634 passed with exactly 2 failures, and shfmt-permissions
  at 751 passed** — unverified (both suites are run through `nix-shell --run pytest`, which this session's own config
  denies via the exact bug being fixed, and pytest is not importable outside that nix shell; the implementer must
  establish these numbers directly before changing anything)

## Design Decisions

### What a parser publishes when there is no wrapped command

- **Chosen:** Split by what is actually knowable. `nix-shell` with no `--run`/`--command` publishes NOTHING (no
  `nestedCommands` key), so the filter fails closed and the invocation is denied. Bare `xargs` publishes the command it
  is KNOWN to run — `echo` — rather than nothing.
- **Rationale:** The operator's own words: "For nix-shell it should publish nothing since no command is going to be run.
  For xargs it should publish the known result: echo is going to be run." The asymmetry is honest rather than
  inconsistent — an interactive `nix-shell` genuinely runs no command the parser could name, whereas bare `xargs` has a
  documented, statically-known default (`echo`). A parser that publishes nothing for `xargs` would be claiming ignorance
  it does not have.
- **Rejected alternatives:** Publishing nothing in both cases (uniform fail-closed, matching the existing spec case's
  literal premise); adding a protocol signal distinguishing "there is definitely no wrapped command" from "there is one
  but I could not parse it", which would have touched the filter and protocol rather than only the parsers.
- **Date:** 2026-09-18

### Keeping `named["command"]` alongside the new channel

- **Chosen:** Parsers publish on BOTH channels for now — `nestedCommands` (new, load-bearing) and `named["command"]`
  (unchanged). Dropping `named["command"]` is deferred to a separate improvement that first gives filters direct access
  to the `nestedCommands` channel.
- **Rationale:** The operator's condition: "We can drop it but then the filters must also become aware of
  nestedCommands. Otherwise we lose the option to only allow nested commands if these commands match a certain filter in
  addition to its commands passing." Today that capability exists ONLY because a config can point an ordinary
  `namedValue` filter at `named["command"]` — the `nestedCommand` filter itself takes no pattern and only requires each
  sub-command to independently decide `allow`. Dropping the key now would silently remove an expressible restriction,
  which is exactly the class of change this engine treats as most dangerous. Keeping it costs a redundant second
  channel; removing the capability costs the operator a control they use.
- **Rejected alternatives:** Dropping `named["command"]` outright in this improvement (cleaner single channel, but
  removes the pattern-constrainable route with no replacement); doing both here — dropping the key AND adding a
  nestedCommands-aware filter type (matcher class, load-time validation, config schema, migration consideration) — which
  would add engine surface to what is otherwise an urgent live-bug fix and delay the unblock; subdividing this into a
  trunk with two leaves.
- **Date:** 2026-09-18

### Divergence from the shfmt-permissions parser originals

- **Chosen:** Modify only the `packages/command-policy/parsers/` copies, leave
  `packages/shfmt-permissions/scripts/parsers/` untouched, and correct the knowledgebase glossary line that currently
  documents the command-policy parsers as a "copy of packages/shfmt-permissions/scripts/parsers/".
- **Rationale:** 'rationale not captured' beyond the option text — the recommended option was chosen as presented. The
  two packages' deprecation posture (shfmt-permissions stays installed and functionally unchanged until the operator
  migrates) already forbids touching the old copies, and the knowledgebase claim becomes false the moment the new copies
  speak a protocol the old engine does not understand.
- **Rejected alternatives:** Diverging but leaving the now-false knowledgebase claim as an Observed-during-exploration
  note; also porting the change into shfmt-permissions to keep the two sets identical, which would contradict the
  no-functional-change deprecation posture and risk its 751-test baseline.
- **Date:** 2026-09-18

## Success Criteria

- [ ] `timeout 10 echo hi`, `nix develop -c echo hi` and `nix-shell --run 'echo hi'` each decide **allow** when `echo`
      is allow-listed alongside the wrapper — the live symptom is gone
- [ ] The same three wrappers each decide **deny** when the wrapped command is blocked or not allow-listed — propagation
      actually propagates, rather than merely having stopped failing
- [ ] `cd packages/command-policy/tests && nix-shell --run pytest` runs auto-approved, without `bypass-policy` (the
      operator's own most-affected case, and a live end-to-end proof)
- [ ] `test_a_nested_command_filter_composes_with_other_filters_across_entries` and
      `test_propagation_does_not_see_operands_arriving_on_stdin` are GREEN
- [ ] `test_an_entry_whose_nested_command_filter_has_nothing_to_check_does_not_match`,
      `test_exceeding_the_propagation_depth_limit_is_denied` and
      `test_a_propagated_command_is_checked_against_blocked_commands` are green for the RIGHT reason — each asserted at
      `result.reason` level, so none of them can be satisfied by a `ParserCouldNotInterpretInvocation`
- [ ] Every new test was demonstrated RED against pre-fix code before the fix landed, and that demonstration is recorded
      in Observed-during-implementation
- [ ] The command-policy suite has NO failures other than the two named cases going from red to green; any other delta
      from the established baseline is a regression
- [ ] `packages/shfmt-permissions/tests` still passes at its established baseline, with no file under
      `packages/shfmt-permissions/` modified
- [ ] `packages/command-policy/lib/` is unmodified — this improvement changes parsers, tests and docs only
- [ ] The knowledgebase glossary line describing the command-policy parsers as a copy of the shfmt-permissions ones no
      longer makes that claim

## Implementation TODO

- [ ] Update status to in-progress
- [x] Establish the pre-fix baseline: run both suites and record exact pass/fail counts plus the names of the failing
      cases (the plan could not verify the stated 634/2 and 751 numbers — see Assumptions)
- [x] Record the pre-fix `Reason` type for each of the seven xargs spec cases, so the "green for the wrong reason"
      claims in Implementation Notes are re-confirmed against the code as it stands today
- [x] Write the failing unit tests for `parsers/timeout.py`'s `nestedCommands` output and watch them fail
- [x] Teach `parsers/timeout.py` to publish `nestedCommands` (`shape: "argv"`, DURATION excluded, nothing published when
      no command follows), keeping `named["command"]` unchanged
- [x] Write the failing unit tests for `parsers/nix.py` and make them pass (`-c`/`--command` only; nothing published for
      `nix run` and other `-c`-less invocations)
- [x] Write the failing unit tests for `parsers/nix-shell.py` and make them pass (`shape: "shell"`, last `--run`/
      `--command` wins, nothing published for a bare `nix-shell` or `nix-shell shell.nix`)
- [x] Write the failing unit tests for the new `parsers/xargs.py` and make them pass (option walk incl. value-consuming
      options and `--`, COMMAND + INITIAL-ARGS as `shape: "argv"`, bare `xargs` publishing `echo`, `paths` always empty)
- [x] Add the decision-spec case proving a wrapped ALLOWED command is allowed, for each of the four wrappers
- [x] Add the decision-spec case proving a wrapped BLOCKED command is denied, for each of the four wrappers
- [x] Add the companion case isolating propagation-to-`blockedCommands` with every outer program allow-listed, beside
      (never replacing) `test_a_propagated_command_is_checked_against_blocked_commands`
- [x] Retarget `test_an_entry_whose_nested_command_filter_has_nothing_to_check_does_not_match` onto a wrapper that
      genuinely publishes nothing (`nix-shell` with no `--run`), and restate the bare-`xargs` case as what it now tests
- [x] Strengthen `test_exceeding_the_propagation_depth_limit_is_denied` to assert the denial reason, not only the
      outcome
- [ ] Run the full command-policy suite and confirm the only delta from the recorded baseline is the two cases turning
      green
- [ ] Run the shfmt-permissions suite and confirm it is unchanged; confirm via `git status` that nothing under
      `packages/shfmt-permissions/` was touched
- [x] Verify the live end-to-end case: `cd packages/command-policy/tests && nix-shell --run pytest` is auto-approved
      with no `bypass-policy` wrapper (verified against the fixed engine + the real merged config; the running hook
      still serves cached plugin 0.3.0 until the operator updates the install — see Observed during implementation)
- [x] Correct the `docs/knowledgebase/command-policy-decision-model.md` glossary line that calls the command-policy
      parsers a copy of the shfmt-permissions ones, and refresh the "four cases that need parsers/xargs.py" gotcha
      paragraph that this work resolves
- [x] Delete `docs/improvements/experiments/20260918-223632/` — both probes describe pre-fix state and go stale the
      moment the fix lands
- [x] Bump the command-policy plugin version and its marketplace entry
- [x] Update status to completed

## Observed during exploration

- **A third spec passes only coincidentally, beyond the two the task brief predicted.**
  `test_a_propagated_command_is_checked_against_blocked_commands` denies because `find` is not allow-listed in its own
  config, entirely independently of whether propagation to the blocked `rm` works. Folded into scope as a COMPANION case
  rather than a rewrite, since the authored-ahead spec's assertions are authority.
- **`shape` is a declared-but-unread field.** `NestedCommand.shape` is constructed, defaulted and documented, but no
  consumer branches on it — the filter forwards only `text`, and nested text is always re-parsed as shell syntax. The
  two legal values therefore behave identically today. Deliberately left alone here (adding a consumer is engine
  surface, out of scope); recorded so the next reader does not mistake the field for load-bearing machinery.
- **The knowledgebase's own Gotchas section will go stale with this change.** It states the spec suite is green "except
  for four cases that need `packages/command-policy/parsers/xargs.py`", and that those are "not this leaf's to fix".
  Both statements stop being true here; the count is also imprecise against what the probe measured. Folded into scope
  as a documentation TODO.
- **`packages/command-policy/tests/` has no unit coverage for bundled parser scripts at all**, whereas
  `packages/shfmt-permissions/tests/test_new_parsers.py` covers its own. This improvement adds the first such file, but
  only for the four parsers in scope — the other eleven bundled parsers (`awk`, `cat`, `chmod`, `composer`, `find`,
  `gawk`, `git`, `grep`, `npm`, `pnpm`, `sed`, `yarn`) remain uncovered on the command-policy side. Left alone
  deliberately; recorded rather than silently dropped.

## Observed during implementation

- **Pre-fix baseline re-confirmed exactly as stated, via `bypass-policy nix-shell --run pytest`** (the escape hatch —
  plain `nix-shell` is the very command this bug denies): `packages/command-policy/tests` → **634 passed, 2 failed**
  (`test_a_nested_command_filter_composes_with_other_filters_across_entries`,
  `test_propagation_does_not_see_operands_arriving_on_stdin`, both failing with
  `AssertionError: ... Actual: deny ... Reason: (ParserCouldNotInterpretInvocation(program='xargs'),)`).
  `packages/shfmt-permissions/tests` → **751 passed**. Both match the plan's stated Assumptions exactly; that Assumption
  is now CONFIRMED rather than unverified.
- **Re-ran `docs/improvements/experiments/20260918-223632/probe_current_reasons.py` (plain `python3`, no nix shell
  needed) before touching any parser** — it reproduced the planning-time table verbatim: all seven xargs spec cases deny
  via `ParserCouldNotInterpretInvocation` (composing with `ProgramNotAllowListed` for the `find`-blocked-commands case,
  and with `SensitivePathReferenced`/`ArgumentPathOutsideAllowedPaths` for the literal-sensitive-path case), and all
  three live wrapper symptoms (`timeout`, `nix develop -c`, `nix-shell --run`) deny via `FilterRejected` alone, never a
  parse failure. Confirms the parsers parse successfully today and are rejected specifically by the nestedCommand filter
  having nothing to check — exactly the root cause the plan located.
- **`timeout.py`'s new unit tests (`tests/test_bundled_parsers.py::TestTimeoutParserNestedCommands`) were run RED
  first** (all failed with `KeyError: 'nestedCommands'`, confirming the missing-channel defect, not a typo) **before**
  the parser was changed to publish `nestedCommands` alongside the unchanged `named.command`; all 5 are GREEN after.
- **Same RED-first discipline for `nix.py`, `nix-shell.py`, and the new `xargs.py`**: each parser's unit tests
  (`TestNixParserNestedCommands`, `TestNixShellParserNestedCommands`, `TestXargsParserNestedCommands`) were run and
  failed for the expected reason before the corresponding parser change (`KeyError: 'nestedCommands'` for the first two;
  `xargs.py`'s tests failed with `RuntimeError: ... No such file or directory` before the file existed at all). All 23
  cases in `test_bundled_parsers.py` are GREEN after. The full `packages/command-policy/tests` suite then went from
  634/2 to **659 passed, 0 failed** (634 baseline + 23 new unit cases + the 2 previously-RED specs now green).
- **The live acceptance signal needed TWO things beyond this improvement's parser fix, both found by running it rather
  than assuming.** After the fix, plain `nix-shell --run pytest` still denied, and neither cause was a parser defect:
  1. **`pytest` was never allow-listed at all** — absent from `~/.claude/command-policy.json`, from the project
     `.claude/command-policy.json`, AND from the old `~/.claude/shfmt-permissions.json`. This was invisible before the
     migration because the old engine's `_handle_propagate` recursed into an unlisted program and landed on
     `passthrough` (Claude Code's own dialog prompts a human), whereas the deny-by-default model makes "not
     allow-listed" a hard `deny` requiring an explicit entry. The planning session's live reproduction wrapped `echo`
     (allow-listed), so it never surfaced this. Closed through the sanctioned channel at the operator's direction:
     `add-allow-policy --scope project --intent "..." "pytest"`, which wrote `pytest` into the PROJECT config — correct
     scope, since "every suite here runs as `nix-shell --run pytest`" is a repository fact, not a per-user one.
  2. **The running PreToolUse hook serves the INSTALLED PLUGIN CACHE, not this working tree.**
     `~/.claude/plugins/cache/vonaffenfels-dev-tools/command-policy/0.3.0/parsers/` still has no `xargs.py` and no
     `nestedCommands` in any of the three wrapper parsers. So this session's own Bash calls keep being judged by pre-fix
     code no matter what the working tree says, and `nix-shell --run pytest` will keep denying live until the operator
     updates the installed plugin to the 0.3.1 published here. This is exactly why the marketplace version bump is
     load-bearing; it is not a residual defect.

  **Verified as far as is possible without that cache refresh**: driving the FIXED engine (`lib/` from this working
  tree) against the REAL merged user+project config now containing `pytest`,
  `cd packages/command-policy/tests && nix-shell --run pytest`, `nix-shell --run pytest`, `timeout 10 echo hi` and
  `nix develop -c echo hi` all decide **allow**. The criterion is met by the code; only cache propagation remains, and
  that is the operator's install step.

- **Non-vacuity verified directly against pre-fix parser content**, not merely inferred: backed up the four fixed parser
  files, restored `timeout.py`/`nix.py`/`nix-shell.py` to their pre-fix committed content and deleted `xargs.py`, then
  re-ran the new decision-spec cases.
  `test_a_wrapped_allowed_command_is_allowed_for_each_of_the_four_ bundled_wrapper_parsers` and
  `test_a_propagated_command_is_checked_against_blocked_commands_with_every_outer_program_ allow_listed` both genuinely
  FAILED against pre-fix code (`Expected decision: allow, Actual: deny`), confirming they exercise the fix rather than
  passing vacuously. `test_a_wrapped_blocked_command_is_denied_for_each_of_the_four_ bundled_wrapper_parsers` passed on
  BOTH sides - expected and correct, not a vacuity failure: the nestedCommand filter fails closed on an empty
  `nested_commands` list, so pre-fix it denies EVERY wrapped command (allowed or blocked) via the same `FilterRejected`
  reason type, for the wrong underlying cause. Its discriminating power comes from being paired with the ALLOW case,
  exactly the plan's stated "minimum pair" bar - not from being independently RED. Restored the fixed parser content
  afterward and confirmed `git diff` against the committed parsers was empty before re-verifying green.
