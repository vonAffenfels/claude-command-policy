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

- **Project config file** → `{main repository root}/.claude/command-policy.json`. Main repository root comes from `git`
  (candidate: first `worktree` entry of `git worktree list --porcelain`; to be verified). Never the project dir's
  subpath — always the main repository ROOT.
- **Path-containment boundary** → the root of the worktree the session is working in (`git rev-parse --show-toplevel`
  run from that worktree).

Outside a git repository (or when `git` fails), both fall back to today's `CLAUDE_PROJECT_DIR`/cwd behaviour.

Rules stay database-free in the user's sense: `PathResolutionContext` already receives its root at construction, and the
config loader already receives file paths — only the edge factories (`for_project()`, `load_config_from_environment()`,
`add_allow_write.config_path`, `bin/migrate-config`) change where they get them.

## Implementation Notes

### Open Questions

- (To be discussed) Which directory to ask `git` from. For the config file, `CLAUDE_PROJECT_DIR` suffices (it lies in
  the same repository in all three launch shapes). For the BOUNDARY after `EnterWorktree`, `CLAUDE_PROJECT_DIR` still
  points at the main checkout, so the worktree must come from the session's cwd (hook stdin `cwd` field?). Unmeasured:
  what that `cwd` holds after `EnterWorktree`, and after a Bash `cd` elsewhere — a `cd` into ANOTHER repository must not
  switch the session to that repository's policy.
- (To be discussed) Session launched in a SUBDIRECTORY of the main checkout: boundary becomes the repository root (wider
  than today's subdirectory). Acceptable?

## Assumptions

- **Launched directly inside a linked worktree, hook processes get CLAUDE_PROJECT_DIR = the worktree and stdin cwd = the worktree; a Bash change-directory to /tmp does NOT change the cwd later hooks receive** — confirmed (experiments/hook-cwd/probe.sh B (headless haiku session with a logging PreToolUse hook): all four hook invocations, including those after the change-directory, logged stdin cwd, process PWD and CLAUDE_PROJECT_DIR = the worktree; raw log in experiments/hook-cwd/hook-input.log)

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

### How the main repository is found

- Chosen: ask `git` (a subprocess at the edge).
- Rationale: operator — "do _not_ infer the main repository from some kind of symlink. Just start the proper command to
  get it from git. This kind of hacky 'I can do it smarter' is where lots of bugs come from."
- Rejected alternatives: reading `.git` / `gitdir` / `commondir` files directly to avoid a subprocess.
- Date: 2026-10-19