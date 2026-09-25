---
name: config
description:
  Change, update, or edit the command-policy permissions/auto-approval config; make a command stop prompting or always
  be allowed; block or restrict a command or path; reduce permission prompts; or answer any question about
  command-policy.json or how the policy decides. Does NOT trigger on an ordinary denial, which routes to
  command-policy:find-auto-allowed-command instead.
user-invocable: true
---

# command-policy Config

Schema reference and change workflow for `command-policy.json`. Load this whenever you are reading, writing, or
explaining command-policy's config - not when a single command was just denied and needs a workaround (that is
`command-policy:find-auto-allowed-command`'s job).

## 1. The model in one screen

- **`allow` is the only outcome that grants.** It runs with no human involved.
- **Everything else is deny+hint - a ROUTING signal, not a block.** "Could not be auto-approved" is not "forbidden". The
  caller retries with something auto-approved, or escalates deliberately.
- **`bypass-policy <command>`** is a one-off escalation to the human for THIS invocation. It does not change the config.
- **`add-allow-policy --scope <user|project> --intent "<why>" "<command>"`** is the durable fix: it proposes a new
  `allowedCommands` entry, shown as a diff, written only once approved.
- **Deny-by-default, with no leniency knobs.** The config can express what IS allowed; it cannot express permissiveness
  beyond that. There is no `defaultDecision`, no fallback mode, nothing that widens the allowlist except an
  `allowedCommands` entry actually vouching for an invocation.

## 2. Where config lives, and the merge

Two layers, both optional:

- `~/.claude/command-policy.json` (user scope)
- `${CLAUDE_PROJECT_DIR}/.claude/command-policy.json` (project scope)

Both are read and merged (`Config.defaults().merged_with(user).merged_with(project)`); neither is required to exist.
**Default to the USER scope** unless the user explicitly asks for a project-scoped change - a project config is usually
meant to be shared/committed, and writing to it without being asked surprises whoever else uses the project.

Merge rules, per key:

- `allowedCommands`, `blockedCommands`, `sensitiveVariables`, `sensitivePaths`, `additionalAllowedPathPrefixes`,
  `allowedPaths` - **union**. A project config can only ADD, never remove something the user config already allows or
  restricts.
- `commandSubstitutionResponse` - **overlay-wins only when the overlay actually SETS it.** An overlay that never
  mentions the key does not silently reset an earlier layer's explicit choice back to the default.

## 3. Changing config (workflow)

1. **Read the effective config first**, via the Bash tool: `explain-policy`. This is the MERGED result, with every
   currently-reachable Warning (both static and, for an external parser, described - see §9).
2. **Also read the raw file(s)** you are about to touch, so you know what is actually there rather than trusting memory
   of a prior read. Never assume a config is empty just because nothing was mentioned recently.
3. **New `allowedCommands` entry → `add-allow-policy`.** Quote the WHOLE entry as one argument - a bare program name, or
   a JSON object matching the entry schema (§Reference: schema). It refuses (denies, before ever showing the ask dialog)
   a proposal whose entry has a static or described problem (§9) - fix the entry and retry rather than arguing with the
   refusal.
4. **Everything else - editing/removing an `allowedCommands` entry, `blockedCommands`, `allowedPaths`,
   `additionalAllowedPathPrefixes`, `sensitive*` - is a direct `Edit` of the JSON file.** `add-allow-policy` can only
   APPEND to `allowedCommands`; it cannot touch any other key or modify/remove an existing entry.
5. **After a direct Edit, the PostToolUse lint hook re-renders `Config.warnings()`** for the merged result and surfaces
   it as a `systemMessage` - read it. It is the same problem-detection Edit/`add-allow-policy` both go through
   (`AllowedCommand.problems()` plus, for external parsers, `Config.described_problems()`), so it catches what a plain
   JSON edit could get wrong that `add-allow-policy`'s own construction would have caught.
6. **Never create a config file full of defaults.** An absent file (or one that mentions only what actually differs from
   the defaults) is the normal, intended state - do not "helpfully" pre-populate every key.

**`bypass-policy` vs. `add-allow-policy`:** if the goal is "let me through this one specific time", use `bypass-policy`.
If the goal is "this KIND of command should just work from now on", use `add-allow-policy` - a caller that only ever
reaches for `bypass-policy` never actually reduces how often it has to escalate.

## 4. Evaluation order and what each objection means

Six passes, in this order; the reason list is primary-objection-first when several apply, but EVERY objecting pass
contributes its own reason, not just the first:

1. `sensitivePaths` - substring match on the raw command TEXT. Deliberately broad (false-positive direction, on
   purpose) - never narrow it to prefix/exact matching.
2. `blockedCommands` - the invoked program itself.
3. `commandSubstitutionResponse: 'deny'` (only when explicitly set that way) - any `$(...)`/backtick anywhere denies,
   unconditionally, before even reaching `allowedCommands`.
4. `sensitiveVariables` - a referenced variable name.
5. Redirect path validation - a shell-performed redirect (`>`, `>>`, ...) landing outside the project or
   `additionalAllowedPathPrefixes`.
6. `allowedCommands` - deny-by-default: no entry vouches.

**Categorical** objections (1, 2, 3 in deny mode, 4, 5) are true regardless of which `allowedCommands` entry is in
play - `bypass-policy` escalates these to `ask` rather than silently waiving them (a redirect the wrapper performs, a
blocked command, or a sensitive path referenced are never something a wrapper program can legitimately vouch for on your
behalf).

**Near-miss** objections (6, and its own several distinct reasons: no entry names the program at all; the program's own
entry didn't vouch for this invocation's shape) are properties of one candidate entry's own vouching attempt -
`bypass-policy` downgrades these to `passthrough` (hands the decision to Claude Code's own permission rules) rather than
forcing `ask`.

## 5. Entries describe command shapes

`allowedCommands` is a list of entries. **Filters AND within one entry; entries OR across the list.** An invocation is
allowed the moment ANY entry fully vouches for it - so two entries for the same program, each covering a different
shape, is normal and often clearer than one entry with an awkward compound filter:

```json
[
  { "program": "xargs", "filters": [{ "type": "optionPresent", "option": "--dry-run", "action": "required" }] },
  { "program": "xargs", "filters": [{ "type": "nestedCommand" }] }
]
```

Every entry that matches the invoked program but does NOT vouch contributes its own reason to the denial - so a
near-miss hint always names a REAL, specific cause, never a generic "no entry worked". Prefer several narrow entries
over one entry with filters scoped so loosely they let more through than intended.

## 6. Variables, substitutions, and unknowable arguments

- **`onlyTheseVariables` vouches for NAMES, never values.** `{"onlyTheseVariables": ["HOME"]}` says this entry accepts a
  `$HOME`/`${HOME}` reference ANYWHERE in the invocation - it says nothing about what `$HOME` actually expands to at
  runtime, and no filter can inspect that either.
- **A `block` filter can never prove absence next to unknowable content** (a variable or a `$(...)` substitution
  anywhere in the invocation). `echo $(echo safe)` denies against a filter forbidding `--dangerous`, even though the
  inner command is itself harmless - nothing static rules out the expansion being exactly that flag.
- **A `required` filter can still be proven from a separate, fully-literal word.** `echo --required $(echo safe)` still
  satisfies a `required optionPresent` filter on `--required` - it is its own complete word, untouched by the
  substitution sharing the line with it.
- **An index-based filter (`argumentAtIndex`/`positionalArgAtIndex`) is defeated once something unknowable PRECEDES
  it** - an expansion of anything other than exactly one word shifts every later index, so a required filter pinned to a
  later position can no longer be proven. An index pinned BEFORE the unknowable content stays provable.
- **The recovery is decomposition, not escalation, when it applies:** run the value-producing command first
  (`project-root`, `git ls-files -m`, ...), read its real output, confirm it's the kind of value you expected, then
  re-issue the original command with that value written in literally as two separate auto-approved invocations. This
  restores static checking - it is not a way around it.

## 7. Path containment

Every argument is a path CANDIDATE by default - unless something rules it out. This is deliberately the maximally strict
starting point:

- **No parser at all → every argument is a candidate**, options included. `ls --color=/etc` and `ls $(echo /etc)` both
  deny unless the entry earns an exemption (below).
- **A `structured` parser → every declared slot is a candidate too, unless it says `path: false` explicitly.** An
  undeclared slot is STILL a candidate (declaring nothing gets you the same strictness as no parser at all).
- **A `provided`/`command` parser → whatever the script's own code decides.** This is the only route with genuine
  program-specific knowledge (`grep $(echo pattern) file` is fine because the parser knows position 0 is a pattern, not
  a path; `cat $(echo file)` still denies because cat's parser calls every positional a file).

Path candidates are checked against the project root plus every `additionalAllowedPathPrefixes` entry, with symlinks
resolved on both sides.

**`hasNoPathParameters: true` is a factual CLAIM the program takes no path operands at all - never a waiver.** Declaring
it falsely (to make a denial go away) is a defect of the same kind as a wrong parser, and an audit of a real config
found exactly this mistake live. It is the ONLY way an entry may carry unknowable content (a variable or substitution)
in an argument slot without a parser that can classify that slot as non-path.

## 8. Problems: what "invalid entry" means, and where it shows up

An `allowedCommands` entry can have a construction-time PROBLEM instead of raising an error - the entry then simply
NEVER vouches for anything, and the problem is reported through the ordinary warnings channel
(`explain-policy`/SessionStart/SubagentStart/the lint hook/`add-allow-policy`'s refusal), never a crashed hook.

- **Static problems** (found with no subprocess): an unrecognised filter `type` or `commandParser.type`, an uncompilable
  regex `pattern`, a retired `structured` key (`optionsWithArguments`/`pathOptions`/`pathPositionals` - use the current
  `options`/`positionals` shape instead, §Reference: parsers), an unresolved `provided` script name, a malformed
  `programGlob`, or an `optionValue`/`nestedCommand` filter naming a capability the entry's own DECLARED parser type
  (default/structured) structurally cannot have.
- **Described problems** (found only for a `provided`/`command` parser, via its own `{"describe": true}` response -
  §Reference: parsers): a `nestedCommand` filter beside a parser that answers "I never publish sub-commands", an
  `optionValue` filter naming an option the parser never populates with a value, a `namedValue` filter naming a value
  the parser never publishes, or the script simply failing to answer the describe protocol correctly at all (a contract
  breach in its own right).
- **A problem entry never vouches, for any invocation, silently** - it is exactly as if the entry were absent, except
  the problem itself is visible through the warnings channel above. `add-allow-policy` refuses (denies, before asking) a
  proposal with either kind of problem, so a human is never asked to approve an entry that would not actually do
  anything.

## Reference: schema

**Top-level keys** (all optional):

| Key                             | Type                                           | Meaning                                                                                                                                             | Merge                                     |
| ------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `allowedCommands`               | list of entries                                | see below                                                                                                                                           | union                                     |
| `blockedCommands`               | list of program names                          | categorical denial if invoked, anywhere                                                                                                             | union                                     |
| `sensitiveVariables`            | list of variable names                         | categorical denial if referenced, anywhere                                                                                                          | union                                     |
| `sensitivePaths`                | list of substrings                             | categorical denial if the raw text contains one                                                                                                     | union                                     |
| `additionalAllowedPathPrefixes` | list of paths (`~` ok)                         | widens the path-containment boundary                                                                                                                | union                                     |
| `allowedPaths`                  | list of `{path, tools}`                        | Read/Grep/Glob's own decision domain - NEVER denies, only allows or abstains                                                                        | union                                     |
| `commandSubstitutionResponse`   | `"deny"` \| `"via-allowed-commands"` (default) | `deny`: any `$(...)`/backtick anywhere denies outright. `via-allowed-commands`: the substituted command is itself checked through the same pipeline | overlay-wins, only if the overlay sets it |

**`allowedCommands` entry** - a bare string (shorthand for `{"program": "<string>"}`) or an object:

| Key                   | Type                          | Meaning                                                                                                                                           |
| --------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `program`             | string                        | exact program name to match (mutually exclusive with `programGlob`)                                                                               |
| `programGlob`         | `{marketplace, plugin, path}` | matches a plugin-bundled script at `{cache_root}/{marketplace}/{plugin}/*/{path}` - `path` must not start with `/`, and no field may contain `..` |
| `filters`             | list of filter objects        | AND-ed; see Reference: filters                                                                                                                    |
| `onlyTheseVariables`  | list of variable names        | the ONLY variable NAMES this invocation may reference anywhere - default: none                                                                    |
| `hasNoPathParameters` | bool (default `false`)        | a factual claim the program takes no path operands - see §7                                                                                       |
| `commandParser`       | parser object (default: none) | see Reference: parsers                                                                                                                            |

**`allowedPaths` entry:** `{"path": "...", "tools": "read"}` (or a list: `["read", "grep"]`). Tool names: `read`,
`grep`, `glob`; `all` expands to all three; `search` expands to `grep`+`glob`.

## Reference: filters

Every filter has a `type` and an `action` (`"block"` (default) or `"required"`). Eight of the ten are a MATCHER (what to
extract and compare) composed with the action; `paths` and `nestedCommand` are their own kind and ignore `action`
entirely.

**Universal rule: a filter sees only what the entry's PARSER produced, not the raw command line.** A filter naming
something the parser never populates does not error - it silently reports the target ABSENT, and absent always FAILS the
filter regardless of `block`/`required` (fail-closed, never fail-open). This is why `optionValue`/`namedValue` filters
are load-bearing to check against the parser's own capabilities (§9) before trusting them.

| Type                   | Compares                                               | Notes                                                                                                                                                       |
| ---------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `parameterRegex`       | regex against ALL arguments joined with spaces         | `{"pattern": "..."}`                                                                                                                                        |
| `matchFullParameter`   | exact membership in the argument list                  | `{"pattern": "exact-value"}`                                                                                                                                |
| `positionalArgRegex`   | regex against positionals only, joined                 | `{"pattern": "..."}`                                                                                                                                        |
| `argumentAtIndex`      | regex against argument N (options + positionals)       | `{"index": N, "pattern": "..."}` - TARGET_ABSENT if out of range                                                                                            |
| `positionalArgAtIndex` | regex against positional N only                        | `{"index": N, "pattern": "..."}` - TARGET_ABSENT if out of range                                                                                            |
| `namedValue`           | regex against a parser-published named value           | `{"name": "...", "pattern": "..."}` - only `provided`/`command` parsers populate `named`                                                                    |
| `optionValue`          | regex against an option's consumed value(s)            | `{"option": "-m", "pattern": "..."}` - needs a parser that DECLARES the option consumes a value (default parser never does)                                 |
| `optionPresent`        | whether an option token appears at all                 | `{"option": "--force"}` - no target-absent state; presence IS the outcome                                                                                   |
| `paths`                | set membership against `exactly`                       | `{"exactly": ["a.txt", "b.txt"]}` (or a bare string) - no `action`; an entry with no detected filtering paths passes vacuously                              |
| `nestedCommand`        | every published sub-command must itself decide `allow` | `{"maxDepth": N}` (optional) - needs a parser that publishes on the `nestedCommands` channel (§Reference: parsers); fails closed when nothing was published |

## Reference: parsers (the knowledge ladder)

No `commandParser` key → **`DefaultParser`**: dash-prefixed word = option (no value ever attached), everything else a
positional. No program-specific knowledge at all, so it can never rule an argument out as a path.

`{"type": "structured", ...}` → **DECLARED knowledge**, one record per slot:

```json
{
  "type": "structured",
  "options": [{ "option": "-m", "arguments": 1, "path": false }, "-v"],
  "positionals": [{ "index": 0, "path": false }],
  "doubleDashStops": true
}
```

- `options`: a bare string is a valueless flag; `{option, arguments, path}` declares how many following tokens it
  consumes (default `0`) and whether its value is a path candidate (default `true`).
- `positionals`: `{index, path}` - `path` defaults to `true`.
- `doubleDashStops` (default `false`): a bare `--` ends option parsing.
- **Retired keys `optionsWithArguments`/`pathOptions`/`pathPositionals` are PROBLEMS, not silently ignored or
  reinterpreted** - rewrite them into `options`/`positionals` records.

`{"type": "provided", "name": "git"}` → a BUNDLED reference script, `parsers/<name>.py`. Currently ships (all answer the
describe protocol below): `awk`, `cat`, `chmod`, `composer`, `find`, `gawk`, `git`, `grep`, `nix`, `nix-shell`, `npm`,
`pnpm`, `sed`, `spawn-claude`, `timeout`, `xargs`, `yarn`. `nix`, `nix-shell`, `timeout`, `xargs` are the wrapper
parsers that can publish on `nestedCommands`; none of the others ever do.

`{"type": "command", "command": "/path/to/script"}` → your OWN script. Contract:

- Receives `{"arguments": [...]}` on stdin; must print JSON on stdout:
  `{"options": [...], "positionals": [...], "named": {...}, "paths": [...], "nestedCommands": [...]}` (the last two
  optional; `nestedCommands` entries are `{"text": "...", "shape": "argv" | "shell"}` - `"argv"` for already-split words
  re-quoted with `shlex`, `"shell"` for a shell-syntax string taken as-is).
- **Also receives `{"describe": true}` on stdin** and must answer
  `{"publishesNestedCommands": bool, "namedValues": [string, ...], "optionsWithValues": [string, ...]}` - the STATIC
  capability answer `optionValue`/`nestedCommand`/ `namedValue` filters are checked against (§9). Any non-zero exit,
  timeout, malformed JSON, or a response missing/mis-shaping one of these three keys is itself a reported problem, never
  silently "capability unknown".

## Reference: escape hatches

- **`bypass-policy <command>`** - recognized ONLY when it is the SOLE statement on the line
  (`Statement. as_sole_invoked_program()`), never a `startswith` prefix check - `bypass-policy true && rm -rf /` does
  NOT escalate the `rm`. Combines the wrapper's own shell-level objections with the wrapped command's ordinary decision:
  if nothing objects, simply `allow`; a categorical objection (blocked command, sensitive path, an out-of-bounds
  redirect) forces `ask` rather than being silently waived; anything else becomes `passthrough`.
- **`add-allow-policy --scope <user|project> --intent "<why>" "<command>"`** - the ONLY accepted grammar; the whole
  proposed command must be ONE quoted argument (an unquoted trailing redirect is performed by the OUTER shell against
  `add-allow-policy`'s own stdout, not by the tool - quoting the whole thing prevents this). Violation codes, each
  denying rather than asking: `redirect_on_invocation`, `shell_touched` (a pipeline, `&&`/`||`/`;`, backgrounding,
  command substitution anywhere, or a variable reference in the entry argument itself), `missing_scope`,
  `duplicate_scope`, `invalid_scope_value`, `missing_intent`, `no_command_argument`, `multiple_command_arguments`. Flag
  ORDER is not fixed - only that each of `--scope`/`--intent`/the command argument appears exactly once.
- **`audit-session-policy`** - reports which Bash commands in a PAST session would not auto-approve under the CURRENT
  merged config; the tool for deciding what to allow-list next from real usage.

## Reference: worked examples

```json
{
  "program": "git",
  "commandParser": { "type": "provided", "name": "git" },
  "filters": [
    { "type": "namedValue", "name": "subcommand", "pattern": "^(status|log|diff|show)$", "action": "required" }
  ]
}
```

Allow-lists `git` for a fixed set of read-only subcommands only.

```json
{
  "program": "sed",
  "commandParser": { "type": "provided", "name": "sed" },
  "filters": [
    { "type": "matchFullParameter", "pattern": "-i", "action": "block" },
    { "type": "parameterRegex", "pattern": "^-i", "action": "block" }
  ]
}
```

`sed` without in-place editing.

```json
{
  "program": "find",
  "commandParser": { "type": "provided", "name": "find" },
  "filters": [
    { "type": "namedValue", "name": "execPresent", "pattern": "^true$", "action": "block" },
    { "type": "namedValue", "name": "deletePresent", "pattern": "^true$", "action": "block" }
  ]
}
```

`find` without `-exec`/`-delete`.

```json
[
  {
    "program": "timeout",
    "commandParser": { "type": "provided", "name": "timeout" },
    "filters": [
      { "type": "namedValue", "name": "command", "pattern": ".+", "action": "required" },
      { "type": "nestedCommand" }
    ]
  }
]
```

`timeout` propagating to its wrapped command - the wrapped command still faces every ordinary check on its own terms.

```json
{
  "program": "my-tool",
  "commandParser": { "type": "structured", "options": [{ "option": "--colors", "arguments": 1, "path": false }] }
}
```

A custom tool whose `--colors` value is a color name, not a path - declared out with `path: false` rather than left to
deny.

```json
{ "path": "/var/log/myapp", "tools": "read" }
```

Under `allowedPaths` - a directory outside the project readable by Read/Grep/Glob, granting nothing to Bash.
