#!/usr/bin/env python3
"""
timeout command parser for shfmt-permissions.

Parses GNU coreutils `timeout [OPTION]... DURATION COMMAND [ARG]...`. timeout is a
wrapper: it runs COMMAND and kills it after DURATION. The security-relevant target is
the inner command, so the parser skips timeout's own options and the DURATION positional
and re-quotes the remainder (COMMAND + its args) as `command` — the key for propagation.

Input (JSON on stdin):
    {"arguments": ["-s", "KILL", "10", "rm", "-rf", "/tmp/x"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-s", "arguments": ["KILL"]}],
        "positionals": [{"index": 0, "value": "10"}],
        "subcommand": null,
        "named": {"signal": "KILL", "duration": "10", "command": "rm -rf /tmp/x"},
        "paths": [],
        "nestedCommands": [{"text": "rm -rf /tmp/x", "shape": "argv"}]
    }

The inner command arrives as already-split argv, so it is re-quoted with shlex before
being published — that way a re-parse preserves the original word boundaries. It is
published on TWO channels: `named.command` (unchanged, for a config-authored `namedValue`
filter) and `nestedCommands` (the channel `lib/nested_command_filter.py` actually reads,
with `shape: "argv"` since the text is re-quoted already-split words). `timeout 10` with
no inner command publishes neither. Inner-command paths are validated by the propagated
evaluation, not by this parser, and timeout's own options only ever take durations/signals
— so `paths` is always empty.
"""

import json
import shlex
import sys
from typing import Any


# Options that consume one argument. -k/--kill-after takes a DURATION; -s/--signal a SIGNAL.
OPTIONS_WITH_ONE_ARGUMENT = {"-k", "--kill-after", "-s", "--signal"}

# Of those, the ones whose value is published under `named.signal`.
SIGNAL_OPTIONS = {"-s", "--signal"}


def parse_timeout_args(arguments: list[str]) -> dict[str, Any]:
    """Parse timeout command arguments, exposing the wrapped inner command."""
    options: list[dict[str, Any]] = []
    positionals: list[dict[str, Any]] = []
    named: dict[str, Any] = {}

    i = 0
    while i < len(arguments):
        arg = arguments[i]

        # `--` terminates option parsing; the next token is DURATION.
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
                if opt_name in SIGNAL_OPTIONS:
                    named["signal"] = opt_value
                i += 1
                continue

            if arg in OPTIONS_WITH_ONE_ARGUMENT:
                if i + 1 < len(arguments):
                    opt_value = arguments[i + 1]
                    options.append({"name": arg, "arguments": [opt_value]})
                    if arg in SIGNAL_OPTIONS:
                        named["signal"] = opt_value
                    i += 2
                else:
                    options.append({"name": arg, "arguments": []})
                    i += 1
                continue

            # Flag or unknown option - treat as a flag taking no argument.
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # First bare token is DURATION; everything after it is the inner command.
        break

    nested_commands = []
    if i < len(arguments):
        duration = arguments[i]
        named["duration"] = duration
        positionals.append({"index": 0, "value": duration})
        command_parts = arguments[i + 1:]
        if command_parts:
            quoted_command = " ".join(shlex.quote(part) for part in command_parts)
            named["command"] = quoted_command
            nested_commands.append({"text": quoted_command, "shape": "argv"})

    result = {
        "options": options,
        "positionals": positionals,
        "subcommand": None,
        "named": named,
        "paths": [],
    }
    if nested_commands:
        result["nestedCommands"] = nested_commands
    return result


def describe() -> dict[str, Any]:
    """Static capabilities this parser answers via stdin {"describe": true}
    (improvement 20260925-120037). timeout CAN publish a nested command,
    even though `timeout 10` with no inner command publishes nothing - see
    this module's docstring."""
    return {
        "publishesNestedCommands": True,
        "namedValues": ["signal", "duration", "command"],
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
        result = parse_timeout_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
