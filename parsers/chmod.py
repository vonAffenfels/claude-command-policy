#!/usr/bin/env python3
"""
chmod command parser for shfmt-permissions.

Parses chmod commands to extract mode information (both octal and symbolic)
and detect specific permission changes.

Input (JSON on stdin):
    {"arguments": ["-R", "755", "/var/www"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-R", "arguments": []}],
        "positionals": [{"index": 0, "value": "755"}, {"index": 1, "value": "/var/www"}],
        "subcommand": null,
        "named": {
            "mode": "755",
            "recursive": true,
            "setsUserExecutable": true,
            "setsGroupExecutable": true,
            "setsOthersExecutable": true,
            "setsUserWritable": true,
            "setsGroupWritable": false,
            "setsOthersWritable": false,
            "setsSetuid": false,
            "setsSetgid": false,
            "setsSticky": false
        },
        "paths": ["/var/www"]
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


def parse_octal_mode(mode_str: str) -> dict[str, bool]:
    """Parse an octal mode string and extract permission flags.

    Args:
        mode_str: Octal mode string like "755" or "4755".

    Returns:
        Dictionary with permission flags.
    """
    flags = {
        "setsUserExecutable": False,
        "setsGroupExecutable": False,
        "setsOthersExecutable": False,
        "setsUserWritable": False,
        "setsGroupWritable": False,
        "setsOthersWritable": False,
        "setsSetuid": False,
        "setsSetgid": False,
        "setsSticky": False,
    }

    try:
        mode = int(mode_str, 8)
    except ValueError:
        return flags

    # Extract permission bits
    # User (owner) permissions (bits 6-8)
    if mode & 0o100:  # User execute
        flags["setsUserExecutable"] = True
    if mode & 0o200:  # User write
        flags["setsUserWritable"] = True

    # Group permissions (bits 3-5)
    if mode & 0o010:  # Group execute
        flags["setsGroupExecutable"] = True
    if mode & 0o020:  # Group write
        flags["setsGroupWritable"] = True

    # Others permissions (bits 0-2)
    if mode & 0o001:  # Others execute
        flags["setsOthersExecutable"] = True
    if mode & 0o002:  # Others write
        flags["setsOthersWritable"] = True

    # Special bits (bits 9-11)
    if mode & 0o4000:  # Setuid
        flags["setsSetuid"] = True
    if mode & 0o2000:  # Setgid
        flags["setsSetgid"] = True
    if mode & 0o1000:  # Sticky
        flags["setsSticky"] = True

    return flags


def parse_symbolic_mode(mode_str: str) -> dict[str, bool]:
    """Parse a symbolic mode string and extract permission flags.

    Args:
        mode_str: Symbolic mode string like "u+x", "go-w", "a=rwx".

    Returns:
        Dictionary with permission flags.
    """
    flags = {
        "setsUserExecutable": False,
        "setsGroupExecutable": False,
        "setsOthersExecutable": False,
        "setsUserWritable": False,
        "setsGroupWritable": False,
        "setsOthersWritable": False,
        "setsSetuid": False,
        "setsSetgid": False,
        "setsSticky": False,
    }

    # Symbolic mode format: [ugoa...][+-=][rwxXst...]
    # Can have multiple clauses separated by comma
    clauses = mode_str.split(",")

    for clause in clauses:
        # Parse clause: who[+-=]permissions
        match = re.match(r"([ugoa]*)([+\-=])([rwxXstugo]*)", clause)
        if not match:
            continue

        who = match.group(1) or "a"  # Default to 'a' (all) if not specified
        operator = match.group(2)
        permissions = match.group(3)

        # Only track permissions being added (+) or set (=)
        # Removing (-) doesn't "set" the permission
        if operator == "-":
            continue

        # Map who to user classes
        affects_user = "u" in who or "a" in who
        affects_group = "g" in who or "a" in who
        affects_others = "o" in who or "a" in who

        # Map permissions to flags
        for perm in permissions:
            if perm == "x" or perm == "X":
                if affects_user:
                    flags["setsUserExecutable"] = True
                if affects_group:
                    flags["setsGroupExecutable"] = True
                if affects_others:
                    flags["setsOthersExecutable"] = True
            elif perm == "w":
                if affects_user:
                    flags["setsUserWritable"] = True
                if affects_group:
                    flags["setsGroupWritable"] = True
                if affects_others:
                    flags["setsOthersWritable"] = True
            elif perm == "s":
                # s sets setuid when in user position, setgid when in group position
                if affects_user:
                    flags["setsSetuid"] = True
                if affects_group:
                    flags["setsSetgid"] = True
            elif perm == "t":
                flags["setsSticky"] = True

    return flags


def is_octal_mode(mode_str: str) -> bool:
    """Check if a string is an octal mode.

    Args:
        mode_str: String to check.

    Returns:
        True if it looks like an octal mode.
    """
    return bool(re.match(r"^[0-7]{3,4}$", mode_str))


def is_symbolic_mode(mode_str: str) -> bool:
    """Check if a string is a symbolic mode.

    Args:
        mode_str: String to check.

    Returns:
        True if it looks like a symbolic mode.
    """
    # Symbolic mode contains [ugoa], [+-=], and [rwxXst]
    return bool(re.match(r"^[ugoa]*[+\-=][rwxXstugo,]+$", mode_str))


def parse_chmod_args(arguments: list[str]) -> dict[str, Any]:
    """Parse chmod command arguments."""
    options = []
    positionals = []
    named = {
        "mode": None,
        "recursive": False,
        "setsUserExecutable": False,
        "setsGroupExecutable": False,
        "setsOthersExecutable": False,
        "setsUserWritable": False,
        "setsGroupWritable": False,
        "setsOthersWritable": False,
        "setsSetuid": False,
        "setsSetgid": False,
        "setsSticky": False,
    }
    paths = []
    positional_index = 0
    options_stopped = False
    mode_found = False

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
            if not mode_found:
                # First positional after -- is mode
                named["mode"] = arg
                mode_found = True
                if is_octal_mode(arg):
                    flags = parse_octal_mode(arg)
                    named.update(flags)
                elif is_symbolic_mode(arg):
                    flags = parse_symbolic_mode(arg)
                    named.update(flags)
            else:
                # Subsequent positionals are paths
                paths.append(resolve_path(arg))
            i += 1
            continue

        # Handle options
        if arg.startswith("-") and not mode_found:
            if arg in ("-R", "--recursive"):
                named["recursive"] = True
                options.append({"name": arg, "arguments": []})
            elif arg in ("-c", "--changes", "-f", "--silent", "--quiet",
                         "-v", "--verbose", "--preserve-root", "--no-preserve-root",
                         "-h", "--no-dereference", "--dereference", "--reference"):
                options.append({"name": arg, "arguments": []})
            elif arg == "--reference":
                # --reference takes a file argument
                if i + 1 < len(arguments):
                    i += 1
                    options.append({"name": arg, "arguments": [arguments[i]]})
                else:
                    options.append({"name": arg, "arguments": []})
            else:
                # Could be a symbolic mode starting with - (like -x to remove execute)
                # But this is rare and we'll treat unknown -options as flags
                options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Positional arguments
        positionals.append({"index": positional_index, "value": arg})
        positional_index += 1

        if not mode_found:
            # First positional is the mode
            named["mode"] = arg
            mode_found = True
            if is_octal_mode(arg):
                flags = parse_octal_mode(arg)
                named.update(flags)
            elif is_symbolic_mode(arg):
                flags = parse_symbolic_mode(arg)
                named.update(flags)
        else:
            # Subsequent positionals are file paths
            paths.append(resolve_path(arg))

        i += 1

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
        result = parse_chmod_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
