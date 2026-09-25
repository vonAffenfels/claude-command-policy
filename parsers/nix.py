#!/usr/bin/env python3
"""
nix command parser for shfmt-permissions.

Parses flake-era `nix` commands — primarily `nix develop` and `nix shell`, which have
replaced `nix-shell` for reproducible development environments. Extracts the subcommand,
the flake installable, and the nested command run via `-c`/`--command` (the key for
propagation).

Input (JSON on stdin):
    {"arguments": ["develop", ".#backend", "-c", "npm", "install"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-c", "arguments": ["npm", "install"]}],
        "positionals": [{"index": 0, "value": ".#backend"}],
        "subcommand": null,
        "named": {"subcommand": "develop", "installable": ".#backend", "command": "npm install"},
        "paths": [],
        "nestedCommands": [{"text": "npm install", "shape": "argv"}]
    }

The `-c`/`--command` option consumes the rest of the argument vector as a command and its
arguments (unlike `nix-shell --run`, which takes a single shell string). Those already-split
arguments are re-quoted with shlex so that propagation re-parses them with their original
word boundaries intact, and published on TWO channels: `named.command` (unchanged, for a
config-authored `namedValue` filter) and `nestedCommands` (the channel
`lib/nested_command_filter.py` actually reads, with `shape: "argv"`). Every other
invocation — `nix run`, `nix build`, and any `-c`-less subcommand — publishes neither: the
program that would run is named by a flake installable this parser cannot resolve to a
command word, so publishing nothing is honest rather than a guess. Inner-command paths are
therefore validated by the propagated evaluation, not by this parser — so the installable
(a flake reference such as `.#foo`, not a filesystem path) is never reported as a path.
"""

import json
import os
import shlex
import sys
from typing import Any


# nix subcommands (first bare token). Not exhaustive; the security-relevant ones are the
# environment-entering commands (develop, shell, run) whose --command is propagated.
SUBCOMMANDS = {
    "develop", "shell", "run", "build", "flake", "profile", "registry", "repl",
    "eval", "fmt", "store", "search", "path-info", "why-depends", "log", "edit",
    "copy", "bundle", "hash", "key", "nar", "print-dev-env", "upgrade-nix",
    "daemon", "doctor", "help",
}

# Option that runs a command instead of an interactive shell. Consumes the entire remainder
# of the argument vector as the command plus its arguments (nix develop/shell semantics).
COMMAND_OPTIONS = {"-c", "--command"}

# Options that consume one argument
OPTIONS_WITH_ONE_ARGUMENT = {
    "--phase", "--profile", "-k", "--keep", "--unset",
    "-j", "--max-jobs", "--cores", "-I", "--include", "-f", "--file",
}

# Options that consume two arguments (name value)
OPTIONS_WITH_TWO_ARGUMENTS = {
    "--arg", "--argstr", "--override-input", "--option",
}

# Options whose (single) argument is a file/directory path
PATH_OPTIONS = {
    "--profile", "-I", "--include", "-f", "--file",
}


def resolve_path(value: str) -> str:
    """Resolve a path value to absolute form."""
    if value.startswith("~"):
        return os.path.normpath(os.path.expanduser(value))
    elif value.startswith("/"):
        return os.path.normpath(value)
    else:
        return os.path.abspath(value)


def parse_nix_args(arguments: list[str]) -> dict[str, Any]:
    """Parse nix command arguments."""
    options: list[dict[str, Any]] = []
    positionals: list[dict[str, Any]] = []
    named: dict[str, Any] = {}
    paths: list[str] = []
    nested_commands: list[dict[str, Any]] = []
    positional_index = 0
    subcommand = None

    i = 0
    while i < len(arguments):
        arg = arguments[i]

        # -c/--command swallows the rest of the argv as the nested command + its arguments.
        if arg in COMMAND_OPTIONS:
            command_parts = arguments[i + 1:]
            options.append({"name": arg, "arguments": command_parts})
            if command_parts:
                quoted_command = " ".join(shlex.quote(part) for part in command_parts)
                named["command"] = quoted_command
                nested_commands.append({"text": quoted_command, "shape": "argv"})
            break

        if arg.startswith("-"):
            # --option=value style
            if "=" in arg and arg.startswith("--"):
                eq_pos = arg.index("=")
                opt_name = arg[:eq_pos]
                opt_value = arg[eq_pos + 1:]
                options.append({"name": opt_name, "arguments": [opt_value]})
                if opt_name in PATH_OPTIONS:
                    paths.append(resolve_path(opt_value))
                i += 1
                continue

            if arg in OPTIONS_WITH_TWO_ARGUMENTS:
                opt_args = arguments[i + 1:i + 3]
                options.append({"name": arg, "arguments": opt_args})
                i += 1 + len(opt_args)
                continue

            if arg in OPTIONS_WITH_ONE_ARGUMENT:
                if i + 1 < len(arguments):
                    opt_value = arguments[i + 1]
                    options.append({"name": arg, "arguments": [opt_value]})
                    if arg in PATH_OPTIONS:
                        paths.append(resolve_path(opt_value))
                    i += 2
                else:
                    options.append({"name": arg, "arguments": []})
                    i += 1
                continue

            # Unknown option - treat as a flag
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Positional: first bare token is the subcommand, second is the installable.
        if subcommand is None and arg in SUBCOMMANDS:
            subcommand = arg
            named["subcommand"] = arg
        elif "installable" not in named:
            named["installable"] = arg
            positionals.append({"index": positional_index, "value": arg})
            positional_index += 1
        else:
            positionals.append({"index": positional_index, "value": arg})
            positional_index += 1
        i += 1

    result = {
        "options": options,
        "positionals": positionals,
        "subcommand": None,
        "named": named,
        "paths": paths,
    }
    if nested_commands:
        result["nestedCommands"] = nested_commands
    return result


def describe() -> dict[str, Any]:
    """Static capabilities this parser answers via stdin {"describe": true}
    (improvement 20260925-120037). nix CAN publish a nested command
    (`-c`/`--command`), even though a given invocation may not - see this
    module's docstring on the honest-absence rule for `nix run`/`-c`-less
    invocations."""
    return {
        "publishesNestedCommands": True,
        "namedValues": ["subcommand", "installable", "command"],
        "optionsWithValues": sorted(
            OPTIONS_WITH_ONE_ARGUMENT | OPTIONS_WITH_TWO_ARGUMENTS | COMMAND_OPTIONS
        ),
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        if input_data.get("describe"):
            print(json.dumps(describe()))
            return
        arguments = input_data.get("arguments", [])
        result = parse_nix_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
