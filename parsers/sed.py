#!/usr/bin/env python3
"""
sed command parser for shfmt-permissions.

Parses sed commands to extract expression, options, and detect dangerous patterns.

Input (JSON on stdin):
    {"arguments": ["-i.bak", "s/foo/bar/g", "file.txt"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-i", "arguments": [".bak"]}],
        "positionals": [{"index": 0, "value": "s/foo/bar/g"}, {"index": 1, "value": "file.txt"}],
        "subcommand": null,
        "named": {
            "inPlace": true,
            "inPlaceBackup": ".bak",
            "expression": "s/foo/bar/g",
            "scriptFile": null,
            "containsDangerousCommands": false
        },
        "paths": ["/absolute/path/to/file.txt"]
    }
"""

import json
import os
import re
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


def detect_dangerous_commands(expression: str) -> bool:
    """Detect if a sed expression contains dangerous commands.

    Detects:
    - 'e' command (GNU sed: execute pattern space as shell command)
    - 'w' command (write to file - could write anywhere)
    - 'r' command (read from file - less dangerous but worth flagging)

    Args:
        expression: The sed expression/script.

    Returns:
        True if dangerous patterns are detected.
    """
    if not expression:
        return False

    # The 'e' command in GNU sed executes the pattern space as a shell command
    # It can appear as:
    # - standalone 'e' command (executes pattern space)
    # - 's/.../.../e' flag (executes replacement as command)

    # Pattern 1: 's' command with 'e' flag
    # Matches: s/pattern/replacement/e, s/pattern/replacement/ge, etc.
    # The 'e' must be in the flags position after the final delimiter
    if re.search(r"s[^a-z]*[/|#@,;:][^/|#@,;:]*[/|#@,;:][^/|#@,;:]*[/|#@,;:][a-z]*e", expression):
        return True

    # Pattern 2: standalone 'e' command
    # Matches: e, e command, {e}, etc.
    # The 'e' command executes the contents of pattern space
    if re.search(r"(^|[;{}])\s*e\s*($|[;{}])", expression):
        return True

    # Pattern 3: 'w' command (write to file)
    # Matches: w filename, s/.../replacement/w filename
    # w command writes pattern space to file
    if re.search(r"(^|[;{}])\s*w\s+\S", expression):
        return True
    # s command with w flag
    if re.search(r"s[^a-z]*[/|#@,;:][^/|#@,;:]*[/|#@,;:][^/|#@,;:]*[/|#@,;:][a-z]*w\s*\S", expression):
        return True

    # Pattern 4: 'r' command (read from file)
    # Matches: r filename
    # r command reads file and appends to output
    if re.search(r"(^|[;{}])\s*r\s+\S", expression):
        return True

    return False


def parse_sed_args(arguments: list[str]) -> dict[str, Any]:
    """Parse sed command arguments."""
    options = []
    positionals = []
    named = {
        "inPlace": False,
        "inPlaceBackup": None,
        "expression": None,
        "scriptFile": None,
        "containsDangerousCommands": False,
    }
    paths = []
    positional_index = 0
    options_stopped = False
    expression_found = False
    expressions = []

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
            if not expression_found:
                # First positional is the expression (if no -e was given)
                expressions.append(arg)
                expression_found = True
            else:
                # Subsequent positionals are input files
                paths.append(resolve_path(arg))
            i += 1
            continue

        # Handle options
        if arg.startswith("-"):
            # Handle -i (in-place editing)
            if arg == "-i" or arg == "--in-place":
                named["inPlace"] = True
                # Check if next argument is the backup suffix (not starting with -)
                if i + 1 < len(arguments) and not arguments[i + 1].startswith("-"):
                    # Peek at next arg - could be suffix or could be expression/file
                    # GNU sed: -i[SUFFIX] where SUFFIX is optional and attached
                    # BSD sed: -i extension (separate argument)
                    # We'll treat separate non-option arg as potential suffix only if short
                    next_arg = arguments[i + 1]
                    if len(next_arg) <= 5 and next_arg.startswith("."):
                        # Looks like a backup suffix
                        i += 1
                        named["inPlaceBackup"] = next_arg
                        options.append({"name": "-i", "arguments": [next_arg]})
                    else:
                        # Not a suffix
                        named["inPlaceBackup"] = ""
                        options.append({"name": "-i", "arguments": []})
                else:
                    named["inPlaceBackup"] = ""
                    options.append({"name": "-i", "arguments": []})
            elif arg.startswith("-i"):
                # -i.bak or -ibak (suffix attached)
                named["inPlace"] = True
                suffix = arg[2:]
                named["inPlaceBackup"] = suffix
                options.append({"name": "-i", "arguments": [suffix] if suffix else []})
            elif arg in ("-e", "--expression"):
                # Expression/script
                if i + 1 < len(arguments):
                    i += 1
                    expressions.append(arguments[i])
                    expression_found = True
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
            elif arg.startswith("-e"):
                # -e'expression' (attached)
                expr = arg[2:]
                expressions.append(expr)
                expression_found = True
                options.append({"name": "-e", "arguments": [expr]})
            elif arg in ("-f", "--file"):
                # Script from file
                if i + 1 < len(arguments):
                    i += 1
                    named["scriptFile"] = arguments[i]
                    expression_found = True  # Script is in file
                    paths.append(resolve_path(arguments[i]))
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
            elif arg.startswith("-f"):
                # -fscriptfile (attached)
                script_file = arg[2:]
                named["scriptFile"] = script_file
                expression_found = True
                paths.append(resolve_path(script_file))
                options.append({"name": "-f", "arguments": [script_file]})
            elif arg in ("-n", "--quiet", "--silent", "-r", "-E", "--regexp-extended",
                         "-s", "--separate", "-u", "--unbuffered", "-z", "--null-data",
                         "--follow-symlinks", "--posix", "-l", "--line-length",
                         "--sandbox", "--debug", "-h", "--help", "-V", "--version"):
                # Flag options
                options.append({"name": arg, "arguments": []})
            else:
                # Unknown option - treat as flag
                options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Positional arguments
        positionals.append({"index": positional_index, "value": arg})
        positional_index += 1

        if not expression_found:
            # First positional is the sed expression
            expressions.append(arg)
            expression_found = True
        else:
            # Subsequent positionals are input files
            paths.append(resolve_path(arg))

        i += 1

    # Combine all expressions
    if expressions:
        named["expression"] = "\n".join(expressions) if len(expressions) > 1 else expressions[0]
        named["containsDangerousCommands"] = detect_dangerous_commands(named["expression"])

    return {
        "options": options,
        "positionals": positionals,
        "subcommand": None,
        "named": named,
        "paths": paths
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        arguments = input_data.get("arguments", [])
        result = parse_sed_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
