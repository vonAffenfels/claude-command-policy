#!/usr/bin/env python3
"""
Cat command parser for shfmt-permissions.

Parses cat commands where all positional arguments are file paths.

Input (JSON on stdin):
    {"arguments": ["-n", "file1.txt", "file2.txt"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-n", "arguments": []}],
        "positionals": [
            {"index": 0, "value": "file1.txt"},
            {"index": 1, "value": "file2.txt"}
        ],
        "subcommand": null,
        "named": {},
        "paths": ["/absolute/path/to/file1.txt", "/absolute/path/to/file2.txt"]
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


def parse_cat_args(arguments: list[str]) -> dict[str, Any]:
    """Parse cat command arguments.

    All non-option arguments are treated as file paths.
    """
    options = []
    positionals = []
    paths = []
    positional_index = 0
    options_stopped = False

    i = 0
    while i < len(arguments):
        arg = arguments[i]

        # Handle -- (stop option parsing)
        if arg == "--" and not options_stopped:
            options_stopped = True
            i += 1
            continue

        # After --, everything is positional (file path)
        if options_stopped:
            positionals.append({"index": positional_index, "value": arg})
            positional_index += 1
            # All positionals in cat are file paths
            if arg != "-":  # Skip stdin marker
                paths.append(resolve_path(arg))
            i += 1
            continue

        # Handle options (cat options don't take arguments)
        if arg.startswith("-") and arg != "-":
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Handle positional arguments (file paths)
        positionals.append({"index": positional_index, "value": arg})
        positional_index += 1
        # All positionals in cat are file paths
        if arg != "-":  # Skip stdin marker
            paths.append(resolve_path(arg))
        i += 1

    return {
        "options": options,
        "positionals": positionals,
        "subcommand": None,
        "named": {},
        "paths": paths
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        arguments = input_data.get("arguments", [])
        result = parse_cat_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
