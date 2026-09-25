#!/usr/bin/env python3
"""
Git command parser for shfmt-permissions.

Parses git commands to extract subcommand information, named values, and paths.

Input (JSON on stdin):
    {"arguments": ["commit", "-m", "message", "--", "file.txt"]}

Output (JSON on stdout):
    {
        "options": [{"name": "-m", "arguments": ["message"]}],
        "positionals": [{"index": 0, "value": "file.txt"}],
        "subcommand": null,
        "named": {"subcommand": "commit", "message": "message"},
        "paths": ["/absolute/path/to/file.txt"]
    }
"""

import json
import os
import sys
from typing import Any

# Git options that consume one argument
OPTIONS_WITH_ARGUMENTS = {
    # Global options
    "-C", "-c", "--config", "--work-tree", "--git-dir", "--namespace",
    # commit
    "-m", "--message", "-F", "--file", "-t", "--template", "-e", "--edit",
    "--author", "--date", "--cleanup",
    # branch
    "-u", "--set-upstream-to", "-t", "--track", "--set-upstream",
    # checkout/switch
    "-b", "-B", "--orphan", "-t", "--track",
    # push/pull
    "--repo", "--receive-pack", "--exec",
    # clone
    "-o", "--origin", "-b", "--branch", "--reference", "--depth",
    "--separate-git-dir", "-c", "--config", "-j", "--jobs",
    # add
    "-p", "--patch", "-e", "--edit", "-u", "--update", "-A", "--all",
    # log
    "-n", "--max-count", "--skip", "--since", "--until", "--after", "--before",
    "--author", "--committer", "--grep", "-S", "-G", "-L",
    # diff
    "--diff-filter", "-U", "--unified", "--stat",
}

# Git options whose arguments are file/directory paths
PATH_OPTIONS = {
    "-C", "--work-tree", "--git-dir", "-F", "--file", "-t", "--template",
    "--reference", "--separate-git-dir",
}

# Git subcommands (first positional argument)
SUBCOMMANDS = {
    "add", "am", "annotate", "archive", "bisect", "blame", "branch", "bundle",
    "checkout", "cherry", "cherry-pick", "clean", "clone", "commit", "config",
    "describe", "diff", "difftool", "fetch", "format-patch", "gc", "grep",
    "help", "init", "log", "ls-files", "ls-remote", "ls-tree", "merge",
    "merge-base", "mergetool", "mv", "notes", "pack-objects", "pack-refs",
    "prune", "pull", "push", "range-diff", "rebase", "reflog", "remote",
    "request-pull", "reset", "restore", "revert", "rm", "shortlog", "show",
    "show-branch", "show-ref", "sparse-checkout", "stash", "status",
    "submodule", "switch", "tag", "update-index", "verify-commit", "verify-tag",
    "worktree",
}


def resolve_path(value: str) -> str | None:
    """Resolve a path value to absolute form.

    Args:
        value: Path value to resolve.

    Returns:
        Absolute path, or None if empty.
    """
    if not value:
        return None

    if value.startswith("~"):
        expanded = os.path.expanduser(value)
        return os.path.normpath(expanded)
    elif value.startswith("/"):
        return os.path.normpath(value)
    else:
        return os.path.abspath(value)


def detect_path_heuristic(value: str) -> str | None:
    """Detect if a value is a path using heuristics.

    Args:
        value: Value to check.

    Returns:
        Absolute path if detected, None otherwise.
    """
    if not value:
        return None

    if value.startswith("/"):
        return os.path.normpath(value)
    elif value.startswith("~"):
        expanded = os.path.expanduser(value)
        return os.path.normpath(expanded)
    elif "/" in value or value.startswith("."):
        return os.path.abspath(value)
    elif os.path.exists(value):
        return os.path.abspath(value)

    return None


def parse_git_args(arguments: list[str]) -> dict[str, Any]:
    """Parse git command arguments."""
    options = []
    positionals = []
    named = {}
    paths = []
    positional_index = 0
    options_stopped = False
    subcommand = None

    i = 0
    while i < len(arguments):
        arg = arguments[i]

        # Handle -- (stop option parsing)
        if arg == "--" and not options_stopped:
            options_stopped = True
            i += 1
            continue

        # After --, everything is positional (pathspec in git)
        if options_stopped:
            positionals.append({"index": positional_index, "value": arg})
            positional_index += 1
            # After --, arguments are pathspecs (file paths)
            resolved = resolve_path(arg)
            if resolved:
                paths.append(resolved)
            i += 1
            continue

        # Handle options
        if arg.startswith("-"):
            # Check for --option=value style
            if "=" in arg and arg.startswith("--"):
                eq_pos = arg.index("=")
                opt_name = arg[:eq_pos]
                opt_value = arg[eq_pos + 1:]
                options.append({"name": opt_name, "arguments": [opt_value]})
                # Check if this option takes a path argument
                if opt_name in PATH_OPTIONS:
                    resolved = resolve_path(opt_value)
                    if resolved:
                        paths.append(resolved)
            elif arg in OPTIONS_WITH_ARGUMENTS:
                # Option consumes next argument
                opt_args = []
                if i + 1 < len(arguments):
                    i += 1
                    opt_args.append(arguments[i])
                    # Extract named values for common options
                    if arg in ("-m", "--message"):
                        named["message"] = arguments[i]
                    elif arg in ("-F", "--file"):
                        named["message_file"] = arguments[i]
                    # Check if this option takes a path argument
                    if arg in PATH_OPTIONS:
                        resolved = resolve_path(arguments[i])
                        if resolved:
                            paths.append(resolved)
                options.append({"name": arg, "arguments": opt_args})
            else:
                # Option without argument (flag)
                options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Handle positional arguments
        # First positional is likely subcommand
        if subcommand is None and arg in SUBCOMMANDS:
            subcommand = arg
            named["subcommand"] = arg
        else:
            positionals.append({"index": positional_index, "value": arg})
            positional_index += 1
            # Apply heuristic to detect paths in positionals
            detected = detect_path_heuristic(arg)
            if detected:
                paths.append(detected)
        i += 1

    return {
        "options": options,
        "positionals": positionals,
        "subcommand": None,  # We don't create nested structure for simplicity
        "named": named,
        "paths": paths
    }


def describe() -> dict[str, Any]:
    """Static capabilities this parser answers via stdin {"describe": true}
    (improvement 20260925-120037). git never wraps another command."""
    return {
        "publishesNestedCommands": False,
        "namedValues": ["subcommand", "message", "message_file"],
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
        result = parse_git_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
