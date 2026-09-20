# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`command-policy` — a single Claude Code plugin, living alone in this repository. It makes deterministic, rule-based
permission decisions for Bash commands and file-access paths: same input, same verdict, every time, with no model
judgment in the loop.

It is the successor to the `shfmt-permissions` plugin, which still lives in the `vonaffenfels-dev-tools` monorepo.
`shfmt-permissions` stays fully installed and functional for anyone who has not migrated; `command-policy` becomes the
live PreToolUse engine once a user runs `/command-policy:migrate-config`.

## Repository Layout

This repo is simultaneously **the plugin** and **a one-plugin marketplace**:

- `.claude-plugin/plugin.json` — the plugin manifest.
- `.claude-plugin/marketplace.json` — the registry, with a single entry whose `source` is `"./"` (the repo root itself).
  Without it the repo is still a valid plugin, but only loadable per-session via `claude --plugin-dir`; the registry is
  what makes `/plugin marketplace add vonAffenfels/claude-command-policy` and version-gated updates work.
- `lib/` — **all real code**. A flat `sys.path` directory, NOT a package: modules are imported as `import config`, never
  `import lib.config`.
- `parsers/` — per-program argument parsers (`git`, `npm`, `sed`, `find`, …), invoked as external processes.
- `agents/` — currently one, `find-auto-allowed-command` (see below).
- `bin/` — a thin layer holding **ALL** entrypoints. Four user-facing (`bypass-policy`,
  `add-allow-policy --scope user|project`, `explain-policy`, `audit-session-policy`) and five hook-invoked
  (`command-policy-analyze-bash-command`, `command-policy-analyze-path`, `command-policy-render-session-start`,
  `command-policy-render-subagent-start`, `command-policy-lint-config-on-write`). The hook-invoked five are prefixed
  because plugin `bin/` is APPENDED to PATH and a generic name can be shadowed.
- `hooks/hooks.json` — PreToolUse (Bash, Read, Grep, Glob), SessionStart, SubagentStart, PostToolUse (Write|Edit). Hook
  processes reference their entrypoints via `${CLAUDE_PLUGIN_ROOT}/bin/...`; a skill body never does, because that
  variable does not exist in the Bash tool environment.
- `docs/knowledgebase/` — concept articles. `docs/improvements/` — the improvement history that produced this plugin.

**There is deliberately NO `scripts/` directory.** Everything executable is an entrypoint, and entrypoints live in
`bin/`.

## The Decision Engine

`Config.from_dict(cfg).decision_for(command)` in `lib/config.py` is the settled public entrypoint, alongside its
Read/Grep/Glob counterpart `Config.decision_for_path(tool_name, path)`. The `Config` value object owns construction,
copy-on-write merge, structured layer-provenance warnings, and a deny-by-default-oriented `explain()` that states
plainly when no config file was found at either scope, rather than rendering output indistinguishable from a
present-but-empty config.

Config lives at `~/.claude/command-policy.json` and `${CLAUDE_PROJECT_DIR}/.claude/command-policy.json`, with no
top-level version key.

A denial's rendered reason ends with an unconditional pointer to the `command-policy:find-auto-allowed-command` AGENT
(`agents/`, dispatched via Task from empty context, `tools: Read` only — so it structurally cannot shell out to
`explain-policy` or invoke `Config.decision_for` itself). It reasons over the rendered rules already injected into its
own context at dispatch and proposes an auto-approved alternative.

## Version Bumps Are Load-Bearing

Plugin files are cached on user machines, and the cache invalidates on **version change in `marketplace.json`** and
nothing else. Any commit that modifies plugin content must bump the version in **both** `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` in that same commit — splitting the bump into a follow-up leaves the first commit
effectively invisible to users.

## Tests

```bash
cd tests && nix-shell --run pytest
```

Python 3 and `shfmt` are assumed runtime dependencies; `tests/shell.nix` provides both.
