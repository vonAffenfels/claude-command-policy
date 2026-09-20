#!/usr/bin/env python3
"""
awk command parser for shfmt-permissions.

Parses awk commands to extract program, variables, and detect dangerous patterns.

Input (JSON on stdin):
    {"arguments": ["-v", "x=1", "{ print $1 }", "file.txt"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-v", "arguments": ["x=1"]}],
        "positionals": [{"index": 0, "value": "{ print $1 }"}, {"index": 1, "value": "file.txt"}],
        "subcommand": null,
        "named": {
            "program": "{ print $1 }",
            "programFile": null,
            "variables": {"x": "1"},
            "containsProgramCalls": false
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


def strip_awk_strings_and_comments(program: str) -> str:
    """Remove string literals and comments from awk program for pattern detection.

    This prevents false positives where 'system' appears inside a string literal
    or comment rather than as an actual function call.

    Args:
        program: The awk program text.

    Returns:
        Program text with strings replaced by placeholders and comments removed.
    """
    result = []
    i = 0
    in_regex = False

    while i < len(program):
        char = program[i]

        # Handle comments (# to end of line)
        if char == "#":
            # Skip to end of line
            while i < len(program) and program[i] != "\n":
                i += 1
            continue

        # Handle string literals (double quotes)
        if char == '"':
            # Skip the entire string
            i += 1
            while i < len(program):
                if program[i] == "\\":
                    i += 2  # Skip escape sequence
                elif program[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            result.append('""')  # Placeholder
            continue

        # Handle regex literals (between slashes, but not division)
        # This is tricky because / can be division or regex delimiter
        # Heuristic: if / follows certain tokens, it's regex
        if char == "/" and not in_regex:
            # Check if this looks like start of regex (simplified heuristic)
            # After: ~ !~ { ; ( , = || && | or at start
            prev_chars = "".join(result[-10:]).strip() if result else ""
            if (not prev_chars or
                prev_chars.endswith(("~", "!~", "{", ";", "(", ",", "=", "||", "&&", "|", "!"))):
                # This is a regex
                i += 1
                while i < len(program):
                    if program[i] == "\\":
                        i += 2  # Skip escape sequence
                    elif program[i] == "/":
                        i += 1
                        break
                    else:
                        i += 1
                result.append("//")  # Placeholder
                continue

        result.append(char)
        i += 1

    return "".join(result)


def detect_program_calls(program: str) -> bool:
    """Detect if an awk program contains external command execution patterns.

    Detects:
    - system(...) function calls
    - getline with pipe: "cmd" | getline or cmd | getline
    - Output pipes: print ... | "cmd"
    - Input redirection with command: getline < "cmd"
    - Coprocess: |& operator

    Args:
        program: The awk program text.

    Returns:
        True if dangerous patterns are detected.
    """
    if not program:
        return False

    # Strip strings and comments for accurate detection
    stripped = strip_awk_strings_and_comments(program)

    # Pattern 1: system() function call
    # Matches: system("cmd"), system(var), system("cmd" var)
    if re.search(r"\bsystem\s*\(", stripped):
        return True

    # Pattern 2: Coprocess operator |&
    if "|&" in stripped:
        return True

    # Pattern 3: Pipe to getline (input from command)
    # Matches: "cmd" | getline, cmd | getline, ("cmd") | getline
    if re.search(r"\|\s*getline", stripped):
        return True

    # Pattern 4: Print/printf piped to command
    # Matches: print ... | "cmd", printf ... | cmd
    if re.search(r"\b(print|printf)\b[^|;]*\|", stripped):
        return True

    # Pattern 5: getline from command via input redirection
    # In awk, getline < "file" reads file, but getline < ("cmd") executes cmd
    # We'll flag any getline < pattern as potentially dangerous
    if re.search(r"\bgetline\s*<", stripped):
        return True

    # Pattern 6: close() on a pipe (indicates pipe was used somewhere)
    if re.search(r"\bclose\s*\(", stripped):
        # This alone isn't dangerous, but combined with other patterns might be
        # For now, don't flag this alone
        pass

    return False


def parse_awk_args(arguments: list[str]) -> dict[str, Any]:
    """Parse awk command arguments."""
    options = []
    positionals = []
    named = {
        "program": None,
        "programFile": None,
        "variables": {},
        "containsProgramCalls": False,
    }
    paths = []
    positional_index = 0
    options_stopped = False
    program_found = False

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
            if not program_found:
                # First positional is the program
                named["program"] = arg
                program_found = True
                named["containsProgramCalls"] = detect_program_calls(arg)
            else:
                # Subsequent positionals are input files
                paths.append(resolve_path(arg))
            i += 1
            continue

        # Handle options
        if arg.startswith("-"):
            if arg in ("-f", "--file"):
                # Program from file
                if i + 1 < len(arguments):
                    i += 1
                    named["programFile"] = arguments[i]
                    program_found = True  # Program is in file, not positional
                    paths.append(resolve_path(arguments[i]))
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
            elif arg.startswith("-f"):
                # -ffile (combined form)
                file_path = arg[2:]
                named["programFile"] = file_path
                program_found = True
                paths.append(resolve_path(file_path))
                options.append({"name": "-f", "arguments": [file_path]})
            elif arg in ("-v", "--assign"):
                # Variable assignment
                if i + 1 < len(arguments):
                    i += 1
                    var_assign = arguments[i]
                    options.append({"name": arg, "arguments": [var_assign]})
                    # Parse var=value
                    if "=" in var_assign:
                        var_name, var_value = var_assign.split("=", 1)
                        named["variables"][var_name] = var_value
                else:
                    options.append({"name": arg, "arguments": []})
            elif arg.startswith("-v"):
                # -vvar=value (combined form)
                var_assign = arg[2:]
                options.append({"name": "-v", "arguments": [var_assign]})
                if "=" in var_assign:
                    var_name, var_value = var_assign.split("=", 1)
                    named["variables"][var_name] = var_value
            elif arg in ("-e", "--source"):
                # Program text (gawk extension)
                if i + 1 < len(arguments):
                    i += 1
                    if named["program"] is None:
                        named["program"] = arguments[i]
                    else:
                        named["program"] += "\n" + arguments[i]
                    program_found = True
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
            elif arg in ("-F", "--field-separator"):
                # Field separator
                if i + 1 < len(arguments):
                    i += 1
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
            elif arg.startswith("-F"):
                # -F: or -F',' (combined form)
                sep = arg[2:]
                options.append({"name": "-F", "arguments": [sep]})
            elif arg in ("-W", "--compat", "--traditional", "--posix", "--re-interval",
                         "--gen-pot", "--non-decimal-data", "--sandbox", "-b", "--characters-as-bytes",
                         "-c", "-C", "-d", "-D", "-E", "-g", "-h", "--help", "-L", "-l",
                         "-M", "-n", "-N", "-o", "-O", "-p", "-P", "-r", "-S", "-s", "-t",
                         "-V", "--version"):
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

        if not program_found:
            # First positional is the awk program
            named["program"] = arg
            program_found = True
            named["containsProgramCalls"] = detect_program_calls(arg)
        else:
            # Subsequent positionals are input files
            paths.append(resolve_path(arg))

        i += 1

    # If program came from -e options, check for dangerous patterns
    if named["program"] and not named["containsProgramCalls"]:
        named["containsProgramCalls"] = detect_program_calls(named["program"])

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
        result = parse_awk_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
