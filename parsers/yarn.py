#!/usr/bin/env python3
"""
yarn command parser for shfmt-permissions.

Parses yarn commands to extract subcommand, packages, and relevant options.
The subcommand table is the union of yarn v1 (classic) and berry (v2+) vocabulary,
so the parser never needs to know which era it is looking at. An implicit script
run (`yarn build`) is canonicalized to `run` plus a script name, and v1's `global`
prefix (`yarn global add pkg`) sets the global flag without consuming the subcommand.

Input (JSON on stdin):
    {"arguments": ["global", "add", "typescript"]}

Output (JSON on stdout):
    {
        "options": [],
        "positionals": [{"index": 0, "value": "typescript"}],
        "subcommand": null,
        "named": {
            "subcommand": "add",
            "packages": ["typescript"],
            "script": null,
            "global": true
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


# yarn subcommands: union of v1 (classic) and berry (v2+) vocabulary
SUBCOMMANDS = {
    # Shared by both eras
    "add", "audit", "bin", "cache", "config", "dedupe", "exec", "explain",
    "import", "info", "init", "install", "link", "list", "login", "logout",
    "node", "outdated", "own", "owner", "pack", "publish", "rebuild", "remove",
    "run", "set", "tag", "team", "test", "unlink", "unplug", "up", "upgrade",
    "upgrade-interactive", "version", "versions", "why", "workspace",
    "workspaces", "whoami", "help",
    # v1 (classic) only
    "autoclean", "check", "create", "generate-lock-entry", "licenses",
    "policies", "global",
    # berry (v2+) only
    "constraints", "dlx", "npm", "patch", "patch-commit", "plugin", "stage",
}

# yarn subcommand aliases mapping to canonical form
SUBCOMMAND_ALIASES = {
    "up": "upgrade",
    "ls": "list",
}

# Subcommands that accept package names
PACKAGE_SUBCOMMANDS = {
    "add", "remove", "upgrade", "why", "link", "unlink", "unplug", "info",
    "outdated", "patch", "owner", "tag", "publish", "list",
}

# Subcommands that take script or binary names
SCRIPT_SUBCOMMANDS = {"run", "exec", "dlx", "create", "node"}

# Options that take one argument
OPTIONS_WITH_ARGUMENTS = {
    "--cwd", "--modules-folder", "--cache-folder", "--global-folder",
    "--link-folder", "--preferred-cache-folder", "--registry", "--proxy",
    "--https-proxy", "--network-concurrency", "--network-timeout",
    "--mutex", "--scope", "--tag", "--access", "--otp", "--otp-code",
    "--package", "--use-yarnrc", "--pattern", "--filename",
}

# Options whose arguments are paths
PATH_OPTIONS = {
    "--cwd", "--modules-folder", "--cache-folder", "--global-folder",
    "--link-folder", "--preferred-cache-folder", "--use-yarnrc", "--filename",
}


def parse_yarn_args(arguments: list[str]) -> dict[str, Any]:
    """Parse yarn command arguments."""
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

    i = 0
    while i < len(arguments):
        arg = arguments[i]

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
            elif arg in ("-g", "--global"):
                # Global flag
                named["global"] = True
                options.append({"name": arg, "arguments": []})
            elif arg in OPTIONS_WITH_ARGUMENTS:
                # Option consumes next argument
                if i + 1 < len(arguments):
                    i += 1
                    opt_value = arguments[i]
                    options.append({"name": arg, "arguments": [opt_value]})
                    if arg in PATH_OPTIONS:
                        paths.append(resolve_path(opt_value))
                else:
                    options.append({"name": arg, "arguments": []})
            else:
                # Flag option or unknown option
                options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # v1's `global` prefixes the real subcommand rather than being one
        if subcommand is None and arg == "global":
            named["global"] = True
            i += 1
            continue

        # First non-option is the subcommand, or an implicit script run
        if subcommand is None:
            if arg in SUBCOMMANDS or arg in SUBCOMMAND_ALIASES:
                subcommand = SUBCOMMAND_ALIASES.get(arg, arg)
                named["subcommand"] = subcommand
                i += 1
                continue
            # `yarn build` means `yarn run build`
            subcommand = "run"
            named["subcommand"] = subcommand
            named["script"] = arg
            i += 1
            continue

        # After subcommand, collect positional arguments
        positionals.append({"index": positional_index, "value": arg})
        positional_index += 1

        # For package subcommands, collect package names
        if subcommand in PACKAGE_SUBCOMMANDS:
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


def describe() -> dict[str, Any]:
    """Static capabilities this parser answers via stdin {"describe": true}
    (improvement 20260925-120037). yarn never wraps another command."""
    return {
        "publishesNestedCommands": False,
        "namedValues": ["subcommand", "packages", "script", "global"],
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
        result = parse_yarn_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
