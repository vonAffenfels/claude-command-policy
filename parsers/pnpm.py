#!/usr/bin/env python3
"""
pnpm command parser for shfmt-permissions.

Parses pnpm commands to extract subcommand, packages, and relevant options.
Handles pnpm command aliases (i = install, rm = remove, dx = dlx, etc.) and
canonicalizes an implicit script run (`pnpm build`) to `run` plus a script name.

Input (JSON on stdin):
    {"arguments": ["add", "-g", "typescript"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-g", "arguments": []}],
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


# pnpm subcommands
SUBCOMMANDS = {
    "add", "audit", "bin", "config", "create", "dedupe", "deploy", "dlx",
    "doctor", "env", "exec", "fetch", "import", "init", "install",
    "install-test", "licenses", "link", "list", "ls", "outdated", "pack",
    "patch", "patch-commit", "patch-remove", "prune", "publish", "rebuild",
    "remove", "root", "run", "server", "setup", "start", "store", "test",
    "unlink", "update", "why", "whoami",
    # Short forms are also valid subcommands
    "i", "in", "ins", "inst", "insta", "instal", "isnt", "isnta", "isntal",
    "rm", "un", "uninstall", "up", "upgrade", "ln", "t", "tst", "ll", "la",
    "dx", "c", "rb",
}

# pnpm subcommand aliases mapping to canonical form
SUBCOMMAND_ALIASES = {
    "i": "install",
    "in": "install",
    "ins": "install",
    "inst": "install",
    "insta": "install",
    "instal": "install",
    "isnt": "install",  # Common typo, accepted by pnpm
    "isnta": "install",
    "isntal": "install",
    "rm": "remove",
    "un": "remove",
    "uninstall": "remove",
    "up": "update",
    "upgrade": "update",
    "ln": "link",
    "t": "test",
    "tst": "test",
    "ll": "list",
    "la": "list",
    "ls": "list",
    "dx": "dlx",
    "c": "config",
    "rb": "rebuild",
}

# Subcommands that accept package names
PACKAGE_SUBCOMMANDS = {
    "add", "remove", "update", "link", "unlink", "why", "list", "outdated",
    "patch", "publish",
}

# Subcommands that take script or binary names
SCRIPT_SUBCOMMANDS = {"run", "exec", "dlx", "create"}

# Options that take one argument
OPTIONS_WITH_ARGUMENTS = {
    "--dir", "-C", "--workspace-root", "-w", "--filter", "--filter-prod",
    "--store-dir", "--virtual-store-dir", "--modules-dir", "--lockfile-dir",
    "--registry", "--config", "--loglevel", "--reporter", "--package",
    "--use-node-version", "--network-concurrency", "--child-concurrency",
    "--workspace-concurrency", "--resolution-mode", "--save-workspace-protocol",
    "--tag", "--access", "--otp", "--depth",
}

# Options whose arguments are paths
PATH_OPTIONS = {
    "--dir", "-C", "--store-dir", "--virtual-store-dir", "--modules-dir",
    "--lockfile-dir", "--config",
}


def parse_pnpm_args(arguments: list[str]) -> dict[str, Any]:
    """Parse pnpm command arguments."""
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

        # First non-option is the subcommand, or an implicit script run
        if subcommand is None:
            if arg in SUBCOMMANDS or arg in SUBCOMMAND_ALIASES:
                subcommand = SUBCOMMAND_ALIASES.get(arg, arg)
                named["subcommand"] = subcommand
                i += 1
                continue
            # `pnpm build` means `pnpm run build`
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


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        arguments = input_data.get("arguments", [])
        result = parse_pnpm_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
