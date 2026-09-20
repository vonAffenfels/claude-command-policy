#!/usr/bin/env python3
"""
Composer command parser for shfmt-permissions.

Parses composer commands to extract subcommand, packages, and relevant options.

Input (JSON on stdin):
    {"arguments": ["require", "--dev", "phpunit/phpunit"]}

Output (JSON on stdout):
    {
        "options": [{"name": "--dev", "arguments": []}],
        "positionals": [{"index": 0, "value": "phpunit/phpunit"}],
        "subcommand": null,
        "named": {
            "subcommand": "require",
            "packages": ["phpunit/phpunit"],
            "script": null,
            "global": false
        },
        "paths": []
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


# Composer options that take one argument
OPTIONS_WITH_ARGUMENTS = {
    "-d", "--working-dir",
    "--ansi", "--no-ansi",
    "-n", "--no-interaction",
    "-v", "-vv", "-vvv", "--verbose",
    "--profile", "--no-plugins", "--no-scripts",
    "--no-cache", "--no-audit",
}

# Options whose arguments are paths
PATH_OPTIONS = {
    "-d", "--working-dir",
}

# Composer subcommands
SUBCOMMANDS = {
    "about", "archive", "audit", "browse", "bump", "cc", "check-platform-reqs",
    "clear-cache", "clearcache", "config", "create-project", "depends", "diagnose",
    "dump-autoload", "dumpautoload", "exec", "fund", "global", "help", "home",
    "i", "info", "init", "install", "licenses", "list", "outdated", "prohibits",
    "reinstall", "remove", "require", "run", "run-script", "search", "self-update",
    "selfupdate", "show", "status", "suggests", "u", "update", "upgrade", "validate",
    "why", "why-not",
}

# Subcommand aliases
SUBCOMMAND_ALIASES = {
    "i": "install",
    "u": "update",
    "upgrade": "update",
    "dumpautoload": "dump-autoload",
    "clearcache": "clear-cache",
    "cc": "clear-cache",
    "selfupdate": "self-update",
    "why": "depends",
    "why-not": "prohibits",
}

# Subcommands that take package names as arguments
PACKAGE_SUBCOMMANDS = {
    "require", "remove", "update", "u", "upgrade", "reinstall",
    "show", "info", "depends", "why", "prohibits", "why-not",
    "outdated", "bump",
}

# Subcommands that take script names
SCRIPT_SUBCOMMANDS = {"run", "run-script", "exec"}


def parse_composer_args(arguments: list[str]) -> dict[str, Any]:
    """Parse composer command arguments."""
    options = []
    positionals = []
    named = {
        "subcommand": None,
        "packages": [],
        "script": None,
        "global": False,
    }
    paths = []
    positional_index = 0
    subcommand = None
    is_global = False

    i = 0
    while i < len(arguments):
        arg = arguments[i]

        # Check for 'global' modifier (must come before subcommand)
        if arg == "global" and subcommand is None:
            is_global = True
            named["global"] = True
            i += 1
            continue

        # Handle options
        if arg.startswith("-"):
            # Handle --option=value style
            if "=" in arg and arg.startswith("--"):
                eq_pos = arg.index("=")
                opt_name = arg[:eq_pos]
                opt_value = arg[eq_pos + 1:]
                options.append({"name": opt_name, "arguments": [opt_value]})
                if opt_name in PATH_OPTIONS:
                    paths.append(resolve_path(opt_value))
            elif arg in ("-d", "--working-dir"):
                # These options take path arguments
                if i + 1 < len(arguments):
                    i += 1
                    opt_value = arguments[i]
                    options.append({"name": arg, "arguments": [opt_value]})
                    paths.append(resolve_path(opt_value))
                else:
                    options.append({"name": arg, "arguments": []})
            elif arg in ("--dev", "--no-dev", "--prefer-source", "--prefer-dist",
                         "--no-progress", "--no-suggest", "--no-plugins", "--no-scripts",
                         "--optimize-autoloader", "-o", "--classmap-authoritative", "-a",
                         "--apcu-autoloader", "--ignore-platform-reqs", "--ignore-platform-req",
                         "--no-install", "--no-autoloader", "--no-update", "--with-dependencies",
                         "--with-all-dependencies", "--dry-run", "-n", "--no-interaction",
                         "-q", "--quiet", "-v", "-vv", "-vvv", "--verbose", "--ansi",
                         "--no-ansi", "--profile", "--no-cache", "--no-audit", "-h", "--help"):
                # Flag options
                options.append({"name": arg, "arguments": []})
            else:
                # Unknown option - treat as flag
                options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # First non-option, non-global is the subcommand
        if subcommand is None and arg in SUBCOMMANDS:
            subcommand = SUBCOMMAND_ALIASES.get(arg, arg)
            named["subcommand"] = subcommand
            i += 1
            continue

        # After subcommand, collect positional arguments
        if subcommand is not None:
            positionals.append({"index": positional_index, "value": arg})
            positional_index += 1

            # For package subcommands, collect package names
            if subcommand in PACKAGE_SUBCOMMANDS:
                # Package names contain / (vendor/package) or are just names
                named["packages"].append(arg)

            # For script subcommands, first positional is the script name
            if subcommand in SCRIPT_SUBCOMMANDS and named["script"] is None:
                named["script"] = arg

        i += 1

    return {
        "options": options,
        "positionals": positionals,
        "subcommand": None,  # Keep consistent with other parsers
        "named": named,
        "paths": paths
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        arguments = input_data.get("arguments", [])
        result = parse_composer_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
