# claude-command-policy

A Claude Code plugin that auto-approves commands from a list of policies rather than relying on auto-accept mode.

It uses [shfmt](https://github.com/patrickvane/shfmt) to parse the BASH tool script into an AST - then appplies your
policies to it to see if we can auto allow the command. If a command can't be auto allowed claude is guided towards
using an equivalent auto allowed command instead - only falling back to a user prompt if claude really can't get its job
done with the current toolset.

## DISCLAIMER

As of right now I'm just one guy with the idea that I'd rather not ask the wolf how to secure the sheeps den by using
auto mode. I've spent quite a bit of time and ideas on this but I don't claim this to be absolutely fool (ai) proof.

Also: yes this is written by claude-code obviously - if I wasn't going to use it then I would not need this plugin. So
it's still somewhat asking the wolf but at least we can inspect the fence instead of trusting it to build a good one
night after night after night.

## Install

```bash
/plugin marketplace add vonAffenfels/claude-command-policy
/plugin install command-policy@claude-command-policy
```

To develop against a local checkout instead:

```bash
claude --plugin-dir /path/to/claude-command-policy
```

## Tests

```bash
cd tests && nix-shell --run pytest
```

Python 3 and `shfmt` are assumed runtime dependencies; `tests/shell.nix` provides both.

## The guidance concept

A command that can't get auto approved gets 'denied' with a reason telling claude why it was denied. Usually a near miss
because some kind of variable or command substitution makes it impossible to statically analyze the command. Claude can
then:

- fix the command itself - usually by calling the inner substitude command which gets auto allowed, then statically
  calling the outer command with the result
- call an agent to help it look for an equivalent command in the list of auto allowed commands
- prefix the command with `bypass-policy` (argv form, e.g. `bypass-policy ls -d bin`) to tell the plugin "I know no
  entry allows this" and let it fall through to claude-codes own command approval system. Claude runs this itself
  instead of asking you to run `!command`. Usually triggering an ask user prompt
- run
  `add-allow-policy --scope {user,project} --intent "why we should allow this" --example "<a real command>" '<entry>'`
  to propose adding an entry (a program name or a JSON entry object - never a whole command line) to your allow list.
  Every `--example` must be allowed by your current config plus the entry, otherwise the proposal is refused before you
  are asked. Claude proposes this up front when a task will need many bypasses, or at the end of a session that needed
  many workarounds (handing the command to you instead when its work is part of a wider process)

Bascially - claude gets the chance to correct itself without ever accidentally triggering a user interaction. Only when
it gives up on its current tool set and adds `bypass-policy` will a user interaction become necessary, and a durable
`add-allow-policy` rule is how repeated interactions get collapsed into one.
