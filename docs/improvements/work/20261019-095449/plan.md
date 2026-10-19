# Improvement 20261019-095449: Resolve project config to the main worktree

## Meta

- Related Ticket: None
- Status: ready-to-implement
- Created: 2026-10-19
- Updated: 2026-10-19
- Plan started: 2026-10-19T09:55:20+02:00
- Plan finished: 2026-10-19T12:58:53+02:00
- Merge target: main

## This Improvement's Objective

Inside a git repository, the main repository wins over `CLAUDE_PROJECT_DIR`: every command-policy component that reads
or writes the project-scope config uses `{main repository root}/.claude/command-policy.json`, whether the session was
launched in the main checkout, launched directly in a linked worktree (`--workdir`), or entered one via `EnterWorktree`.
The path-containment boundary becomes the worktree the session is actually working in, matching what Claude Code itself
enforces there. Outside a git repository, today's `CLAUDE_PROJECT_DIR`-based behaviour is kept for both.

## Context / Why This Exists

Operator report (2026-10-19): command-policy behaves differently depending on how a session got into a worktree.

- Session launched in the main checkout, then `EnterWorktree`: hooks keep `CLAUDE_PROJECT_DIR` = launch dir, so the MAIN
  checkout's `.claude/command-policy.json` is used (desired).
- Session launched directly inside the worktree: `CLAUDE_PROJECT_DIR` = the worktree, whose `.claude/` normally has NO
  `command-policy.json` (the file is typically untracked — in this very repo it is not in `git ls-files`), so the
  project layer silently disappears.

Operator's proposed direction: when inside a repository, explicitly use `{main worktree}/.claude/command-policy.json`;
otherwise keep `{project dir}/.claude/command-policy.json`. Also expected to touch the helper commands.

### Measured during planning

- Every project-config path site, each with its OWN copy of the resolution rule:
  - `lib/config_loader.py:40-48` `load_config_from_environment` — `CLAUDE_PROJECT_DIR` or `"."`. Used by all hook
    entrypoints and `explain-policy`.
  - `lib/add_allow_write.py:39-45` `config_path(scope)` — `CLAUDE_PROJECT_DIR` or `os.getcwd()`.
  - `bin/migrate-config:39-47` — two functions, `CLAUDE_PROJECT_DIR` or `os.getcwd()`, for both the source
    `shfmt-permissions.json` and the target `command-policy.json`.
  - `lib/escalation_policy.py:285-287` — display-only string `${CLAUDE_PROJECT_DIR}/.claude/command-policy.json` in the
    add-allow `ask` diff.
  - `skills/config/SKILL.md:34`, `skills/migrate-config/SKILL.md:12` — documentation of the location.
- `CLAUDE_PROJECT_DIR` is NOT set in the Bash tool environment (checked with `env` inside this planning worktree). So
  `add-allow-policy --scope project` and `migrate-config`, which run via the Bash tool, fall back to `os.getcwd()`.
  After `EnterWorktree` that cwd is the worktree, which means TODAY, even in the "good" EnterWorktree case,
  `add-allow-policy --scope project` writes to the WORKTREE's config while the hooks read the MAIN checkout's — the
  approved entry never takes effect. This is an existing bug the fix must cover, not only the launch-in-worktree case.
- A linked worktree's `.git` is a FILE: `gitdir: <main>/.git/worktrees/<name>`. Reading these files to find the main
  repository was REJECTED by the operator — the main repository is obtained from a `git` command (see Design Decisions).
- `PathResolutionContext.for_project()` (`lib/path_resolution.py:69-76`) also roots at `CLAUDE_PROJECT_DIR` — but that
  is the path-containment BOUNDARY, a separate concern from where the config file lives. Not in this improvement's scope
  unless the operator decides otherwise (see Open Questions).

## Proposed Approach

### Concepts

- **`Workspace`** (value object, NEW, `lib/workspace.py`) — where this session is: the project config file, the boundary
  root, and the working directory. Constructed from plain values (`launch_directory`, `working_directory`) plus an
  injected `RepositoryLayout` port, so the priority rules below are exercised with an in-memory layout and no `git`.
  `Workspace.of_this_session()` is the ONE edge factory reading `CLAUDE_PROJECT_DIR` / `os.getcwd()` and wiring the real
  `git` port; every site in Affected Components goes through it. Name is a proposal — the operator may rename.
- **`RepositoryLayout`** (integration port, NEW) — two questions answered by `git`, `None` outside a repository or on
  any `git` failure: `main_repository_root(directory)` (first `worktree ` line of
  `git -C <dir> worktree list --porcelain`) and `working_tree_root(directory)`
  (`git -C <dir> rev-parse --show-toplevel`). `GitRepositoryLayout` is the only place `subprocess` runs `git`; tests of
  `Workspace` use an in-memory `RepositoryLayout` (a fake of OUR port, not a mock of `subprocess`), and
  `GitRepositoryLayout` gets its own contract tests against real temp repositories.
- **`PathResolutionContext`** (existing) — gains the split: `boundary` (containment root AND anchor for config-side
  relative paths) and `working_directory` (anchor for command-side relative paths). Two resolution methods named by
  WHOSE path it is (e.g. `absolute_path_of_command_argument` / `absolute_path_of_config_entry`); the existing
  `absolute_path_of` is removed so no call site keeps an ambiguous anchor. `working_directory` defaults to `boundary`,
  so the ~40 existing `PathResolutionContext(cwd=...)` test constructions only need the keyword rename.

Fantasy callsites:

```python
workspace = Workspace.of_this_session()
config = load_config(user_config_path, workspace.project_config_file(), workspace.path_resolution())

workspace = Workspace(launch_directory="/repo/.claude/worktrees/wt", working_directory="/repo/.claude/worktrees/wt/docs",
                      repository_layout=InMemoryRepositoryLayout(main_root="/repo", working_tree_root="/repo/.claude/worktrees/wt"))
assert workspace.project_config_file() == Path("/repo/.claude/command-policy.json")
assert workspace.boundary() == "/repo/.claude/worktrees/wt"

context = PathResolutionContext(boundary="/wt", working_directory="/wt/docs")
assert context.absolute_path_of_command_argument("../x") == "/wt/x"
assert context.absolute_path_of_config_entry("notes.txt") == "/wt/notes.txt"
```

### Rules

- **Project config file** → `{main repository root}/.claude/command-policy.json`. Main repository root = first
  `worktree ` line of `git -C <launch dir> worktree list --porcelain`, where launch dir = `CLAUDE_PROJECT_DIR`, else
  `os.getcwd()` (the Bash-tool helpers, where `CLAUDE_PROJECT_DIR` is unset but cwd is inside the session's worktree).
  Asked from the LAUNCH dir, never the current cwd: cwd follows Bash `cd`, and a `cd` into a nested independent repo
  (e.g. a vendored checkout inside the boundary — allowed) would otherwise switch the session to that repo's policy.
  Never the project dir's subpath — always the main repository ROOT.
- **Path-containment boundary**, in priority order (operator decision, see Design Decisions):
  1. the current git root — `git -C <process cwd> rev-parse --show-toplevel` (process cwd = hook stdin `cwd`; measured
     identical). Whichever worktree or main checkout the session is in; its ROOT, so a `cd` into a subdirectory does not
     shrink it. No same-repository check.
  2. `CLAUDE_PROJECT_DIR` (the directory Claude started in) when the process cwd is not inside a git repository; in the
     Bash-tool helpers, where it is unset, `os.getcwd()`.
- **Relative-path base** → the process cwd. Today `PathResolutionContext._cwd` is BOTH the relative-path base and the
  boundary (`lib/path_resolution.py:53,91,113`), and both are `CLAUDE_PROJECT_DIR`. Once the boundary is the worktree
  root and cwd can be a subdirectory, these must be two separate fields: `cat ../x` after `cd docs` resolves against
  `<worktree>/docs`, not against the worktree root. (Today's conflation only ever fails CLOSED — the real cwd is always
  at or below the assumed one — but it gives false denials after `EnterWorktree`/`cd`.)

Outside a git repository (`git` exit 128, or `git` missing/failing), all three fall back to today's
`CLAUDE_PROJECT_DIR`/cwd behaviour.

`git` runs as a subprocess on every hook invocation (two calls). Accepted per operator decision; the cost is to be
noted, not optimised away by reading `.git` files.

- **Relative paths written in the CONFIG** (`paths` filter `exactly`, allowedPaths rules, relative
  `additionalAllowedPathPrefixes`) → the boundary root. Keeps D4 (`tests/test_permission_decisions.py:1875`): a config
  entry's meaning must not depend on where the session happens to stand. Inside a worktree, `exactly: ["notes.txt"]`
  means THAT worktree's `notes.txt`.

Rules stay free of ambient state: `PathResolutionContext` and `Workspace` receive everything at construction; only
`Workspace.of_this_session()` (and `GitRepositoryLayout`) touch the environment, cwd and `git`.
`PathResolutionContext.for_project()` becomes a delegation to it (or is removed in favour of it — implementer's call,
keep one name).

## Affected Components

- `lib/path_resolution.py` — `PathResolutionContext`: split `_cwd` into a boundary root and a relative-path base;
  `for_project()` obtains both from the new resolver.
- NEW edge module (name TBD) — the `git`-backed resolver: main repository root (from the launch dir), current git root
  (from the process cwd), fallbacks. Subprocess lives here only, injected like `ExternalParserFactory`.
- `lib/config_loader.py` — `load_config_from_environment` project config path.
- `lib/add_allow_write.py` — `config_path("project")`.
- `bin/migrate-config` — source `shfmt-permissions.json` and target `command-policy.json` paths.
- `lib/escalation_policy.py:285-287` — the displayed project config path in the add-allow `ask` diff.
- Relative-path call sites, classified by WHOSE relative path it is:
  - command-side (relative to where the command runs → process cwd): `lib/default_parser.py:97,106,108`,
    `lib/structured_parser.py:172-222`, `lib/redirect_path_validation_policy.py:36`, `lib/path_permission.py:38` (the
    tool's target path).
  - config-side (relative to the project → boundary root, see Open Questions): `lib/paths_filter.py:25` (`exactly`
    entries), `lib/path_permission.py:52` (allowedPaths rule), `PathResolutionContext.is_contained`'s
    `additionalAllowedPathPrefixes`.
- Docs: `skills/config/SKILL.md:34`, `skills/migrate-config/SKILL.md:12`,
  `docs/knowledgebase/command-policy-decision-model.md` (the `PathResolutionContext` paragraphs), `CLAUDE.md` ("Config
  lives at …").
- `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` — version bump in the same commit.
- `tests/shell.nix` — add `pkgs.git` (today only python313, pytest, shfmt; the impure shell inherits PATH, so `git`
  works by accident).
- `CLAUDE.md` "Tests" paragraph — `git` joins Python 3 and `shfmt` as an assumed runtime dependency (absent `git`
  degrades to the non-repository fallback, never an error).

## Implementation Notes

### Resolved during planning

- Which directory to ask `git` from — measured (see Assumptions, `experiments/hook-cwd/`): config from the launch dir,
  boundary from the process cwd, as described in Proposed Approach.
- Session launched in a SUBDIRECTORY of the main checkout: the boundary becomes the repository root. Operator: "if you
  are working inside a project then you actually want to work on that project." Monorepos with per-package rules are not
  a current use case; explicitly out of scope.

- Splitting `PathResolutionContext._cwd` into relative-path base and boundary: in scope (operator: "yes please").
- Boundary when cwd is in a different repository: current git root wins, else `CLAUDE_PROJECT_DIR` (Design Decisions).

- Config-side relative paths anchor at the boundary root, command-side at the working directory (Design Decisions).

### Risks for the implementation

- Test-suite ambient state: `Config(...)`/`Config.from_dict` default to `PathResolutionContext.for_project()`
  (`lib/config.py:118,129`), which will now run `git` against the PROCESS cwd. Any test that sets `CLAUDE_PROJECT_DIR`
  without also `chdir`-ing (i.e. not using `cwd_pinned_inside_project`) runs with cwd = `tests/`, inside THIS
  repository, and its boundary silently becomes this repository's root. Audit such tests; the conftest Flag List F1 note
  describes exactly this class of false-green.
- Subprocess cost: two `git` calls per `for_project()`; ~600 tests, many of which build a default `Config`. Measure
  suite time before/after.

### Known consequences of the boundary rule (accepted)

- `cd` into a NESTED independent repository inside the project (e.g. a vendored checkout with its own `.git`) shrinks
  the boundary to that nested repository: paths elsewhere in the project then deny until the session `cd`s back. Fails
  closed (false denials), never open.
- The cwd cannot otherwise leave the boundary: command-policy denies a `cd` outside it, and `bypass-policy cd …` cannot
  work at all — `cd` is a shell builtin and `bypass-policy` runs its argument as a subprocess (measured:
  `bypass-policy cd /tmp` → exit 127, "No such file or directory"). The remaining route is a `cd` into an
  `additionalAllowedPathPrefixes` entry; if that prefix is itself a git repository, the boundary becomes it.

## Test Architecture

Run: `cd tests && nix-shell --run pytest` (CLAUDE.md). TDD via the `tdd` skill; record suite runtime BEFORE the first
change (see Risks).

1. **`tests/test_workspace.py` (NEW) — the priority rules, no `git`.** `Workspace` with an in-memory `RepositoryLayout`:
   - launched in main checkout, cwd main → config `<main>/.claude/command-policy.json`, boundary `<main>`
   - launched in main checkout, cwd in a linked worktree (after `EnterWorktree`) → config main, boundary worktree
   - launched in a worktree (`CLAUDE_PROJECT_DIR` = worktree) → config main, boundary worktree
   - cwd in a worktree SUBDIRECTORY → boundary is the worktree ROOT, working directory the subdirectory
   - launched in a subdirectory of the main checkout → config at the main ROOT, not the subdirectory
   - cwd in a nested independent repository → boundary = that repository; config still from the launch dir's main
   - not a repository → config `<launch dir>/.claude/command-policy.json`, boundary = launch dir
   - launch dir in a repository but cwd outside any → boundary = launch dir (priority 2)
2. **`tests/test_repository_layout.py` (NEW) — contract tests of `GitRepositoryLayout` against REAL temp repositories**
   (pytest `tmp_path`; `git init`, `git worktree add`), mirroring `experiments/git-commands/probe.sh`: main root, main
   subdir, linked worktree inside and outside the main checkout, worktree subdir, nested independent repo, not a repo (→
   `None`). Needs `git` in `tests/shell.nix` — check it is there; add if not. New fixture in `conftest.py` (e.g.
   `repository_with_linked_worktree`) for reuse by 3.
3. **Entrypoint tests — end-to-end through `bin/`** (extend `tests/test_consumer_entrypoints.py` /
   `test_escalation_entrypoints.py`, using the fixture from 2):
   - `command-policy-analyze-bash-command` run with `CLAUDE_PROJECT_DIR` = linked worktree, config ONLY in the main
     checkout → the main checkout's allow entry applies (the operator's original bug).
   - same, with cwd = linked worktree and `CLAUDE_PROJECT_DIR` = main checkout (the EnterWorktree shape) → a path in the
     MAIN checkout outside the worktree is now outside the boundary.
   - `add-allow-policy --scope project` run with cwd = linked worktree and NO `CLAUDE_PROJECT_DIR` → writes the MAIN
     checkout's config (the measured existing bug).
   - `migrate-config` same shape → reads/writes the main checkout's files.
4. **`tests/test_path_resolution.py` — the split.** Command argument `../x` with working directory `/wt/docs` → `/wt/x`;
   config entry `notes.txt` → `/wt/notes.txt`; containment uses the boundary, not the working directory.
5. **Spec suite `tests/test_permission_decisions.py`** — add, next to D4: a relative command argument after `cd sub`
   resolves against the subdirectory (allowed inside, denied when `..` escapes the boundary root). D4 itself must stay
   green UNCHANGED.

Isolation rule for every new test: pin BOTH `CLAUDE_PROJECT_DIR` and cwd (`cwd_pinned_inside_project`), never inherit
pytest's cwd — which lives inside THIS repository and would silently become the boundary.

## Assumptions

- **Launched directly inside a linked worktree, hook processes get CLAUDE_PROJECT_DIR = the worktree and stdin cwd = the
  worktree; a Bash change-directory to /tmp does NOT change the cwd later hooks receive** — refuted (First probe was
  invalid: command-policy itself DENIED the change-directory to /tmp (PreToolUse logged, no PostToolUse), so it never
  ran. Re-run B2 with an allowed change-directory into docs: every later hook got stdin cwd = <worktree>/docs. A Bash
  change-directory DOES persist into the hook cwd. Launch values (CLAUDE_PROJECT_DIR = worktree, initial cwd = worktree)
  do hold.)
- **Launched in the main checkout then EnterWorktree: from then on hooks get stdin cwd = the new worktree and process
  PWD = the new worktree, while CLAUDE_PROJECT_DIR stays the main checkout; ExitWorktree restores cwd to the main
  checkout** — confirmed (experiments/hook-cwd/probe.sh A3 run by the operator from the main checkout: PostToolUse of
  EnterWorktree and every later hook logged cwd = .claude/worktrees/hook-cwd-probe with CLAUDE_PROJECT_DIR = main
  checkout; PostToolUse of ExitWorktree logged cwd = main checkout. Log: experiments/hook-cwd/hook-input.log)
- **Hook stdin cwd follows Bash change-directory commands, so it can be a SUBDIRECTORY of the worktree (or, via
  bypass-policy, somewhere outside it); the worktree root must be derived from it via git, never used raw** — confirmed
  (experiments/hook-cwd/probe.sh B2: after an allowed change-directory into docs, PreToolUse/PostToolUse hooks logged
  cwd = <worktree>/docs. A change-directory outside the boundary is denied by command-policy itself (A3, B: no
  PostToolUse logged), so leaving the worktree needs a bypass-policy escalation.)
- **The first worktree entry of the porcelain worktree listing is the main repository root, and show-toplevel is the
  containing worktree root, for: main root, main subdir, linked worktree inside or outside the main checkout, and its
  subdir. Both exit 128 outside a repository. A nested independent repo answers with ITSELF for both.** — confirmed
  (experiments/git-commands/probe.sh against a throwaway repo in the session scratchpad (git 2.55.0); rerun the script
  to reproduce)

## Design Decisions

### Worktree has its own command-policy.json

- Chosen: use ONLY the main repository's `.claude/command-policy.json`; a worktree's own copy is ignored.
- Rationale: operator — "use only the main checkout"; "main repository wins over CLAUDE_PROJECT_DIR".
- Rejected alternatives: worktree file first, else main (two sessions on one worktree could diverge again); layering
  both (third provenance layer, most complex).
- Date: 2026-10-19

### Project dir subpath

- Chosen: always `{main repository ROOT}/.claude/command-policy.json`; the project dir's subpath is NOT carried over.
- Rationale: operator — `CLAUDE_PROJECT_DIR` "is the perpetrator": it stays on the main repository when launched there,
  but points at the worktree when launched with `--workdir`, finding no or the wrong config. "Absolutely don't keep this
  subfolder."
- Rejected alternatives: mirroring the project dir's subpath into the main checkout.
- Date: 2026-10-19

### Path-containment boundary

- Chosen: the boundary becomes the worktree the session is working in.
- Rationale: operator — "This does double duty since claude-code itself already enforces this while inside a worktree so
  the session will get the correct hint if we fix this."
- Rejected alternatives: leaving the boundary on `CLAUDE_PROJECT_DIR` (out of scope).
- Date: 2026-10-19

### Boundary priority

- Chosen: (1) current git root of the process cwd — worktree or main checkout, wherever the session is; (2)
  `CLAUDE_PROJECT_DIR`, "the directory claude started in", when not inside a git repository.
- Rationale: operator — boundary "should be in list of priority: current git root (worktree, main repo depending on
  where we are), CLAUDE_PROJECT_DIR - this should be the directory claude started in and should always be present".
- Rejected alternatives: accept the cwd's git root only when it belongs to the same main repository as the config, else
  fall back to the launch dir's toplevel (Claude's proposal).
- Date: 2026-10-19

### Separate relative-path base from boundary

- Chosen: `PathResolutionContext` gets two fields — relative paths resolve against the process cwd, containment checks
  against the boundary.
- Rationale: operator — "yes please" after the measurement that cwd follows Bash `cd`; with the boundary moving to the
  worktree ROOT, one field can no longer serve both.
- Rejected alternatives: keep one field (relative paths after `cd sub` would resolve against the wrong directory).
- Date: 2026-10-19

### Anchor for relative paths: config vs. command

- Chosen: relative paths in a COMMAND (arguments, redirect targets, the Read/Grep/Glob target) resolve against the
  working directory; relative paths in the CONFIG (`paths` `exactly`, allowedPaths rules, allowed prefixes) resolve
  against the boundary root.
- Rationale: operator — "Good split between config and command. Please do that". Keeps the existing D4 spec
  (`test_a_relative_paths_filter_entry_resolves_against_the_project_not_the_process_cwd`).
- Rejected alternatives: everything against the working directory (config meaning would drift with `cd`, breaks D4);
  everything against the boundary root (wrong for `cat ../x` after `cd sub`).
- Date: 2026-10-19

### How the main repository is found

- Chosen: ask `git` (a subprocess at the edge).
- Rationale: operator — "do _not_ infer the main repository from some kind of symlink. Just start the proper command to
  get it from git. This kind of hacky 'I can do it smarter' is where lots of bugs come from."
- Rejected alternatives: reading `.git` / `gitdir` / `commondir` files directly to avoid a subprocess.
- Date: 2026-10-19

## Success Criteria

- A session launched directly in a linked worktree uses the main checkout's `.claude/command-policy.json` (entrypoint
  test 3a green; manually: `explain-policy` from a worktree-launched session lists the main checkout's rules).
- After `EnterWorktree`, the boundary is the worktree: a path in the main checkout outside the worktree is outside the
  boundary; paths inside the worktree are inside.
- `add-allow-policy --scope project` and `migrate-config` run from a worktree write the main checkout's file.
- After `cd sub`, a relative command argument resolves against `sub`; relative config entries still resolve against the
  boundary root (D4 green unchanged).
- Outside a git repository, behaviour is identical to today (existing suite green without edits beyond the `cwd=` →
  `boundary=` keyword rename).
- No `absolute_path_of` call site remains with an ambiguous anchor; no code outside `GitRepositoryLayout` runs `git`; no
  code outside `Workspace.of_this_session()` reads `CLAUDE_PROJECT_DIR` for path purposes.
- Suite runtime increase measured and reported.

## Implementation TODO

- [ ] Update status to in-progress
- [ ] Record baseline: `cd tests && nix-shell --run pytest` result and wall time
- [ ] Add `pkgs.git` to `tests/shell.nix`; add a `conftest.py` fixture building a main repo with a linked worktree
      (inside `.claude/worktrees/`), a nested independent repo and a non-repo directory
- [ ] `RepositoryLayout` port + `GitRepositoryLayout` with contract tests (Test Architecture 2)
- [ ] `Workspace` value object with in-memory-layout tests (Test Architecture 1), incl. `Workspace.of_this_session()`
- [ ] Split `PathResolutionContext` into `boundary` / `working_directory`; replace `absolute_path_of` with the
      command-side / config-side methods; rename `cwd=` in existing tests (Test Architecture 4)
- [ ] Route every command-side call site (`default_parser`, `structured_parser`, `redirect_path_validation_policy`,
      `path_permission.py:38`) and config-side call site (`paths_filter`, `path_permission.py:52`, allowed prefixes) to
      the matching method; add the spec-suite cases (Test Architecture 5)
- [ ] Wire `Workspace.of_this_session()` into `config_loader.load_config_from_environment`, `PathResolutionContext`'s
      production factory, `add_allow_write.config_path`, `escalation_policy` (proposal validation context + displayed
      path), `bin/migrate-config`
- [ ] Entrypoint tests (Test Architecture 3)
- [ ] Audit tests that set `CLAUDE_PROJECT_DIR` without pinning cwd (Risks); fix any that now resolve against this
      repository
- [ ] Measure suite runtime against the baseline; report
- [ ] Docs: `skills/config/SKILL.md`, `skills/migrate-config/SKILL.md`, `CLAUDE.md` (config location + `git`
      dependency), knowledgebase article's `PathResolutionContext` paragraphs (load `knowledgebase:philosophy` first)
- [ ] Bump version in `.claude-plugin/plugin.json` AND `.claude-plugin/marketplace.json` in the same commit as the
      content change
- [ ] Update status to completed