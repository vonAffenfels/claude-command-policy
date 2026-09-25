#!/usr/bin/env python3
"""
npm command parser for shfmt-permissions.

Parses npm commands to extract subcommand, packages, and relevant options.
Handles npm command aliases (i = install, rm = uninstall, etc.).

Input (JSON on stdin):
    {"arguments": ["i", "-g", "typescript"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-g", "arguments": []}],
        "positionals": [{"index": 0, "value": "typescript"}],
        "subcommand": null,
        "named": {
            "subcommand": "install",
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


# npm subcommands
SUBCOMMANDS = {
    "access", "adduser", "audit", "bin", "bugs", "cache", "ci", "completion",
    "config", "dedupe", "deprecate", "diff", "dist-tag", "docs", "doctor",
    "edit", "exec", "explain", "explore", "find-dupes", "fund", "get", "help",
    "help-search", "hook", "init", "install", "install-ci-test", "install-test",
    "link", "ll", "login", "logout", "ls", "org", "outdated", "owner", "pack",
    "ping", "pkg", "prefix", "profile", "prune", "publish", "query", "rebuild",
    "repo", "restart", "root", "run", "run-script", "search", "set", "shrinkwrap",
    "star", "stars", "start", "stop", "team", "test", "token", "uninstall",
    "unpublish", "unstar", "update", "version", "view", "whoami",
    # Short forms are also valid subcommands
    "i", "add", "isntall", "rm", "remove", "un", "unlink", "r", "up", "udpate",
    "ln", "t", "tst", "s", "se", "c", "cit", "sit", "it", "ddp", "v", "verison",
    "find", "why", "la", "x", "npx",
}

# npm subcommand aliases mapping to canonical form
SUBCOMMAND_ALIASES = {
    "i": "install",
    "add": "install",
    "isntall": "install",  # Common typo
    "rm": "uninstall",
    "remove": "uninstall",
    "un": "uninstall",
    "unlink": "uninstall",
    "r": "uninstall",
    "up": "update",
    "udpate": "update",  # Common typo
    "upgrade": "update",
    "ln": "link",
    "t": "test",
    "tst": "test",
    "s": "search",
    "se": "search",
    "c": "config",
    "cit": "install-ci-test",
    "sit": "install-test",
    "it": "install-test",
    "ddp": "dedupe",
    "v": "view",
    "verison": "version",  # Common typo
    "find": "explore",
    "why": "explain",
    "la": "ls",
    "ll": "ls",
    "x": "exec",
    "npx": "exec",
}

# Subcommands that accept package names
PACKAGE_SUBCOMMANDS = {
    "install", "uninstall", "update", "link", "view", "info", "show",
    "outdated", "deprecate", "owner", "star", "unstar", "unpublish",
    "dist-tag", "access", "publish",
}

# Subcommands that take script names
SCRIPT_SUBCOMMANDS = {"run", "run-script", "exec", "x", "npx"}

# Options that take one argument
OPTIONS_WITH_ARGUMENTS = {
    "--prefix", "--userconfig", "--globalconfig", "--registry",
    "--cache", "--tmp", "--editor", "--viewer",
    "--loglevel", "--maxsockets", "--fetch-retries", "--fetch-retry-factor",
    "--fetch-retry-mintimeout", "--fetch-retry-maxtimeout",
    "--searchlimit", "--searchstaleness", "--searchopts",
    "--workspace", "-w", "--workspaces",
    "--tag", "--access", "--otp",
}

# Options whose arguments are paths
PATH_OPTIONS = {
    "--prefix", "--userconfig", "--globalconfig", "--cache", "--tmp",
}


def parse_npm_args(arguments: list[str]) -> dict[str, Any]:
    """Parse npm command arguments."""
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

        # First non-option is the subcommand
        if subcommand is None:
            if arg in SUBCOMMANDS or arg in SUBCOMMAND_ALIASES:
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
                # Package names can be @scope/name or just name
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
    (improvement 20260925-120037). npm never wraps another command."""
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
        result = parse_npm_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
