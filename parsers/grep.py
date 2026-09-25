#!/usr/bin/env python3
"""
grep command parser for shfmt-permissions.

Parses grep commands to extract pattern and distinguish it from file arguments.

Input (JSON on stdin):
    {"arguments": ["-r", "pattern", "dir1", "dir2"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-r", "arguments": []}],
        "positionals": [{"index": 0, "value": "pattern"}, {"index": 1, "value": "dir1"}, {"index": 2, "value": "dir2"}],
        "subcommand": null,
        "named": {
            "pattern": "pattern",
            "patternFile": null,
            "recursive": true,
            "extended": false,
            "fixed": false
        },
        "paths": ["/absolute/path/to/dir1", "/absolute/path/to/dir2"]
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


# Options that take one argument
OPTIONS_WITH_ARGUMENTS = {
    "-e", "--regexp",  # Pattern
    "-f", "--file",  # Pattern file
    "-m", "--max-count",
    "-A", "--after-context",
    "-B", "--before-context",
    "-C", "--context",
    "-D", "--devices",
    "-d", "--directories",
    "--label",
    "--include", "--exclude", "--exclude-dir", "--exclude-from",
    "--color", "--colour",
    "--binary-files",
}

# Options whose arguments are paths
PATH_OPTIONS = {
    "-f", "--file",
    "--exclude-from",
}


def parse_grep_args(arguments: list[str]) -> dict[str, Any]:
    """Parse grep command arguments."""
    options = []
    positionals = []
    named = {
        "pattern": None,
        "patternFile": None,
        "recursive": False,
        "extended": False,
        "fixed": False,
    }
    paths = []
    positional_index = 0
    options_stopped = False
    pattern_found = False
    pattern_from_option = False  # True if pattern came from -e option

    i = 0
    while i < len(arguments):
        arg = arguments[i]

        # Handle -- (stop option parsing)
        if arg == "--" and not options_stopped:
            options_stopped = True
            i += 1
            continue

        # After --, everything is positional
        if options_stopped:
            positionals.append({"index": positional_index, "value": arg})
            positional_index += 1
            if not pattern_found and not pattern_from_option:
                # First positional after -- is pattern (if no -e was given)
                named["pattern"] = arg
                pattern_found = True
            else:
                # Subsequent positionals are files/directories to search
                paths.append(resolve_path(arg))
            i += 1
            continue

        # Handle options
        if arg.startswith("-") and len(arg) > 1:
            # Handle --option=value style
            if "=" in arg and arg.startswith("--"):
                eq_pos = arg.index("=")
                opt_name = arg[:eq_pos]
                opt_value = arg[eq_pos + 1:]
                options.append({"name": opt_name, "arguments": [opt_value]})

                if opt_name in ("--regexp",):
                    named["pattern"] = opt_value
                    pattern_from_option = True
                    pattern_found = True
                elif opt_name == "--file":
                    named["patternFile"] = opt_value
                    pattern_from_option = True
                    pattern_found = True
                    paths.append(resolve_path(opt_value))
                elif opt_name in PATH_OPTIONS:
                    paths.append(resolve_path(opt_value))

                i += 1
                continue

            # Handle -e (explicit pattern)
            if arg in ("-e", "--regexp"):
                if i + 1 < len(arguments):
                    i += 1
                    named["pattern"] = arguments[i]
                    pattern_from_option = True
                    pattern_found = True
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
                i += 1
                continue

            # Handle -f (pattern from file)
            if arg in ("-f", "--file"):
                if i + 1 < len(arguments):
                    i += 1
                    named["patternFile"] = arguments[i]
                    pattern_from_option = True
                    pattern_found = True
                    paths.append(resolve_path(arguments[i]))
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
                i += 1
                continue

            # Handle combined short options like -rn, -Ern
            if not arg.startswith("--") and len(arg) > 2:
                # Could be combined flags like -rn or -rnE
                combined = arg[1:]
                is_combined_flags = True
                for char in combined:
                    if char in "efmABCDd":
                        # These take arguments, so can't be combined
                        is_combined_flags = False
                        break

                if is_combined_flags:
                    # Parse each flag individually
                    for char in combined:
                        if char in ("r", "R"):
                            named["recursive"] = True
                        elif char == "E":
                            named["extended"] = True
                        elif char == "F":
                            named["fixed"] = True
                        options.append({"name": f"-{char}", "arguments": []})
                    i += 1
                    continue

            # Handle recursive flags
            if arg in ("-r", "-R", "--recursive"):
                named["recursive"] = True
                options.append({"name": arg, "arguments": []})
                i += 1
                continue

            # Handle extended regex flag
            if arg in ("-E", "--extended-regexp"):
                named["extended"] = True
                options.append({"name": arg, "arguments": []})
                i += 1
                continue

            # Handle fixed strings flag
            if arg in ("-F", "--fixed-strings"):
                named["fixed"] = True
                options.append({"name": arg, "arguments": []})
                i += 1
                continue

            # Handle other options with arguments
            if arg in OPTIONS_WITH_ARGUMENTS:
                if i + 1 < len(arguments):
                    i += 1
                    opt_value = arguments[i]
                    options.append({"name": arg, "arguments": [opt_value]})
                    if arg in PATH_OPTIONS:
                        paths.append(resolve_path(opt_value))
                else:
                    options.append({"name": arg, "arguments": []})
                i += 1
                continue

            # Handle flag options
            if arg in ("-G", "--basic-regexp", "-P", "--perl-regexp",
                       "-i", "--ignore-case", "-v", "--invert-match",
                       "-w", "--word-regexp", "-x", "--line-regexp",
                       "-c", "--count", "-L", "--files-without-match",
                       "-l", "--files-with-matches", "-o", "--only-matching",
                       "-q", "--quiet", "--silent", "-s", "--no-messages",
                       "-n", "--line-number", "-H", "--with-filename",
                       "-h", "--no-filename", "-T", "--initial-tab",
                       "-Z", "--null", "-b", "--byte-offset",
                       "-u", "--unix-byte-offsets", "-a", "--text",
                       "-I", "--binary", "-z", "--null-data",
                       "-V", "--version", "--help"):
                options.append({"name": arg, "arguments": []})
                i += 1
                continue

            # Unknown option - treat as flag
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Positional arguments
        positionals.append({"index": positional_index, "value": arg})
        positional_index += 1

        if not pattern_found and not pattern_from_option:
            # First positional is the pattern (unless -e was used)
            named["pattern"] = arg
            pattern_found = True
        else:
            # Subsequent positionals are files/directories
            paths.append(resolve_path(arg))

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
    (improvement 20260925-120037). grep never wraps another command."""
    return {
        "publishesNestedCommands": False,
        "namedValues": ["pattern", "patternFile", "recursive", "extended", "fixed"],
        "optionsWithValues": sorted(OPTIONS_WITH_ARGUMENTS),
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        if input_data.get("describe"):
            print(json.dumps(describe()))
            return
        arguments = input_data.get("arguments", [])
        result = parse_grep_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
