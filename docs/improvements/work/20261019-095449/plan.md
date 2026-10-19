# Improvement 20261019-095449: Resolve project config to the main worktree

## Meta

- Related Ticket: None
- Status: planned
- Created: 2026-10-19
- Updated: 2026-10-19
- Plan started: 2026-10-19T09:55:20+02:00
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

## Proposed Approach (draft)

One edge-level value object owns "which repository/worktree is this session in", built ONCE from `git` output, and every
site listed under Context consumes it instead of re-deriving paths from `CLAUDE_PROJECT_DIR`/`getcwd()`. It answers two
questions:

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

Rules stay database-free in the user's sense: `PathResolutionContext` already receives its root at construction, and the
config loader already receives file paths — only the edge factories (`for_project()`, `load_config_from_environment()`,
`add_allow_write.config_path`, `bin/migrate-config`) change where they get them.

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

## Implementation Notes

### Resolved during planning

- Which directory to ask `git` from — measured (see Assumptions, `experiments/hook-cwd/`): config from the launch dir,
  boundary from the process cwd, as described in Proposed Approach.
- Session launched in a SUBDIRECTORY of the main checkout: the boundary becomes the repository root. Operator: "if you
  are working inside a project then you actually want to work on that project." Monorepos with per-package rules are not
  a current use case; explicitly out of scope.

- Splitting `PathResolutionContext._cwd` into relative-path base and boundary: in scope (operator: "yes please").
- Boundary when cwd is in a different repository: current git root wins, else `CLAUDE_PROJECT_DIR` (Design Decisions).

### Open Questions

- (To be discussed) Relative paths written in the CONFIG (`paths` filter `exactly`, allowedPaths rules, relative
  `additionalAllowedPathPrefixes`): anchor at the boundary root (proposed), not the process cwd. An existing spec test
  pins exactly this for the project dir — `tests/test_permission_decisions.py:1875`
  `test_a_relative_paths_filter_entry_resolves_against_the_project_not_the_process_cwd` (Flag List D4: "resolving
  against the process cwd would make the filter's meaning depend on where the user happened to be standing"). So the
  split is really three-way: command-side relative → process cwd; config-side relative → boundary root; containment →
  boundary root.

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

### How the main repository is found

- Chosen: ask `git` (a subprocess at the edge).
- Rationale: operator — "do _not_ infer the main repository from some kind of symlink. Just start the proper command to
  get it from git. This kind of hacky 'I can do it smarter' is where lots of bugs come from."
- Rejected alternatives: reading `.git` / `gitdir` / `commondir` files directly to avoid a subprocess.
- Date: 2026-10-19
