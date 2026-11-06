# Improvement 20261106-122320: Scratchpad as allowed path prefix

## Meta

- Related Ticket: PHPT-582
- Status: planned
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T12:23:26+01:00
- Merge target: main

## This Improvement's Objective

command-policy recognises the session's scratchpad directory deterministically and treats paths inside it as within the
allowed prefixes — effectively the same as if the command ran inside the repository.

## Context / Why This Exists

Every Claude Code session has a private scratchpad directory (today
`/tmp/claude-{uid}/{launch-dir slug}/{session_id}/scratchpad`), and the system prompt tells Claude to put temporary
files there rather than in `/tmp`. command-policy's path containment knows only the boundary (the working tree the
session is in, `Workspace.boundary()`) plus the configured `additionalAllowedPathPrefixes`, so every Bash command
touching the scratchpad — `ls`, `cat`, a redirect into it — is denied as "argument path outside the project/allowed
prefixes". The caller then has to `bypass-policy` a command that would have been auto-approved inside the repository.
Observed live in the planning session itself: `ls /tmp/claude-1001/...` denied.

A static `additionalAllowedPathPrefixes` entry cannot fix this: the path contains the session id, and a broad
`/tmp/claude-{uid}` prefix would admit every other session's scratchpad and task-output files.

**The deterministic source exists:** Claude Code puts `scratchpad_dir` into every command hook's stdin JSON (see
Assumptions). The hook entrypoints simply do not read it today — `bin/command-policy-analyze-bash-command` only reads
`tool_input.command`, and `Workspace.of_this_session()` reads only `CLAUDE_PROJECT_DIR` and the cwd.

## Proposed Approach

(Draft — seam under discussion.) The Bash hook entrypoint reads `scratchpad_dir` from its stdin payload and hands it to
`Workspace`, which adds it to the `PathResolutionContext` as a second containment root next to the boundary.
`is_contained` then admits a path inside the boundary, the scratchpad, or an allowed prefix — so argument-path
validation and redirect validation both pick it up with no per-policy change. Absent/empty/non-absolute `scratchpad_dir`
→ no extra root, exactly today's behaviour (fails closed = deny+hint, never blocks).

Out of scope: Read/Grep/Glob (`decision_for_path` never consults the boundary; Claude Code itself already permits
scratchpad access for those tools).

## Assumptions

- **Claude Code passes the session's scratchpad directory to every command hook in the stdin JSON as `scratchpad_dir`
  (common base fields: hook_event_name, session_id, transcript_path, cwd, scratchpad_dir, prompt_id, permission_mode,
  agent_id, ...), omitted when the scratchpad is disabled, for served/remote calls, and stripped when forwarding to
  cloud sessions.** — confirmed (Read from the claude-code 2.1.316 binary
  (/nix/store/pw9hhdspm85i5ljy9cb965nz517qk9f7-claude-code-2.1.316/bin/.claude-wrapped): base hook input builder returns
  {session_id, transcript_path, cwd, scratchpad_dir: jA()?nR(e.id)??void 0:void 0, ...}; field list Is=[hook_event_name,
  session_id, transcript_path, cwd, scratchpad_dir, ...]. Not yet observed in a live payload — first implementation step
  captures one.)
- **Re-deriving the scratchpad path from the on-disk layout ({CLAUDE_CODE_TMPDIR|TMPDIR|/tmp}/claude-{uid}/{sanitised
  launch dir}/{session_id}/scratchpad) is not deterministic enough to rely on.** — confirmed (Layout observed under
  /tmp/claude-1001 (slug = launch dir with non-alphanumerics replaced by '-', e.g. 'Görlitz' -> 'G-rlitz'; the slug
  stays the LAUNCH dir after EnterWorktree). The binary contains several divergent temp-root resolvers
  (CLAUDE_CODE_TMPDIR, else os.tmpdir(); one ignores TMPDIR on macOS; sandbox uses
  CLAUDE_CODE_TMPDIR||CLAUDE_TMPDIR||/tmp/claude). Undocumented and version-dependent.)
- **Both Bash path-containment checks (allowedCommands argument paths in allowed_command_policy.py and redirect targets
  in redirect_path_validation_policy.py) go through PathResolutionContext.is_contained(path, allowed_prefixes);
  decision_for_path (Read/Grep/Glob) does not use the boundary at all.** — confirmed (grep is_contained lib/\*.py:
  allowed_command_policy.py:206, redirect_path_validation_policy.py:37; lib/path_permission.py matches only allowedPaths
  rules.)
