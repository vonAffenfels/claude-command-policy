#!/usr/bin/env python3
"""
Find command parser for shfmt-permissions.

Parses find commands to extract exec/delete actions, search paths, and other options.

Input (JSON on stdin):
    {"arguments": [".", "-name", "*.txt", "-exec", "rm", "{}", ";"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-name", "arguments": ["*.txt"]}, {"name": "-exec", "arguments": ["rm", "{}", ";"]}],
        "positionals": [{"index": 0, "value": "."}],
        "subcommand": null,
        "named": {
            "execPresent": true,
            "deletePresent": false,
            "exec_command": "rm",
            "type": null
        },
        "paths": ["/absolute/path/to/."]
    }
"""

import json
import os
import sys
from typing import Any


def resolve_path(value: str) -> str:
    """Resolve a path value to absolute form.

    Args:
        value: Path value to resolve.

    Returns:
        Absolute path.
    """
    if value.startswith("~"):
        expanded = os.path.expanduser(value)
        return os.path.normpath(expanded)
    elif value.startswith("/"):
        return os.path.normpath(value)
    else:
        return os.path.abspath(value)


# Find primaries/tests that take one argument
PRIMARIES_WITH_ONE_ARG = {
    "-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename",
    "-lname", "-ilname", "-regex", "-iregex",
    "-type", "-xtype", "-fstype",
    "-user", "-group", "-uid", "-gid",
    "-perm", "-mode",
    "-size", "-links", "-inum",
    "-mtime", "-atime", "-ctime", "-mmin", "-amin", "-cmin",
    "-newer", "-anewer", "-cnewer", "-newerXY",
    "-samefile", "-level", "-maxdepth", "-mindepth",
    "-printf", "-fprintf",
}

# Primaries with two arguments
PRIMARIES_WITH_TWO_ARGS = {
    "-newerXY",  # -newerXY reference (X and Y are single chars)
}

# Actions that start exec-style blocks (terminated by ; or +)
EXEC_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir"}

# Primaries that are flags (no arguments)
FLAG_PRIMARIES = {
    "-empty", "-executable", "-readable", "-writable",
    "-nouser", "-nogroup", "-xdev", "-noleaf", "-mount",
    "-daystart", "-depth", "-follow", "-ignore_readdir_race",
    "-noignore_readdir_race", "-warn", "-nowarn",
    "-print", "-print0", "-ls", "-fls", "-quit",
}

# Dangerous/noteworthy actions
DANGEROUS_ACTIONS = {"-delete", "-prune"}


def parse_find_args(arguments: list[str]) -> dict[str, Any]:
    """Parse find command arguments.

    Find syntax: find [paths...] [expression]
    Paths come first (before any primary starting with -).
    """
    options = []
    positionals = []
    named = {
        "execPresent": False,
        "deletePresent": False,
        "exec_command": None,
        "type": None,
    }
    paths = []
    positional_index = 0

    i = 0
    # First, collect path arguments (everything before first primary/operator)
    while i < len(arguments):
        arg = arguments[i]
        # Stop when we hit a primary, operator, or special token
        if arg.startswith("-") or arg.startswith("(") or arg.startswith("!") or arg == ",":
            break
        # This is a search path
        positionals.append({"index": positional_index, "value": arg})
        positional_index += 1
        paths.append(resolve_path(arg))
        i += 1

    # Now parse the expression
    while i < len(arguments):
        arg = arguments[i]

        # Handle exec-style actions (-exec, -execdir, -ok, -okdir)
        if arg in EXEC_ACTIONS:
            named["execPresent"] = True
            exec_args = [arg]
            exec_command_parts = []
            i += 1

            # Collect everything until ; or +
            while i < len(arguments):
                exec_arg = arguments[i]
                exec_args.append(exec_arg)

                # Check for terminator
                if exec_arg in (";", "+", "\\;"):
                    i += 1
                    break

                # Collect command parts (excluding {} placeholder and terminator)
                if exec_arg != "{}":
                    exec_command_parts.append(exec_arg)
                i += 1

            # The first part after -exec is the command
            if exec_command_parts and named["exec_command"] is None:
                named["exec_command"] = exec_command_parts[0]

            options.append({"name": arg, "arguments": exec_args[1:]})
            continue

        # Handle -delete action
        if arg == "-delete":
            named["deletePresent"] = True
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Handle -type primary (extract value to named)
        if arg == "-type" and i + 1 < len(arguments):
            type_value = arguments[i + 1]
            named["type"] = type_value
            options.append({"name": arg, "arguments": [type_value]})
            i += 2
            continue

        # Handle primaries with one argument
        if arg in PRIMARIES_WITH_ONE_ARG and i + 1 < len(arguments):
            opt_value = arguments[i + 1]
            options.append({"name": arg, "arguments": [opt_value]})
            i += 2
            continue

        # Handle flag primaries (no arguments)
        if arg in FLAG_PRIMARIES or arg in DANGEROUS_ACTIONS:
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Handle operators and grouping
        if arg in ("(", ")", "-a", "-and", "-o", "-or", "!", "-not", ","):
            # These are structural, not really "options" but we track them
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Handle options starting with - that we don't recognize
        if arg.startswith("-"):
            # Check if next arg might be a value (doesn't start with -)
            if i + 1 < len(arguments) and not arguments[i + 1].startswith("-"):
                options.append({"name": arg, "arguments": [arguments[i + 1]]})
                i += 2
            else:
                options.append({"name": arg, "arguments": []})
                i += 1
            continue

        # Anything else is an unexpected positional (shouldn't happen in valid find syntax)
        positionals.append({"index": positional_index, "value": arg})
        positional_index += 1
        i += 1

    return {
        "options": options,
        "positionals": positionals,
        "subcommand": None,
        "named": named,
        "paths": paths
    }


def describe() -> dict[str, Any]:
    """Static capabilities this parser answers via stdin {"describe": true}
    (improvement 20260925-120037). find never publishes on the
    nestedCommands channel - `-exec`'s command is reported only as the
    `exec_command` named value, not propagated through the wrapper-command
    machinery."""
    return {
        "publishesNestedCommands": False,
        "namedValues": ["execPresent", "deletePresent", "exec_command", "type"],
        "optionsWithValues": sorted(PRIMARIES_WITH_ONE_ARG | EXEC_ACTIONS),
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        if input_data.get("describe"):
            print(json.dumps(describe()))
            return
        arguments = input_data.get("arguments", [])
        result = parse_find_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
