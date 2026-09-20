#!/usr/bin/env python3
"""
spawn-claude command parser for command-policy.

Parses the home-manager nushell wrapper `spawn-claude <name> [...args]`
(`main [name: string, ...args: string]`). `spawn-claude` starts an
interactive `claude --name <name>` session: everything before the FIRST
literal `--` in `args` is forwarded to `claude` verbatim; everything after it
is joined with spaces into the seed prompt.

Three spans, three treatments:
  - the session name (argument 0) - never a path candidate. It is a display
    name (prompt box, /resume picker, terminal title) and a zellij pane/stack
    title, never a filename.
  - the forwarded-args span (before the separator) - TOTAL path candidacy,
    mirroring `default_parser.py`'s "no knowledge means no exemption": every
    non-option token, and the value half of a `--name=value` option, becomes
    a candidate. No `claude` flag is named anywhere in this file - that is
    the point, since a hand-maintained list of its path-valued flags would
    already be incomplete (`--plugin-dir` is real and undocumented in the
    brief that motivated this parser) and a list of the safe ones fails open
    the instant `claude` grows a new one.
  - the prompt (everything after the separator) - never a path candidate. It
    is a chat message, joined into one string, never treated as a filename by
    `spawn-claude` itself. This is load-bearing: an orchestrator dispatch's
    seed prompt begins with `/` because it is a slash command, and a bare
    path-shaped positional would otherwise deny it outright.

The session name and the prompt are published on `named` only
(`sessionName`, `prompt`, `forwardedFlags`) - `named` is invisible to
`ParameterRegexMatcher`/`PositionalArgRegexMatcher`, so a prompt that quotes
a dangerous flag in prose cannot pollute a regex filter or contribute a path
candidate.

Input (JSON on stdin):
    {"arguments": ["name", "--settings", "/etc/passwd"]}

Output (JSON on stdout):
    {
        "options": [{"name": "--settings", "arguments": []}],
        "positionals": [{"index": 0, "value": "/etc/passwd"}],
        "subcommand": null,
        "named": {"sessionName": "name", "forwardedFlags": "--settings /etc/passwd"},
        "paths": ["/etc/passwd"]
    }
"""

import json
import os
import sys
from typing import Any


def resolve_path(value: str) -> str | None:
    """Resolve a path value to absolute form. Mirrors `parsers/git.py`'s
    `resolve_path` shape."""
    if not value:
        return None
    if value.startswith("~"):
        return os.path.normpath(os.path.expanduser(value))
    if value.startswith("/"):
        return os.path.normpath(value)
    return os.path.abspath(value)


def split_spawn_claude_spans(arguments: list[str]) -> tuple[str | None, list[str], str | None]:
    """Split raw arguments into (session_name, forwarded_args, prompt),
    mirroring the real nushell script exactly: the FIRST literal `--` after
    the session name is the prompt separator. No `--` at all means every
    remaining argument is forwarded and there is no prompt - a documented,
    ordinary case, not an error."""
    if not arguments:
        return None, [], None

    session_name = arguments[0]
    rest = arguments[1:]

    separator_index = None
    for index, argument in enumerate(rest):
        if argument == "--":
            separator_index = index
            break

    if separator_index is None:
        return session_name, rest, None

    forwarded_args = rest[:separator_index]
    prompt = " ".join(rest[separator_index + 1 :])
    return session_name, forwarded_args, prompt


def classify_forwarded_span(forwarded_args: list[str]) -> tuple[list[dict], list[dict]]:
    """Classify the forwarded-args span exactly like `DefaultParser`: a
    dash-prefixed word is an option, everything else a positional."""
    options: list[dict[str, Any]] = []
    positionals: list[dict[str, Any]] = []
    index = 0
    for argument in forwarded_args:
        if argument.startswith("-"):
            options.append({"name": argument, "arguments": []})
        else:
            positionals.append({"index": index, "value": argument})
            index += 1
    return options, positionals


def path_candidates_for(forwarded_args: list[str]) -> list[str]:
    """Every value in the forwarded-args span becomes a path candidate: a
    bare positional contributes its whole text, and a `--name=value` word
    contributes the VALUE after the `=` split - never the option name
    itself, so `--settings=/etc/passwd` resolves to `/etc/passwd`, never
    `<project>/--settings=/etc/passwd`. A bare flag with no `=` names no
    value of its own and contributes nothing - it is a grammar word, not
    user content, and the flag name itself is never what a path-valued
    `claude` flag actually points at."""
    candidates = []
    for argument in forwarded_args:
        operand = _path_operand_of(argument)
        if not operand:
            continue
        resolved = resolve_path(operand)
        if resolved:
            candidates.append(resolved)
    return candidates


def _path_operand_of(argument: str) -> str | None:
    if not argument.startswith("-"):
        return argument
    if "=" in argument:
        return argument.partition("=")[2]
    return None


def parse_spawn_claude_args(arguments: list[str]) -> dict[str, Any]:
    session_name, forwarded_args, prompt = split_spawn_claude_spans(arguments)
    options, positionals = classify_forwarded_span(forwarded_args)

    named: dict[str, Any] = {}
    if session_name is not None:
        named["sessionName"] = session_name
    if forwarded_args:
        named["forwardedFlags"] = " ".join(forwarded_args)
    if prompt is not None:
        named["prompt"] = prompt

    return {
        "options": options,
        "positionals": positionals,
        "subcommand": None,
        "named": named,
        "paths": path_candidates_for(forwarded_args),
    }


def main():
    """Main entry point."""
    try:
        input_data = json.loads(sys.stdin.read())
        arguments = input_data.get("arguments", [])
        result = parse_spawn_claude_args(arguments)
        print(json.dumps(result))
    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
