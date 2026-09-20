#!/usr/bin/env python3
"""
nix-shell command parser for shfmt-permissions.

Parses nix-shell commands to extract options, named values for propagation, and paths.

Input (JSON on stdin):
    {"arguments": ["--run", "npm install", "-p", "nodejs"]}

Output (JSON on stdout):
    {
        "options": [{"name": "--run", "arguments": ["npm install"]}, {"name": "-p", "arguments": ["nodejs"]}],
        "positionals": [],
        "subcommand": null,
        "named": {"command": "npm install", "packages": ["nodejs"]},
        "paths": [],
        "nestedCommands": [{"text": "npm install", "shape": "shell"}]
    }

`--run`/`--command` take ONE argument that is a shell STRING, not already-split argv
(unlike `timeout`/`nix`'s trailing argv) - so it is published verbatim on `nestedCommands`
with `shape: "shell"`, alongside the unchanged `named.command`. When the option appears
more than once, only the LAST wins (mirrors `named.command`'s own last-write-wins
behaviour) - that is the one nix-shell actually honours, so publishing an earlier ignored
one would evaluate a command that never runs. A bare `nix-shell` or `nix-shell shell.nix`
with no `--run`/`--command` publishes neither: no command is going to run at all, and
that is knowable, unlike bare `xargs`'s statically-known `echo` default.

Note: Paths from the --run/--command inner commands are handled via propagate recursion,
so they're not included in this parser's paths output.
"""

import json
import os
import sys
from typing import Any


# Options that consume one argument
OPTIONS_WITH_ONE_ARGUMENT = {
    "--run", "--command",  # Command to execute (key for propagation)
    "-i",  # Interpreter path
    "-A", "--attr",  # Attribute path
}

# Options that consume two arguments (key-value pairs)
OPTIONS_WITH_TWO_ARGUMENTS = {
    "--arg",  # Nix expression argument (name value)
    "--argstr",  # String argument (name value)
}

# Options that can be specified multiple times (accumulate values)
MULTI_VALUE_OPTIONS = {
    "-p", "--packages",  # Packages to make available
    "--keep", "-k",  # Environment variables to keep
    "-I", "--include",  # Paths to add to NIX_PATH
}

# Boolean flags (no arguments)
FLAG_OPTIONS = {
    "--pure",  # Pure environment
    "-E", "--expr",  # Interpret path as expression
    "--impure",  # Allow impure evaluation
}

# Options whose arguments are file/directory paths
PATH_OPTIONS = {
    "-i",  # Interpreter path
    "-I", "--include",  # Paths to add to NIX_PATH
}


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


def parse_nix_shell_args(arguments: list[str]) -> dict[str, Any]:
    """Parse nix-shell command arguments."""
    options = []
    positionals = []
    named = {}
    paths = []
    positional_index = 0
    options_stopped = False
    nested_command_text = None

    # Initialize multi-value named entries
    packages = []
    keep = []
    include = []
    arg_dict = {}
    argstr_dict = {}

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

                # Extract named values
                if opt_name in ("--run", "--command"):
                    named["command"] = opt_value
                    nested_command_text = opt_value
                elif opt_name == "--attr":
                    named["attr"] = opt_value
                elif opt_name == "--packages":
                    packages.append(opt_value)
                elif opt_name == "--keep":
                    keep.append(opt_value)
                elif opt_name == "--include":
                    include.append(opt_value)
                i += 1
                continue

            # Boolean flags
            if arg in FLAG_OPTIONS:
                options.append({"name": arg, "arguments": []})
                if arg == "--pure":
                    named["pure"] = True
                elif arg in ("-E", "--expr"):
                    named["expr"] = True
                i += 1
                continue

            # Options with two arguments (--arg name value, --argstr name value)
            if arg in OPTIONS_WITH_TWO_ARGUMENTS:
                opt_args = []
                if i + 2 < len(arguments):
                    name_arg = arguments[i + 1]
                    value_arg = arguments[i + 2]
                    opt_args = [name_arg, value_arg]
                    if arg == "--arg":
                        arg_dict[name_arg] = value_arg
                    elif arg == "--argstr":
                        argstr_dict[name_arg] = value_arg
                    i += 2
                elif i + 1 < len(arguments):
                    # Partial - only name provided
                    opt_args = [arguments[i + 1]]
                    i += 1
                options.append({"name": arg, "arguments": opt_args})
                i += 1
                continue

            # Multi-value options (can be specified multiple times)
            if arg in MULTI_VALUE_OPTIONS:
                opt_args = []
                if i + 1 < len(arguments):
                    i += 1
                    opt_args.append(arguments[i])
                    if arg in ("-p", "--packages"):
                        packages.append(arguments[i])
                    elif arg in ("--keep", "-k"):
                        keep.append(arguments[i])
                    elif arg in ("-I", "--include"):
                        include.append(arguments[i])
                        # -I/--include are path options
                        paths.append(resolve_path(arguments[i]))
                options.append({"name": arg, "arguments": opt_args})
                i += 1
                continue

            # Options with one argument
            if arg in OPTIONS_WITH_ONE_ARGUMENT:
                opt_args = []
                if i + 1 < len(arguments):
                    i += 1
                    opt_args.append(arguments[i])
                    if arg in ("--run", "--command"):
                        named["command"] = arguments[i]
                        nested_command_text = arguments[i]
                    elif arg == "-i":
                        named["interpreter"] = arguments[i]
                        # -i is a path option
                        paths.append(resolve_path(arguments[i]))
                    elif arg in ("-A", "--attr"):
                        named["attr"] = arguments[i]
                options.append({"name": arg, "arguments": opt_args})
                i += 1
                continue

            # Unknown option - treat as flag
            options.append({"name": arg, "arguments": []})
            i += 1
            continue

        # Positional argument (nix expression path)
        positionals.append({"index": positional_index, "value": arg})
        if positional_index == 0:
            named["path"] = arg
            # First positional is the nix expression path
            paths.append(resolve_path(arg))
        positional_index += 1
        i += 1

    # Add accumulated multi-value entries to named
    if packages:
        named["packages"] = packages
    if keep:
        named["keep"] = keep
    if include:
        named["include"] = include
    if arg_dict:
        named["arg"] = arg_dict
    if argstr_dict:
        named["argstr"] = argstr_dict

    result = {
        "options": options,
        "positionals": positionals,
        "subcommand": None,
        "named": named,
        "paths": paths
    }
    if nested_command_text is not None:
        result["nestedCommands"] = [{"text": nested_command_text, "shape": "shell"}]
    return result


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        arguments = input_data.get("arguments", [])
        result = parse_nix_shell_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
