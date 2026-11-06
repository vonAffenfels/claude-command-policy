# Improvement 20261106-122320: Scratchpad as allowed path prefix

## Meta

- Related Ticket: PHPT-582
- Status: completed
- Created: 2026-11-06
- Updated: 2026-11-06
- Plan started: 2026-11-06T12:23:26+01:00
- Plan finished: 2026-11-06T12:45:34+01:00
- Impl started: 2026-11-06T12:49:28+01:00
- Impl finished: 2026-11-06T12:52:38+01:00
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

**The scratchpad is a second "inside the project" root, not a config entry** (Design Decision "Where the scratchpad
enters the engine").

```
hook stdin {"scratchpad_dir": "/tmp/claude-1001/.../scratchpad", ...}
  └─ hook_envelopes.scratchpad_directory_from_hook_input(input_data)   # None unless an absolute str
       └─ load_config_from_environment(scratchpad_directory=...)
            └─ Workspace.of_this_session(scratchpad_directory=...)
                 └─ Workspace.path_resolution() -> PathResolutionContext(boundary, ..., scratchpad_directory=...)
                      └─ is_contained(path, allowed_prefixes): boundary OR scratchpad OR a prefix
```

1. `PathResolutionContext` gains an optional `scratchpad_directory`, realpath'd once at construction like the boundary.
   `is_contained` admits a path equal to or under it (same `_is_within` sibling guard). It is NOT an anchor for relative
   paths — relative command arguments still resolve against the working directory, config entries against the boundary.
2. `Workspace.__init__` / `of_this_session` take an optional `scratchpad_directory` and pass it into
   `path_resolution()`. `of_this_session` stays the one place reading ambient state; the scratchpad is NOT ambient (it
   comes from hook stdin), so the edge passes it in explicitly.
3. `config_loader.load_config_from_environment(scratchpad_directory=None)` forwards it to `Workspace.of_this_session`.
4. `hook_envelopes.scratchpad_directory_from_hook_input(input_data)` — the one place reading the field: returns the
   value only when it is a non-empty absolute path string, else `None`. Sits beside `path_from_tool_input`.
5. Three entrypoints read it and pass it on: `command-policy-analyze-bash-command` (the actual fix), and
   `command-policy-render-session-start` / `command-policy-render-subagent-start` (so the rendered rules tell the
   session and its subagents that they may use the scratchpad). `command-policy-analyze-path` is NOT touched
   (Read/Grep/Glob never consult the boundary).
6. `Config.explain()` renders one line when the path resolution carries a scratchpad, after the
   `additionalAllowedPathPrefixes` section, e.g.
   `sessionScratchpad: /tmp/claude-1001/.../scratchpad (treated like the project: paths inside it pass path checks)`.
   The `[no parser]` header text (`config.py` `_ALLOWED_COMMANDS_HEADER`) changes "inside the project or an allowed
   prefix" to "inside the project, the session scratchpad, or an allowed prefix".
7. The two containment denial clauses in `lib/reason_renderer.py` (`RedirectOutsideAllowedPaths`,
   `ArgumentPathOutsideAllowedPaths`) name the scratchpad as an allowed location, with STATIC wording:
   - `redirect target outside the project, the session scratchpad and the allowed prefixes: '<target>'`
   - `<program>: argument path outside the project, the session scratchpad and the allowed prefixes: '<path>'`

   Static, not session-dependent (Design Decision "How the denial names the scratchpad"): the clause tells the caller
   where a path WOULD pass, which is routing information (the hint is load-bearing). The caller already knows its own
   scratchpad path from its system prompt; the renderer stays a pure function of the Reason's facts and gets no session
   context.

Absent / empty / relative / non-string `scratchpad_dir` → no scratchpad root → exactly today's behaviour (deny+hint for
paths there; never a block). Both containment consumers — `allowed_command_policy._first_path_outside_allowed_prefixes`
and `RedirectPathValidationPolicy` — pick the scratchpad up through `is_contained` with no change of their own.

Out of scope: Read/Grep/Glob (`decision_for_path` never consults the boundary; Claude Code itself already permits
scratchpad access for those tools).

## Affected Components

- `lib/path_resolution.py` — `PathResolutionContext(..., scratchpad_directory=None)`, `is_contained` admits it, a read
  accessor for `explain()`; module docstring paragraph on the scratchpad root.
- `lib/workspace.py` — `Workspace(..., scratchpad_directory=None)`, `of_this_session(scratchpad_directory=None)`,
  `path_resolution()` passes it; docstring bullet "Scratchpad".
- `lib/config_loader.py` — `load_config_from_environment(scratchpad_directory=None)`.
- `lib/hook_envelopes.py` — `scratchpad_directory_from_hook_input(input_data)`.
- `lib/config.py` — `explain()` scratchpad line; `_ALLOWED_COMMANDS_HEADER` wording.
- `lib/reason_renderer.py` — `_CLAUSE_BUILDERS` entries for `RedirectOutsideAllowedPaths` (line ~98) and
  `ArgumentPathOutsideAllowedPaths` (line ~111). Docstring-only mentions of the old wording, updated alongside:
  `bin/bypass-policy:8`, `lib/escalation_policy.py:33`. No test asserts the old exact text (grep of `tests/`).
- `bin/command-policy-analyze-bash-command`, `bin/command-policy-render-session-start`,
  `bin/command-policy-render-subagent-start` — read the field, pass it to `load_config_from_environment`. The two
  renderers currently discard stdin (`sys.stdin.read()`); they now parse it (malformed JSON → no scratchpad, still
  render).
- `docs/knowledgebase/command-policy-decision-model.md` — "Where the session is: `Workspace`" section gains a
  **Scratchpad** bullet (source = hook stdin, a containment root not an anchor, absent → today's behaviour, why not a
  layout re-derivation / not a config prefix).
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — version 0.9.0 → 0.10.0 (new behaviour), same commit
  as the code.

## Implementation Notes

- **Naming:** `scratchpad_directory` everywhere in Python (domain term from Claude Code's own prompt: "Scratchpad
  directory"); the stdin key stays Claude Code's `scratchpad_dir`, read in exactly one function.
- **realpath:** `/tmp` may be a symlink on some systems (macOS `/tmp` → `/private/tmp`); realpath'ing the scratchpad at
  construction, as the boundary already is, keeps `is_contained` correct. `scratchpad/../../etc/passwd` is already
  normalised by `absolute_path_of_command_argument` before containment.
- **Trust:** `scratchpad_dir` comes from Claude Code itself on the same stdin as `tool_input` — same trust level as the
  command being judged. No other validation beyond "absolute path string".
- **`bypass-policy` / `add-allow-policy` transforms** run inside `decision_for`, so they inherit the scratchpad from the
  same `Config` — no change.
- **Observed during exploration (out of scope):**
  - `explain-policy` and the `add-allow-policy` write side (`lib/add_allow_write.py`) run from the Bash tool with no
    hook stdin, so they cannot know the scratchpad. Consequence: an `add-allow-policy --example` naming a scratchpad
    path passes the hook-side check (`ask`) but would fail the write side's re-check. Rare; accepted.
    `CLAUDE_CODE_SESSION_ID` is in the Bash env, but rebuilding the path from it is exactly the layout re-derivation
    rejected above.

- **Implementation deviations:** manifests were already at 0.10.0 on `main` (an earlier improvement took it), so the
  bump went 0.10.0 → 0.11.0. The docstring mentions in `bin/bypass-policy` / `lib/escalation_policy.py` did not contain
  the old wording; the one actual docstring with it, `lib/reason.py` (`ArgumentPathOutsideAllowedPaths`), was updated.
  Full suite: 1094 passed.

## Test Architecture

`cd tests && nix-shell --run pytest`. Pure rules tested in-memory, the edge via the existing `run_entrypoint` subprocess
fixture (`tests/conftest.py`, used by `tests/test_consumer_entrypoints.py`).

- `tests/test_path_resolution.py` — beside the existing `is_contained` tests:
  `test_is_contained_admits_a_path_under_the_scratchpad_directory`,
  `test_is_contained_rejects_a_longer_sibling_of_the_scratchpad_directory`,
  `test_is_contained_resolves_the_scratchpad_directory_through_the_injected_realpath_predicate`,
  `test_a_relative_command_argument_never_resolves_against_the_scratchpad_directory`.
- `tests/test_workspace.py` — `test_its_path_resolution_contains_the_scratchpad_directory_it_was_given`,
  `test_without_a_scratchpad_directory_only_the_boundary_contains` (in-memory layout, as today).
- `tests/test_hook_envelopes.py` — `scratchpad_directory_from_hook_input`: absolute → returned; absent, JSON `null`
  (what a headless `claude -p` session sends — measured), empty, relative, non-string → `None`.
- `tests/test_reason_renderer.py` — `RedirectOutsideAllowedPaths` and `ArgumentPathOutsideAllowedPaths` render a clause
  naming "the session scratchpad" next to the project and the allowed prefixes, plus the offending path.
- `tests/test_config.py` — `explain()` renders the scratchpad line when the injected `PathResolutionContext` carries
  one, and no such line when it does not.
- `tests/test_consumer_entrypoints.py` (end-to-end through the real hook):
  - `ls <tmp_path>/scratchpad/notes.txt` with `scratchpad_dir` in stdin and an `ls` entry → allow envelope; the same
    stdin without `scratchpad_dir` → deny.
  - `echo hi > <tmp_path>/scratchpad/out.txt` with `scratchpad_dir` → allow (redirect path).
  - A sibling `<tmp_path>/scratchpad-other/x` → deny even with `scratchpad_dir` set.
  - SessionStart / SubagentStart renderers with `scratchpad_dir` in stdin print the `sessionScratchpad:` line; with `{}`
    they still render (existing tests keep passing).

Sketch (fantasy callsites):

```python
context = PathResolutionContext(boundary="/repo", scratchpad_directory="/tmp/claude-1/x/s1/scratchpad")
assert context.is_contained("/tmp/claude-1/x/s1/scratchpad/notes.txt") is True
assert context.is_contained("/tmp/claude-1/x/s2/scratchpad/notes.txt") is False

stdin = json.dumps({"scratchpad_dir": str(scratchpad), "tool_input": {"command": f"ls {scratchpad}/notes.txt"}})
result = run_entrypoint("command-policy-analyze-bash-command", stdin=stdin, env=env)
assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"
```

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
- **The `scratchpad_dir` hook-input field is present live for the main session's PreToolUse(Bash), for a subagent's
  PreToolUse(Bash) (same value as the parent), and for SubagentStart.** — confirmed (Temporary
  PreToolUse(Bash)+SubagentStart capture hook in the main checkout's .claude/settings.local.json (since removed),
  claude-code 2.1.316, 2026-11-06: all captured payloads carried
  scratchpad_dir=/tmp/claude-1001/-home-speckmaier-Projekte-intern-claude-command-policy/307cb844-.../scratchpad,
  including agent_id-tagged subagent calls. Note transcript_path's slug was the WORKTREE's while scratchpad_dir's slug
  is the LAUNCH dir's - further evidence layout re-derivation is fragile. Settings file in
  experiments/hook-capture.settings.json.)
- **SessionStart's hook input also carries `scratchpad_dir`.** — confirmed (Live capture 2026-11-06 (claude-code
  2.1.316): an interactive session spawned in the worktree got SessionStart(source=startup) with
  scratchpad_dir=/tmp/claude-1001/...--claude-worktrees-improvement-20261106-122320/<sid>/scratchpad. A headless 'claude
  -p' session got scratchpad_dir=null and had no scratchpad directory at all - so null/absent must be handled as 'no
  scratchpad' (already the plan's behaviour). Note: this probe's slug was the worktree path because it was LAUNCHED
  there - the slug follows the launch dir.)

## Design Decisions

### Where the scratchpad path comes from

- **Chosen:** the `scratchpad_dir` field Claude Code puts into every command hook's stdin JSON.
- **Rationale:** rationale not captured (operator accepted the recommendation; it is the only source Claude Code itself
  hands over, verified live in this planning session at the operator's request).
- **Rejected alternatives:** re-deriving it from the on-disk layout
  (`{CLAUDE_CODE_TMPDIR|TMPDIR|/tmp}/claude-{uid}/{launch-dir slug}/{session_id}/scratchpad`) — undocumented, several
  divergent temp-root resolvers in the binary, launch-dir slug differs from the transcript slug inside a worktree; a
  static `additionalAllowedPathPrefixes` entry `/tmp/claude-{uid}` — admits every other session's scratchpad and
  task-output files.
- **Date:** 2026-11-06

### Where the scratchpad enters the engine

- **Chosen:** A — a second containment root in `PathResolutionContext` (beside the boundary), supplied by the hook
  entrypoint through `Workspace`, plus a `sessionScratchpad:` line in the SessionStart/SubagentStart rendering.
- **Rationale:** rationale not captured (operator: "A) sounds good").
- **Rejected alternatives:** B — append the scratchpad to the config's `additionalAllowedPathPrefixes` before deciding:
  mixes a per-session fact into config, and `explain()` / rendered rules would show it as if someone had configured it.
- **Date:** 2026-11-06

### How the denial names the scratchpad

- **Chosen:** static wording in both containment clauses — "outside the project, the session scratchpad and the allowed
  prefixes".
- **Rationale:** operator asked for the denial message to mention the scratchpad ("Please include the mention in the
  denial message"). Static wording chosen while planning: the renderer stays a pure function of the Reason's facts, and
  the caller already knows its scratchpad path from its own system prompt.
- **Rejected alternatives:** carrying the actual scratchpad path as a fact on `RedirectOutsideAllowedPaths` /
  `ArgumentPathOutsideAllowedPaths` and printing it (session context would have to reach Policy construction just for
  display, and the clause gets long); mentioning it only when the session has a scratchpad (same plumbing cost, for the
  rare headless case).
- **Date:** 2026-11-06

## Success Criteria

- With the plugin installed, `ls <scratchpad>/x`, `cat <scratchpad>/x` and `echo hi > <scratchpad>/x` are auto-allowed
  in a session and in its subagents, exactly as the same commands on a path inside the repository.
- A path in another session's scratchpad, or a sibling `…/scratchpad-other`, is still denied.
- A hook payload without `scratchpad_dir` (disabled scratchpad, cloud/served call, malformed stdin) decides exactly as
  today.
- The SessionStart/SubagentStart rendered rules name the session scratchpad.
- The argument-path and redirect-target denial messages name the session scratchpad as an allowed location.
- Read/Grep/Glob behaviour is unchanged.
- `cd tests && nix-shell --run pytest` passes; version bumped to 0.10.0 in both manifests in the same commit.

## Implementation TODO

- [x] Update status to in-progress
- [x] `PathResolutionContext` scratchpad root: `lib/path_resolution.py`, tests in `tests/test_path_resolution.py`
- [x] `Workspace` carries the scratchpad into `path_resolution()`: `lib/workspace.py`, `tests/test_workspace.py`
- [x] `scratchpad_directory_from_hook_input`: `lib/hook_envelopes.py`, `tests/test_hook_envelopes.py`
- [x] `load_config_from_environment(scratchpad_directory=...)`: `lib/config_loader.py`
- [x] Bash hook reads the field: `bin/command-policy-analyze-bash-command`; end-to-end allow/deny/redirect/sibling cases
      in `tests/test_consumer_entrypoints.py`
- [x] Rendering: `sessionScratchpad:` line and `[no parser]` header wording in `lib/config.py` (`explain()`,
      `_ALLOWED_COMMANDS_HEADER`), tests in `tests/test_config.py`
- [x] Denial wording: `RedirectOutsideAllowedPaths` / `ArgumentPathOutsideAllowedPaths` clauses in
      `lib/reason_renderer.py` name the session scratchpad; tests in `tests/test_reason_renderer.py`; docstring mentions
      in `bin/bypass-policy` and `lib/escalation_policy.py`
- [x] Renderers parse stdin and pass the field: `bin/command-policy-render-session-start`,
      `bin/command-policy-render-subagent-start`; tests in `tests/test_consumer_entrypoints.py`
- [x] Knowledgebase: Scratchpad bullet in the `Workspace` section of
      `docs/knowledgebase/command-policy-decision-model.md`
- [x] Version bump 0.9.0 → 0.10.0 in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (same commit as
      the code)
- [x] Full suite green: `cd tests && nix-shell --run pytest`
- [x] Update status to completed