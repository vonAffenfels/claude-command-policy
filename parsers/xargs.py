#!/usr/bin/env python3
"""
xargs command parser for command-policy.

Parses GNU coreutils `xargs [OPTIONS] [COMMAND [INITIAL-ARGS...]]`. xargs is a
wrapper: it builds and runs COMMAND with INITIAL-ARGS plus operands read from
stdin. The security-relevant target is COMMAND + INITIAL-ARGS, so the parser
walks xargs' own options first and treats everything after them as the
wrapped command.

Input (JSON on stdin):
    {"arguments": ["-n", "1", "rm", "./build"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-n", "arguments": ["1"]}],
        "positionals": [],
        "subcommand": null,
        "named": {"command": "rm ./build"},
        "paths": [],
        "nestedCommands": [{"text": "rm ./build", "shape": "argv"}]
    }

The wrapped command arrives as already-split argv, so it is re-quoted with shlex
before being published on TWO channels: `named.command` (for a config-authored
`namedValue` filter) and `nestedCommands` (the channel `lib/nested_command_filter.py`
actually reads, with `shape: "argv"`). With NO command argument at all, xargs falls
back to its own documented default of running `echo` - a statically known result,
so that default is published rather than nothing. Inner-command paths are validated
by the propagated evaluation, not by this parser, so `paths` is always empty.
"""

import json
import shlex
import sys
from typing import Any

# xargs' own options that consume one argument. Any other `-`-prefixed token
# is treated as a valueless flag - the same convention every sibling parser
# uses, and what makes a synthetic flag like `--dry-run` register as a flag
# rather than being mistaken for COMMAND.
OPTIONS_WITH_ONE_ARGUMENT = {
    "-a", "--arg-file",
    "-d", "--delimiter",
    "-E",
    "-I", "--replace",
    "-L",
    "-n", "--max-args",
    "-P", "--max-procs",
    "-s", "--max-chars",
}

# xargs' documented default when no COMMAND is given.
DEFAULT_COMMAND = "echo"


def parse_xargs_args(arguments: list[str]) -> dict[str, Any]:
    """Parse xargs command arguments, exposing the wrapped COMMAND + INITIAL-ARGS."""
    options: list[dict[str, Any]] = []

    i = 0
    while i < len(arguments):
        arg = arguments[i]

        # `--` terminates option parsing; everything after it is the command.
        if arg == "--":
            i += 1
            break

        if arg.startswith("-"):
            # --option=value style
            if arg.startswith("--") and "=" in arg:
                eq_pos = arg.index("=")
                opt_name = arg[:eq_pos]
                opt_value = arg[eq_pos + 1:]
                options.append({"name": opt_name, "arguments": [opt_value]})
                i += 1
                continue

            if arg in OPTIONS_WITH_ONE_ARGUMENT:
                if i + 1 < len(arguments):
                    options.append({"name": arg, "arguments": [arguments[i + 1]]})
                    i += 2
                else:
                    options.append({"name": arg, "arguments": []})
                    i += 1
                continue

            # Flag or unknown option - treat as a flag taking no argument.
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # First bare token is COMMAND; everything after it is INITIAL-ARGS.
        break

    command_parts = arguments[i:]
    quoted_command = (
        " ".join(shlex.quote(part) for part in command_parts) if command_parts else DEFAULT_COMMAND
    )

    return {
        "options": options,
        "positionals": [],
        "subcommand": None,
        "named": {"command": quoted_command},
        "paths": [],
        "nestedCommands": [{"text": quoted_command, "shape": "argv"}],
    }


def describe() -> dict[str, Any]:
    """Static capabilities this parser answers via stdin {"describe": true}
    (improvement 20260925-120037). xargs ALWAYS publishes a nested command -
    even a bare invocation falls back to the documented `echo` default (see
    this module's docstring), unlike nix-shell's genuine "nothing is going
    to run"."""
    return {
        "publishesNestedCommands": True,
        "namedValues": ["command"],
        "optionsWithValues": sorted(OPTIONS_WITH_ONE_ARGUMENT),
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        if input_data.get("describe"):
            print(json.dumps(describe()))
            return
        arguments = input_data.get("arguments", [])
        result = parse_xargs_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
