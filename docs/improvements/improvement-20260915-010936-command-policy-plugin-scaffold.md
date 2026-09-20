# Improvement 20260915-010936: Command-Policy Plugin Scaffold

## Meta

- Related Ticket: None
- Status: completed
- Created: 2026-09-15
- Updated: 2026-09-15
- Plan started: 2026-09-15T08:49:58+02:00
- Plan finished: 2026-09-15T11:14:59+02:00
- Impl started: 2026-09-15T11:28:57+02:00
- Impl finished: 2026-09-15T17:05:42+02:00
- Trunk: 20260914-195111
- Kind: decomposed

**You MUST also read:** `docs/improvements/improvement-20260914-195111-statement-value-object-refactor.md`

## This Improvement's Objective

LEAF 1 of trunk `20260914-195111` — FIRST IN THE CHAIN. Create the `command-policy` plugin package and settle its
user-facing naming scheme, so that every later leaf has real paths and real command names to write against.

This leaf exists because the trunk's previous six-leaf breakdown was invalidated precisely by getting paths wrong: every
leaf was scoped as in-place edits under `packages/shfmt-permissions/`, and the decision to move the rewrite into a new
plugin made all of them wrong at once. Creating the package FIRST removes that whole class of failure — no later leaf
has to guess where its files go.

IN SCOPE:

1. Scaffold `packages/command-policy/`: `.claude-plugin/plugin.json`, the `hooks/hooks.json` PreToolUse registration
   (Bash matcher, and the Read/Grep/Glob matcher family that the path analyzer serves), and the `lib/`, `bin/`,
   `skills/`, `tests/` directory layout. Register it in the repo-root `.claude-plugin/marketplace.json` with the
   description settled at trunk level: "Deterministic, rule-based permission decisions for commands and file access.
   Same input, same verdict, every time — no model judgment in the loop."
2. SETTLED during this planning session — the five user-facing `bin/` command names, plus the internal entrypoint names.
   See Design Decisions.
3. SETTLED — config file path and the decision to carry no top-level version key. See Design Decisions.
4. Establish the test harness the package never had: a `conftest.py` and a `tests/shell.nix` pinning `python313` +
   pytest + a real `shfmt`.

EXPLICITLY OUT OF SCOPE: any engine logic. This leaf moves no decision code and implements no value object. It produces
an empty, registered, testable package plus a settled naming vocabulary. Deprecating `shfmt-permissions` is NOT here
either — that lands in the final leaf, because the old package must keep working untouched until the new one is real
(trunk decision: "additive, deprecate only").

CRITICAL CONSTRAINT: `shfmt-permissions` stays byte-for-byte untouched by this leaf. It is at marketplace version 6.1.2
with live users and remains the engine everyone actually uses until the chain completes.

NOTE ON ACTIVATION (corrected 2026-09-15): registering the package in `marketplace.json` does NOT make it active. The
plugin only takes effect after the user pushes the changes, updates their marketplace, and installs the plugin — all
deliberate user actions. There is therefore NO risk of this leaf accidentally interfering with anyone's workflow, and no
coexistence hazard to engineer around. The clean handover is the user's own act: deactivate `shfmt-permissions`,
activate `command-policy`. The `bin/` stubs should still exit 0 emitting nothing, but because that is what an
unimplemented stub correctly does — not as a safety mechanism.

## Context / Why This Exists

**Origin / trigger:** Created during the trunk's 2026-09-15 re-plan. The trunk was invalidated because all six of its
leaves were scoped against `packages/shfmt-permissions/` paths that the plugin move made wrong. This leaf is the
structural fix for that failure mode: establish the real package before anything references it.

**Consumer(s) of the output:** Every other leaf in the trunk's chain — each one writes files into the package this leaf
creates, and uses the command names this leaf settles. Downstream, the plugin's eventual users.

**Adjacent systems already covering part of the need:** `docs/knowledgebase/plugin-development.md` governs the
two-files-that-matter rule (plugin-local `plugin.json` plus repo-root `marketplace.json` registration) and the
load-bearing version-bump rule. `docs/knowledgebase/plugin-environment-probe.md` governs the `bin/` vs `scripts/`
question and was READ during this planning session — see the correction recorded under Observed during exploration,
which supersedes the earlier summary of it that appeared in this file. In-repo precedent for the chosen layout is
`packages/improvement/` (`lib/` + `bin/` + a real `conftest.py`).

## Proposed Approach

Scaffold `packages/command-policy/` as a sibling of `packages/shfmt-permissions/`, but on the `lib/` + thin-`bin/`
layout that `packages/improvement/` already proves in this repo, rather than mirroring the old package's flat `scripts/`
structure.

DIRECTORY LAYOUT (settled — every later leaf writes against this):

```
packages/command-policy/
|-- .claude-plugin/plugin.json
|-- hooks/hooks.json
|-- lib/                 # all real code; a sys.path entry, NOT a package (no __init__ file)
|-- bin/                 # ALL entrypoints, user-facing and internal; on the Bash PATH
|-- skills/              # placeholder until the skills leaf (20260915-011123)
`-- tests/               # conftest.py + shell.nix
```

There is NO `scripts/` directory. This is a deliberate departure from `shfmt-permissions` and it is the single most
load-bearing path decision in this leaf.

WHY `lib/` + THIN `bin/`: the `conftest.py` pain this leaf was scoped to fix is CAUSED by hyphenated, extensionless
entrypoint filenames — `shfmt-permissions` has no `conftest.py` and each of its 8 test files independently re-implements
the same `importlib.util` load plus the `sys.modules[...]` assignment. Moving the real code into `lib/`, which imports
normally, dissolves that problem at the root instead of centralising the workaround. `bin/` entrypoints stay thin enough
that no test ever needs to import one.

HOW `lib/` IS REACHED (verified by execution during planning; copied from
`packages/improvement/bin/improvement-marker`): each `bin/` entrypoint bootstraps with
`sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))` and then imports modules
FLAT (`import config`, not `import lib.config`). `lib/` deliberately has no `__init__` file, matching
`packages/improvement/lib/`.

THE `bin/` ROSTER (settled):

| Command                                  | Replaces                                                  | Audience                                           |
| ---------------------------------------- | --------------------------------------------------------- | -------------------------------------------------- |
| `bypass-policy`                          | `bypass-shfmt-permissions`                                | user-facing (settled at trunk)                     |
| `add-allow-policy --scope user\|project` | `propose-shfmt-permissions-user-allow` + `-project-allow` | user-facing (settled at trunk; the pair collapses) |
| `explain-policy`                         | `render-shfmt-permissions`                                | user-facing                                        |
| `audit-session-policy`                   | `shfmt-session-approvals`                                 | user-facing                                        |
| `command-policy-analyze-bash-command`    | `scripts/analyze-bash-command.py`                         | internal, hook-invoked                             |
| `command-policy-analyze-path`            | `scripts/analyze-path.py`                                 | internal, hook-invoked                             |

The two internal entrypoints carry the `command-policy-` prefix because plugin `bin/` is APPENDED to PATH, not
prepended, so a generic name like `analyze-path` can be silently shadowed by anything earlier in PATH. The four
user-facing names stay short because humans and the model type them; the internal two are only ever referenced from
`hooks.json` by full path, so a long distinctive name costs nothing.

HOOK REGISTRATION: `hooks/hooks.json` registers PreToolUse for the `Bash` matcher pointing at
`${CLAUDE_PLUGIN_ROOT}/bin/command-policy-analyze-bash-command`, and for the `Read`/`Grep`/`Glob` matcher family
pointing at `${CLAUDE_PLUGIN_ROOT}/bin/command-policy-analyze-path`. This follows what
`docs/knowledgebase/plugin-environment-probe.md` prescribes, but NO plugin in this repo currently routes a hook through
`bin/` — see Assumptions; verifying it live is the FIRST implementation step.

INERT-ON-INSTALL: every `bin/` entrypoint ships as a stub that exits 0 and emits nothing. For the two hook entrypoints
this is the 'no opinion' / passthrough response, so installing `command-policy` alongside the still-live
`shfmt-permissions` changes no permission decision anywhere. This is what makes the additive cutover safe during the
remaining eight leaves.

TEST HARNESS: `tests/conftest.py` adapted from `packages/improvement/tests/conftest.py`, but SIMPLER — it needs only (a)
the `sys.path` bootstrap making `lib/` modules directly importable, and (b) a `run_entrypoint` subprocess fixture
driving a `bin/` entrypoint end-to-end for its CLI contract. It deliberately does NOT carry an importlib module-loader
fixture; see the invariant in Implementation Notes. `tests/shell.nix` pins `python313`, `python313Packages.pytest` and
`shfmt`, matching `packages/shfmt-permissions/tests/shell.nix`.

CONFIG: `~/.claude/command-policy.json` plus `${CLAUDE_PROJECT_DIR}/.claude/command-policy.json`. No top-level schema or
version key — the file starts directly with its keys, matching today's precedent. This leaf only FIXES THE PATH; the
config's internal key vocabulary (including the death of four decision knobs) belongs to the config leaf
`20260914-213153` and must not be pre-empted here.

## Affected Components

**Files:**

- `packages/command-policy/.claude-plugin/plugin.json` (new)
- `packages/command-policy/hooks/hooks.json` (new)
- `packages/command-policy/lib/` (new, empty until later leaves)
- `packages/command-policy/bin/bypass-policy` (new, stub)
- `packages/command-policy/bin/add-allow-policy` (new, stub)
- `packages/command-policy/bin/explain-policy` (new, stub)
- `packages/command-policy/bin/audit-session-policy` (new, stub)
- `packages/command-policy/bin/command-policy-analyze-bash-command` (new, stub, hook-invoked)
- `packages/command-policy/bin/command-policy-analyze-path` (new, stub, hook-invoked)
- `packages/command-policy/tests/conftest.py` (new)
- `packages/command-policy/tests/shell.nix` (new)
- `packages/command-policy/tests/test_scaffold.py` (new — the smoke test proving the scaffold is real and inert)
- `.claude-plugin/marketplace.json` (register command-policy; shfmt-permissions entry untouched at 6.1.2)
- `CLAUDE.md` (add the command-policy package to the Repository Structure list)

**Modules:**

- command-policy (new package)
- shfmt-permissions (MUST remain byte-for-byte untouched)

## Implementation Notes

HOOK ROUTE — NOW CONFIRMED, AND HOW IT GETS VERIFIED. The `${CLAUDE_PLUGIN_ROOT}/bin/<name>` hook target is DOCUMENTED
AND SUPPORTED (see Assumptions). Claude Code treats a hook command as a shell command string, so `scripts/` versus
`bin/` is irrelevant to how it resolves; and `bin/` is itself a documented plugin directory whose contents are added to
the Bash tool's PATH while the plugin is enabled.

THE IMPLEMENTER CAN FULLY TEST THE HOOK — it just does not happen automatically. Three levels, in increasing fidelity:

1. STANDALONE, no registration: pipe a hook JSON payload into each entrypoint and check exit code and stdout — the
   officially documented way to test a command hook. Proves the entrypoint itself works.
2. TEMPORARILY REGISTERED (the real end-to-end test): add the hook under test to `.claude/settings.local.json`, restart
   the session, and issue a real Bash call. This fires the hook for real — matcher, command resolution, exit code and
   output — WITHOUT installing a plugin. Two things to get right:
   - `${CLAUDE_PLUGIN_ROOT}` is NOT set for a settings-registered hook, because nothing is installed. Use the working
     copy's real path (e.g. `${CLAUDE_PROJECT_DIR}/packages/command-policy/bin/command-policy-analyze-bash-command`).
     The eventual `hooks/hooks.json` still uses `${CLAUDE_PLUGIN_ROOT}`; only the temporary test entry differs.
   - `.claude/settings.local.json` uses the SETTINGS format (events at top level), NOT the plugin wrapper format (events
     nested under a `hooks` key). The two files are not interchangeable.
   - ⚠ REMOVE THE TEMPORARY ENTRY WHEN DONE. A leftover test hook pointing at a half-built permission analyzer gates
     every Bash call in the user's sessions. This is the one genuine way this leaf CAN disturb the user's workflow, and
     it is entirely within the implementer's control — unlike plugin registration, which is inert.
3. USER, at handover: after push + marketplace update + install, confirm with `/hooks` (lists configured hooks, matchers
   and handlers) and the debug log, which records which hooks matched, their exit codes and their output.
   `/reload-plugins` reloads plugin hooks without a full restart.

THE THIN-WRAPPER INVARIANT. Verified by execution during planning: `importlib.util.spec_from_file_location` returns
`None` for an extensionless file, so a `bin/` entrypoint cannot be loaded as a module without an explicit
`SourceFileLoader`. Do NOT add such a loader to `conftest.py`. The inability to import a `bin/` entrypoint is a FEATURE
that enforces the layout: real logic belongs in `lib/`, which imports normally, and `bin/` entrypoints stay thin enough
to be covered by the `run_entrypoint` subprocess fixture. If a later leaf finds itself wanting to importlib-load a
`bin/` entrypoint, that is the signal that logic has leaked out of `lib/` — fix the leak, do not add the loader.

STUBS EXIT 0 EMITTING NOTHING. The two hook entrypoints should exit 0 printing nothing, which is the documented 'no
opinion' response. This is correct stub behaviour for something unimplemented — it is NOT a safety gate. An earlier
draft of this plan framed an allow-emitting stub as a repo-wide security regression; that was wrong, because an
uninstalled plugin is inert (see the activation note in the objective).

HOOK CONFIG IS NOT HOT-SWAPPABLE. Hooks are loaded when a session starts; editing `hooks/hooks.json` does not affect a
running session. `/reload-plugins` reloads plugin hooks, and `claude --debug` surfaces registration and execution
detail.

USE THE PLUGIN-DEV TOOLING RATHER THAN HAND-CHECKING. The `plugin-dev` plugin ships `validate-hook-schema.sh` (validates
`hooks.json` structure), `test-hook.sh` (drives a hook with sample input) and `hook-linter.sh` (common-issue check). Run
these against this package's `hooks/hooks.json` instead of eyeballing it.

PLUGIN HOOKS.JSON USES THE WRAPPER FORMAT. A plugin's `hooks/hooks.json` wraps its events in a top-level `hooks` key
(optionally alongside a `description`), which is NOT the same shape as a settings.json hooks block where events sit at
top level. Match the existing wrapper shape used by `packages/shfmt-permissions/hooks/hooks.json`.

CARRIED FORWARD FOR LEAF `20260915-010959` (deny+hint and escalation paths), recorded here because it was measured
during this leaf's research rather than that one's: a PreToolUse hook returns its verdict as
`hookSpecificOutput.permissionDecision` with values `allow` / `deny` / `ask`, and EXIT CODE 2 FEEDS THE HOOK'S STDERR
BACK TO CLAUDE. That exit-2 channel is precisely the mechanism the trunk's new outcome model needs for 'deny with a
reason that bounces back to the model so it self-corrects'. That leaf should build on this documented behaviour rather
than rediscovering it.

PLUGIN VERSION. Start `command-policy` at `0.1.0` — it is an inert scaffold, not a working engine, and the version
should not claim otherwise. The version-bump rule in `docs/knowledgebase/plugin-development.md` applies from here on:
`plugin.json` and the `marketplace.json` entry must be bumped together, and they must agree.

DO NOT PRE-EMPT LATER LEAVES. This leaf settles PATHS and NAMES only. It must not decide config key vocabulary (config
leaf `20260914-213153`), outcome vocabulary (pipeline leaf `20260914-213652`), deny-reason shape (leaf
`20260915-010959`), or skill content (leaf `20260915-011123`). Where a stub needs a placeholder, leave it obviously
unimplemented rather than guessing at a later leaf's design.

WHY NO `skills/` CONTENT HERE. The directory exists so later leaves have a home, but both planned skills belong to leaf
`20260915-011123`. An empty directory with no `SKILL.md` is correct at this stage.

**Testing Strategy:** TDD (Red-Green-Refactor) as required by project conventions

### Measured during implementation (2026-09-15)

SETTINGS-LEVEL HOOKS HOT-LOAD; NO SESSION RESTART NEEDED. The plan's level-2 end-to-end recipe said to restart the
session after adding the hook to `.claude/settings.local.json`. MEASURED: not required. The entry was added mid-session
and the very next Bash call fired the entrypoint. This refines the "HOOK CONFIG IS NOT HOT-SWAPPABLE" note above, which
holds for a PLUGIN's `hooks/hooks.json` but NOT for `settings.local.json`. Level-2 testing is therefore cheaper than
planned — no restart, no lost context.

HOW FIRING WAS OBSERVED. A correct stub is silent, so firing is invisible by construction. The entrypoint was
temporarily given a line appending its stdin payload to a scratchpad log, a real Bash call was issued, the log was
confirmed to contain the real hook JSON (`session_id`, `transcript_path`, `cwd`), and the entrypoint was then restored
with `git checkout --` and verified clean by `git diff`. Recording the technique because every later leaf testing a hook
end-to-end faces the same invisibility problem.

THE PLUGIN-DEV TOOLING DOES NOT UNDERSTAND THE PLUGIN WRAPPER FORMAT. `validate-hook-schema.sh` iterates the TOP-LEVEL
keys expecting event names, so against any plugin `hooks/hooks.json` it reports `Unknown event type: description` /
`Unknown event type: hooks` and then dies with a jq error. CONFIRMED NOT SPECIFIC TO THIS PACKAGE: the identical failure
occurs against the live `packages/shfmt-permissions/hooks/hooks.json`. The tool validates the SETTINGS shape only. The
working invocation is to unwrap first — `jq '.hooks' hooks/hooks.json > /tmp/inner.json` and validate that, which passes
all checks with zero warnings. Separately, `hook-linter.sh` lints hook SCRIPTS, not `hooks.json`; run it against the
`bin/` entrypoints (both pass with zero errors; its remaining warnings are bash idioms such as `set -euo pipefail` that
do not apply to Python entrypoints).

## Test Architecture

**Existing helpers to reuse:**

- `packages/improvement/tests/conftest.py` — the structural template: sys.path lib bootstrap plus a `run_entrypoint`
  subprocess fixture. Adapt, do not copy wholesale — its `script_module` importlib fixture is deliberately NOT ported
- `packages/improvement/bin/improvement-marker` — the exact working sys.path bootstrap line a `bin/` entrypoint uses to
  reach `lib/`
- `packages/shfmt-permissions/tests/shell.nix` — the nix pin set to match: python313, python313Packages.pytest, shfmt

**New helpers to create:**

- `conftest.py` `lib/` sys.path bootstrap — makes every `lib/` module importable flat from tests, which is the whole
  point of the `lib/` layout and what removes the per-file importlib duplication the old package suffers
- `run_entrypoint` fixture — the ONLY sanctioned way to exercise a thin `bin/` entrypoint, since importing one is
  deliberately not supported

**Fantasy callsites (test-facing API sketches):**

- `run_entrypoint("command-policy-analyze-bash-command", stdin=hook_payload) -> CompletedProcess(returncode=0, stdout="")`
- `run_entrypoint("explain-policy") -> CompletedProcess(returncode=0)`

**Testability-driven production decisions:**

- Real code lives in `lib/` as plainly-importable flat modules specifically so every later leaf's value objects are
  unit-testable without any importlib machinery
- `bin/` entrypoints are kept thin precisely because they can only be tested through subprocess; thinness is what keeps
  that limitation harmless

## Design Decisions

### Package code layout: where engine code and entrypoints live

- **Chosen:** `lib/` holds all real code as a flat sys.path directory (no `__init__` file); a single `bin/` holds ALL
  entrypoints, both user-facing and hook-invoked; there is NO `scripts/` directory
- **Rationale:** User: 'lib/ packages + thin bin/ entrypoints. Plugin bin/ is in PATH for bash invocations - no need for
  the session to mess around with a plugin dir variables or finds into the plugin cache to find the script anymore.' The
  planner additionally established that the `conftest.py` problem this leaf exists to solve is CAUSED by hyphenated
  extensionless entrypoint filenames, so moving real code into an importable `lib/` dissolves it at the root rather than
  centralising the workaround. When the planner proposed keeping a separate `scripts/` for hook entrypoints, the user
  rejected the three-way split in favour of one entrypoint directory and one rule.
- **Rejected alternatives:** Flat `scripts/` mirroring `shfmt-permissions` exactly (keeps the importlib workaround, just
  centralised); a three-way split with `lib/` + `bin/` for user-facing + `scripts/` for hook entrypoints (keeps hook
  entrypoints off the Bash PATH, but adds a bin-vs-scripts judgment call to every later leaf)
- **Date:** 2026-09-15

### Naming of the internal, hook-invoked entrypoints

- **Chosen:** Prefix them with the plugin name: `command-policy-analyze-bash-command` and `command-policy-analyze-path`.
  The four user-facing commands stay unprefixed.
- **Rationale:** User: 'prefix the internal commands with command-policy- so they don't accidentally collide with other
  plugins.' This is a direct application of the documented gotcha in `docs/knowledgebase/plugin-environment-probe.md`:
  plugin `bin/` is APPENDED to PATH, not prepended, so an executable of the same name earlier in PATH wins. Under the
  chosen everything-in-bin layout the hook entrypoints land on the PATH too, which makes a generic name like
  `analyze-path` a real collision risk. The asymmetry is deliberate: user-facing names are typed by humans and the model
  so brevity has value, while the internal two are only referenced from `hooks.json` by full path, so a long distinctive
  name costs nothing.
- **Rejected alternatives:** Leaving the internal entrypoints unprefixed (`analyze-path`, `analyze-bash-command`) and
  relying on PATH ordering; prefixing all six commands uniformly for consistency at the cost of everyday ergonomics
- **Date:** 2026-09-15

### Whether `add-allow-policy` keeps the user/project command PAIR or collapses behind a flag (explicitly assigned to this leaf by the trunk)

- **Chosen:** Collapse into ONE command with a `--scope user|project` flag
- **Rationale:** rationale not captured (option chosen as presented). The argument put to the user and not contested:
  the scope stays fully visible in the permission dialog because it is on the command line, and since this path ALWAYS
  forces `ask` by design it is never auto-approved — so the per-program allow-list granularity that two separate
  programs would buy is worth nothing here.
- **Rejected alternatives:** Keep the pair as `add-allow-policy-user` / `add-allow-policy-project`, mirroring today's
  two commands so each name states its own scope with no flag to misread; one command with project as the silent default
  and `--user` to override (shortest common case, but makes the scope choice implicit)
- **Date:** 2026-09-15

### Names for the remaining two user-facing `bin/` commands

- **Chosen:** `explain-policy` (was `render-shfmt-permissions`) and `audit-session-policy` (was
  `shfmt-session-approvals`)
- **Rationale:** rationale not captured (option chosen as presented). The argument put to the user: `explain-policy`
  matches the trunk-settled `Config.explain()` surface that backs it, so the CLI name and the value-object method that
  implements it read as ONE concept instead of drifting into two vocabularies (render vs explain).
- **Rejected alternatives:** `render-policy` + `session-approvals-policy` (most literal translation of today's names, so
  existing users transfer directly, but leaves `render` and `explain()` as two words for one thing); `show-policy` +
  `check-session-policy` (plainest everyday verbs, but `show` drifts furthest from the settled `explain()` vocabulary)
- **Date:** 2026-09-15

### Whether `command-policy.json` carries a top-level version or schema key

- **Chosen:** No version key — the file starts directly with its config keys, matching today's `shfmt-permissions.json`
  precedent
- **Rationale:** rationale not captured (option chosen as presented). The argument put to the user: the FILENAME is
  already the format discriminator — `command-policy.json` is by definition the new format and `shfmt-permissions.json`
  the old one — so a version field with exactly one legal value earns nothing and invites compatibility branching into
  the code path that gates every Bash call, which the trunk's 'no auto-detection' decision deliberately keeps clean.
- **Rejected alternatives:** Add a top-level version key so `Config.warnings()` can flag a config from an unknown
  generation and the migration skill has something explicit to stamp (does not violate the trunk decision, but
  introduces a concept with no second value yet)
- **Date:** 2026-09-15

### Whether `conftest.py` should be able to load a `bin/` entrypoint as a module

- **Chosen:** No. `conftest.py` provides only the `lib/` sys.path bootstrap and a `run_entrypoint` subprocess fixture.
  No importlib/SourceFileLoader fixture is added.
- **Rationale:** User, challenging the planner's proposed helper: 'Why would we load a file in /bin/ if they are just
  thin wrappers pulling from the /lib/ directory?' This was correct and removed work rather than adding it. Real logic
  lives in `lib/` and imports normally; the thin wrappers are covered end-to-end by subprocess. The planner had verified
  by execution that loading an extensionless `bin/` file requires an explicit `SourceFileLoader`, and that result is
  retained NOT as a helper but as an enforcing invariant: the difficulty of importing a `bin/` entrypoint is the signal
  that keeps logic in `lib/`. This makes command-policy's harness strictly simpler than
  `packages/improvement/tests/conftest.py`, which still needs its importlib fixture only because its `scripts/*.py`
  hooks hold real logic.
- **Rejected alternatives:** Port `improvement`'s `script_module` importlib fixture across and extend it with an
  explicit `SourceFileLoader` to handle extensionless hyphenated entrypoints
- **Date:** 2026-09-15

## Assumptions

- **A PreToolUse hook can invoke `${CLAUDE_PLUGIN_ROOT}/bin/<name>`, and `bin/` is a legitimate plugin directory** —
  confirmed (Verified against official Claude Code documentation via the claude-code-guide agent, 2026-09-15. (1)
  `${CLAUDE_PLUGIN_ROOT}` is a documented hook path placeholder and a hook command is just a shell command string —
  Claude Code does not treat `scripts/` and `bin/` differently when resolving it. (2) `bin/` is an explicitly documented
  plugin directory: 'Executables added to the Bash tool's PATH while the plugin is enabled'
  (code.claude.com/docs/en/plugins.md). This SUPERSEDES an earlier draft of this plan that recorded the route as
  unverified and as having no precedent; the planner's doubt came from the plugin-dev SKILL, which omits `bin/`
  entirely, rather than from the official docs, which define it.)

- **A plugin shipping a `bin/` directory can be distributed through this repo's marketplace** — confirmed (The docs note
  a caveat that plugins with a `bin/` directory cannot be distributed via organized marketplace / managed settings, and
  are limited to project or user scope. This repo's distribution is unaffected, demonstrated empirically: `improvement`,
  `estimate`, `probe` and `shfmt-permissions` ALL already ship `bin/` directories, are installed from this same
  marketplace, and their bare commands work — `improvement-marker` was invoked as a bare command repeatedly during this
  very planning session. Recorded rather than dropped because it would bite an organized-marketplace distribution.)

- **A hook process's PATH includes the plugin's `bin/` directory, so a hook could invoke a bare command name** —
  unverified (NOT DOCUMENTED — the docs confirm hook processes receive `${CLAUDE_PLUGIN_ROOT}` but are silent on whether
  plugin `bin/` is on a hook process's PATH. THIS PLAN DOES NOT DEPEND ON IT: `hooks.json` uses the full
  `${CLAUDE_PLUGIN_ROOT}/bin/<name>` path, never a bare name. Left unverified deliberately rather than measured, since
  nothing here rests on it. If a future change wants bare-name hook invocation, this repo owns `/probe:env` as the
  instrument to measure it — do not infer it.)

- **Registering a plugin in `marketplace.json` makes it active and able to affect the user's sessions** — refuted (User,
  correcting the planner: the plugin only becomes active after the user pushes the changes, updates their marketplace,
  and installs the plugin. A committed `marketplace.json` entry is inert on its own. This refutation removed a whole
  class of invented risk from this plan — an 'inertness gate' success criterion and a security-regression framing for
  stub behaviour, both of which were guarding against something that cannot happen.)

- **A `bin/` entrypoint can reach `lib/` via a relative sys.path bootstrap, and flat imports work from an extensionless
  executable** — confirmed (Verified BY EXECUTION during planning. A probe replicating the layout
  (`bin/command-policy-analyze-bash-command` bootstrapping `sys.path.insert(0, .../../lib)` then `import policy_thing`)
  ran successfully and printed the value imported from `lib/`. This matches the working in-repo precedent at
  `packages/improvement/bin/improvement-marker`, which uses the identical bootstrap line.)

- **`lib/` needs an `__init__` file to be importable** — refuted (`packages/improvement/lib/` contains only
  `improvements.py`, `markers.py`, `paths.py`, `timings.py` — no `__init__` file. It is a sys.path ENTRY, not a package,
  and its modules are imported flat (`import markers`, not `import lib.markers`). The planning probe reproduced this
  successfully. Later leaves must therefore write `import config`, NOT `import lib.config`.)

- **`improvement`'s `conftest.py` `script_module` importlib fixture ports across to command-policy unchanged** — refuted
  (Verified BY EXECUTION: `importlib.util.spec_from_file_location('m', 'bin/command-policy-analyze-bash-command')`
  returns `None` for an extensionless file, so the fixture would fail with an AttributeError on `spec.loader`. Loading
  such a file requires an explicit `SourceFileLoader`, which was confirmed to work. However the fixture is NOT being
  ported at all — see the design decision; the refutation is recorded because it is the evidence behind the thin-wrapper
  invariant, not because a workaround is needed.)

- **Plugin `bin/` is appended to the Bash tool PATH and its contents are invokable as bare command names** — confirmed
  (`docs/knowledgebase/plugin-environment-probe.md:23-24` (fact 4), measured 2026-08-03 via `/probe:env` on Claude Code
  2.1.220. CAVEAT: the article states these facts are VERSION-SCOPED and should be re-measured after a Claude Code
  upgrade. This leaf's user-facing command design depends on it; if it no longer holds, the four user-facing commands
  still work by full path but lose their ergonomic justification.)

- **The four-key `plugin.json` shape and the six-key `marketplace.json` entry shape are the established repo
  convention** — confirmed (code-research against HEAD: `packages/shfmt-permissions/.claude-plugin/plugin.json:1-8` and
  `packages/improvement/.claude-plugin/plugin.json:1-8` both carry exactly `name`, `version`, `description`,
  `author{name}`. `.claude-plugin/marketplace.json:116-123` adds `source` and mirrors the other four values exactly.)

- **A hook entrypoint that exits 0 printing nothing leaves the existing permission engine in charge** — confirmed
  (Established at trunk level from the current engine's own behaviour: `AnalysisResult` maps `passthrough` to `None` in
  `to_json_response()` so the hook prints nothing and Claude Code falls through to its own logic (trunk Shared Context,
  'Measured facts about the code being replaced'). NOTE: an earlier draft drew the further conclusion that emitting an
  explicit allow instead 'would be a security regression'. That conclusion is WITHDRAWN — it assumed a registered plugin
  is live, which it is not. Exiting 0 with no output remains the right stub behaviour simply because it is the honest
  response for something unimplemented.)

## Observed during exploration

1. **The knowledgebase article and actual repo practice disagree about how hooks invoke plugin scripts.**
   `docs/knowledgebase/plugin-environment-probe.md:41-44` states hook scripts should use
   `${CLAUDE_PLUGIN_ROOT}/bin/<name>`, but every hook in both `packages/shfmt-permissions/hooks/hooks.json` and
   `packages/improvement/hooks/hooks.json` uses `${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py`. Either the article is stale
   or every plugin in the repo diverges from it. This leaf follows the article (see Assumptions) and will settle the
   question by execution, but reconciling the article with practice afterwards is worth its own improvement and is not
   in this leaf's scope.

2. **This improvement file's own Context section previously misstated that article.** It claimed hooks 'must keep using
   `${CLAUDE_PLUGIN_ROOT}/scripts/...` because `CLAUDE_PLUGIN_ROOT` does not exist in the Bash tool environment' — the
   reason given is true and correctly measured, but it was attached to the wrong conclusion (the article draws the
   opposite one). The Context section has been corrected in this update. Recorded because a plan that miscites its own
   governing document is exactly how a later implementation session inherits a wrong premise with confidence.

3. **The `plugin-dev` skill's structure documentation omits the `bin/` directory that the official docs define.**
   `plugin-dev/skills/plugin-structure` lists `.claude-plugin/`, `commands/`, `agents/`, `skills/`, `hooks/`,
   `.mcp.json` and `scripts/` as the plugin layout, and never mentions `bin/`. The official documentation at
   code.claude.com/docs/en/plugins.md DOES define it ('Executables added to the Bash tool's PATH while the plugin is
   enabled'). Reading the skill alone led this planner to briefly and wrongly report that `bin/` was unsupported for
   plugin entrypoints. Recorded because the gap will mislead anyone else who reaches for the bundled skill as the
   authority on plugin layout.

## Success Criteria

- [ ] `packages/command-policy/` exists with the settled layout — `.claude-plugin/`, `hooks/`, `lib/`, `bin/`,
      `skills/`, `tests/` — and contains NO `scripts/` directory
- [ ] `.claude-plugin/plugin.json` carries the four-key shape (`name`, `version`, `description`, `author`) at version
      `0.1.0` with the trunk-settled description
- [ ] `command-policy` is registered in the repo-root `.claude-plugin/marketplace.json` with a matching entry, and the
      `shfmt-permissions` entry is unchanged at `6.1.2`
- [ ] All six `bin/` entrypoints exist with the executable bit set: `bypass-policy`, `add-allow-policy`,
      `explain-policy`, `audit-session-policy`, `command-policy-analyze-bash-command`, `command-policy-analyze-path`
- [ ] Each of the six `bin/` entrypoints, driven standalone with a piped hook JSON payload, exits 0 with empty stdout —
      verified by the implementer without installing anything
- [ ] `hooks/hooks.json` passes `validate-hook-schema.sh` and `hook-linter.sh` from the plugin-dev plugin, and uses the
      plugin wrapper format (events nested under a top-level `hooks` key)
- [ ] END-TO-END HOOK TEST (implementer-performed): with the hook temporarily registered in
      `.claude/settings.local.json` pointing at the working-copy path, a real Bash call demonstrably fires
      `command-policy-analyze-bash-command`, and the temporary entry is REMOVED afterwards
- [ ] HANDOVER CHECK (user-performed, not implementer-performed): after push + marketplace update + install, `/hooks`
      lists the command-policy PreToolUse entries for the Bash and Read/Grep/Glob matchers, and the debug log shows the
      hook firing on a real Bash call
- [ ] `tests/conftest.py` makes `lib/` modules importable flat (`import config`) and provides a `run_entrypoint`
      subprocess fixture; it contains NO importlib module-loader fixture
- [ ] `tests/shell.nix` pins `python313`, `python313Packages.pytest` and `shfmt`
- [ ] `cd packages/command-policy/tests && nix-shell --run "pytest -v"` is green, including a smoke test that asserts
      each stub entrypoint exits 0 with empty stdout and that a `lib/` module imports from a `bin/` entrypoint
- [ ] `git diff --stat packages/shfmt-permissions/` is EMPTY — the old package is byte-for-byte untouched by this leaf
- [ ] No engine logic exists in the package: `lib/` contains no decision, filter, parser or config-parsing code (that
      belongs to later leaves)
- [ ] The `## Interface` section is written, recording the settled paths and the six command names for every downstream
      leaf to consume

## Implementation TODO

- [x] Update status to in-progress
- [x] Create `.claude-plugin/plugin.json` (four-key shape, version `0.1.0`, trunk-settled description) and register
      `command-policy` in the repo-root `.claude-plugin/marketplace.json` with a matching entry
- [x] Scaffold the directory layout: `lib/`, `bin/`, `skills/`, `tests/`, `hooks/` (no `scripts/` directory)
- [x] Create the two internal hook stub entrypoints `command-policy-analyze-bash-command` and
      `command-policy-analyze-path` — exit 0 printing nothing, executable bit set
- [x] Create the four user-facing `bin/` stubs with the settled names (`bypass-policy`, `add-allow-policy` accepting
      `--scope user|project`, `explain-policy`, `audit-session-policy`) — exit 0 printing nothing, executable bit set
- [x] Write `hooks/hooks.json` in the plugin WRAPPER format (events under a top-level `hooks` key), registering
      PreToolUse for the `Bash` matcher to `${CLAUDE_PLUGIN_ROOT}/bin/command-policy-analyze-bash-command` and for the
      `Read`/`Grep`/`Glob` matcher family to `${CLAUDE_PLUGIN_ROOT}/bin/command-policy-analyze-path`, with explicit
      timeouts
- [x] Validate `hooks/hooks.json` with the plugin-dev `validate-hook-schema.sh` and `hook-linter.sh`
- [x] Verify each of the six entrypoints standalone: pipe a hook JSON payload in, assert exit 0 and empty stdout (no
      install needed)
- [x] END-TO-END HOOK TEST: temporarily register the Bash-matcher hook in `.claude/settings.local.json` (SETTINGS format
      — events at top level, not the plugin wrapper; and use the working-copy path, since `${CLAUDE_PLUGIN_ROOT}` is
      unset when nothing is installed), restart the session, issue a real Bash call, and confirm the entrypoint fires
- [x] ⚠ REMOVE the temporary `.claude/settings.local.json` hook entry and confirm it is gone — a leftover entry gates
      every Bash call in the user's sessions
- [x] Write `tests/conftest.py` providing the `lib/` sys.path bootstrap (adapted from
      `packages/improvement/tests/conftest.py`) and the `run_entrypoint` subprocess fixture; DO NOT include an importlib
      module-loader fixture
- [x] Write `tests/shell.nix` pinning `python313`, `python313Packages.pytest`, `shfmt`
- [x] Write `tests/test_scaffold.py`: assert each of the six `bin/` entrypoints exits 0 with empty stdout, and that a
      trivial placeholder `lib/` module imports successfully from a `bin/` stub via the bootstrap
- [x] Run `cd packages/command-policy/tests && nix-shell --run "pytest -v"` and confirm green
- [x] Verify `git diff --stat packages/shfmt-permissions/` is EMPTY
- [x] Add `command-policy` to the Repository Structure list in `CLAUDE.md`
- [x] Write the `## Interface` section recording the six command names, the settled directory layout, and the config
      path, so downstream leaves consume it without re-planning
- [x] HAND OFF TO USER: state plainly that activation is theirs — push, update marketplace, install, then confirm with
      `/hooks` and the debug log, and deactivate `shfmt-permissions` when they choose to cut over
- [x] Update status to completed

## Interface

LEAF 1 OUTPUT — the settled vocabulary every downstream leaf of trunk `20260914-195111` writes against. These are facts
about the package as it exists at HEAD, not proposals. Do not re-decide them; extend them.

### Package root

`packages/command-policy/` — registered in `.claude-plugin/marketplace.json` at version `0.1.0`, alongside the
still-live `shfmt-permissions` at `6.1.2`.

### Directory layout

```
packages/command-policy/
|-- .claude-plugin/plugin.json   # four keys: name, version, description, author{name}
|-- hooks/hooks.json             # plugin WRAPPER format (events nested under a top-level "hooks" key)
|-- lib/                         # ALL real code; a sys.path entry, NOT a package (no __init__ file)
|-- bin/                         # ALL entrypoints, user-facing and hook-invoked; on the Bash PATH
|-- skills/                      # empty until leaf 20260915-011123
`-- tests/                       # conftest.py, shell.nix, test_scaffold.py
```

There is NO `scripts/` directory, and no leaf may add one.

### How a `bin/` entrypoint reaches `lib/`

Copy this bootstrap verbatim; imports are FLAT (`import config`, never `import lib.config`):

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import placeholder
```

`lib/placeholder.py` exists only to prove this route works and to give the smoke test something to import. The first
leaf that adds a real `lib/` module should delete it and repoint `tests/test_scaffold.py`'s import.

### The six command names

| Command                                  | Replaces                                                  | Audience               |
| ---------------------------------------- | --------------------------------------------------------- | ---------------------- |
| `bypass-policy`                          | `bypass-shfmt-permissions`                                | user-facing            |
| `add-allow-policy --scope user\|project` | `propose-shfmt-permissions-user-allow` + `-project-allow` | user-facing            |
| `explain-policy`                         | `render-shfmt-permissions`                                | user-facing            |
| `audit-session-policy`                   | `shfmt-session-approvals`                                 | user-facing            |
| `command-policy-analyze-bash-command`    | `scripts/analyze-bash-command.py`                         | internal, hook-invoked |
| `command-policy-analyze-path`            | `scripts/analyze-path.py`                                 | internal, hook-invoked |

All six exist, carry the executable bit, and currently exit 0 with empty stdout.

### Hook registration (already written, extend rather than replace)

`hooks/hooks.json` registers PreToolUse for the `Bash` matcher →
`${CLAUDE_PLUGIN_ROOT}/bin/command-policy-analyze-bash-command` (timeout 10), and for the `Read`, `Grep` and `Glob`
matchers → `${CLAUDE_PLUGIN_ROOT}/bin/command-policy-analyze-path` (timeout 5 each). The `bin/` route is measured
working end-to-end, not assumed.

### Config path

`~/.claude/command-policy.json` and `${CLAUDE_PROJECT_DIR}/.claude/command-policy.json`. No top-level schema or version
key — the file starts directly with its config keys. The key VOCABULARY inside is NOT settled here; it belongs to config
leaf `20260914-213153`.

### Test harness

`cd packages/command-policy/tests && nix-shell --run "pytest -v"` (python313 + pytest + shfmt). `conftest.py` provides
exactly two things: the `lib/` sys.path bootstrap, and a `run_entrypoint(name, args=(), stdin=None, env=None)`
subprocess fixture. It has NO importlib module-loader fixture and must never gain one — wanting to import a `bin/`
entrypoint is the signal that logic has leaked out of `lib/`.

## Related Past Improvements

- `improvement-20260912-215016-shfmt-permissions-self-describing.md` — prior work making `shfmt-permissions` config
  self-describing; relevant precedent for the config-shape decisions in this leaf.
- `improvement-20260429-095508-pluginprogram-shfmt-permissions.md` — original `shfmt-permissions` plugin/program
  scaffolding; the structural template this leaf's package layout supersedes.
