---
name: migrate-config
description:
  Migrate a shfmt-permissions.json config to command-policy.json. Load this whenever the user asks to migrate, upgrade,
  convert, or port their permissions config from shfmt-permissions to command-policy, or asks what changes when
  switching between the two. Purely additive - the old shfmt-permissions.json file(s) are never modified or deleted.
user-invocable: true
---

# Migrate shfmt-permissions Config to command-policy

Translates `~/.claude/shfmt-permissions.json` and/or `${CLAUDE_PROJECT_DIR}/.claude/shfmt-permissions.json` into their
`command-policy.json` equivalents. The translation is SEMANTIC, not textual: some old keys rename, some invert polarity,
some reshape structurally, and four decision knobs cease to exist entirely because command-policy's deny-by-default
model has nothing left for them to configure.

**Nothing is written until you have reviewed the report and confirmed.** The old `shfmt-permissions.json` file(s) are
never modified or deleted, in either mode - this migration is purely additive.

## Procedure

1. **Run the dry run.** Use the Bash tool to run `migrate-config` (no arguments). It prints a JSON report with one entry
   per scope (`user`, `project`):
   - `sourceExists: false` - that scope has no `shfmt-permissions.json`; skip it silently, do not fabricate a migration
     for it.
   - `sourceExists: true` - carries `newConfig` (the migrated config), `warnings` (each `{kind, message, key}`),
     `existingTarget` (the current `command-policy.json` at that scope, or `null`), and `diff` (a unified diff against
     it, or `null` if there is no existing target or it already matches).

2. **Present the report in prose, per scope that has a source:**
   - Summarize what the migrated config allows/blocks/etc. - don't just dump the JSON.
   - **Always surface every warning's message.** In particular, the four `dead_decision_knob_removed` warnings
     (`defaultDecision`, `sensitiveVariableResponse`, `pathValidationResponse`, `filterRejectionResponse`) and their
     shared point: deny-by-default is materially STRICTER than the old shipped default. Say this plainly even when the
     user's old config never set any of the four knobs - they are losing that permissive fallback either way.
   - If any entry used `propagate`, surface the `propagate_reshaped_to_nested_command` warning's risk explicitly: the
     old `namedValue` selector is gone, and the bundled `nix-shell`/`nix`/`timeout` reference parsers do not yet publish
     sub-commands on the channel the new `nestedCommand` filter reads - such an entry may now DENY the wrapped command
     instead of propagating to it, until that parser support lands.
   - If any entry used a `structured` commandParser, surface `structured_parser_defaults_to_path_active` with the same
     prominence as the four `dead_decision_knob_removed` warnings: the migrated parser is materially STRICTER than its
     source - every positional and option value is now a path candidate by default, and only an explicit `path: false`
     on a slot rules it out. Say this plainly even when the entry's old config never used `pathOptions`/
     `pathPositionals` at all - a slot the old engine silently guessed was not a path may now cause that command to
     DENY. If `structured_parser_inert_path_option` also fired, note which option(s) it names: the old config's
     `pathOptions` declaration for that option was already contributing nothing (the value parsed as a stray
     positional), so the migrated declaration is a valueless flag unless the user adds an `arguments` count.
   - If `allowedReadPaths` was present, note it was folded into `allowedPaths` entries (`tools: "read"`) merged with any
     pre-existing ones.
   - If `existingTarget` is not `null`, show the `diff` and make clear that writing will overwrite it.

3. **Confirm before writing.** Use `AskUserQuestion` to ask, per scope that has a source config: proceed with writing
   this scope's `command-policy.json` (overwriting any existing one), or skip it. Never assume; a migration that
   silently overwrites a hand-edited `command-policy.json` is exactly the kind of surprise this confirmation step exists
   to prevent.

4. **Apply.** For each scope the user confirmed, run `migrate-config --write`. Note: `--write` re-runs the FULL
   migration and writes every scope whose source exists - there is no partial/per-scope flag. If the user confirmed only
   some scopes, mention this: writing applies to every scope with a source file, since a source config the user did not
   confirm was presumably not one they wanted written.

5. **Report what changed.** Name the file(s) written and remind the user the old `shfmt-permissions.json` file(s) are
   untouched - both engines can run side by side (though only one PreToolUse hook decides at runtime; consult
   `hooks/hooks.json` if you need to know which one is currently wired up).

## Where to write

Same convention as `shfmt-permissions:config`: default to the user config unless the user explicitly asks for a
project-scoped migration.
