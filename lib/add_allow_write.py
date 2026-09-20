"""Write-side logic behind `bin/add-allow-policy`.

By the time this module's `main()` runs, `Config.decision_for` (via
escalation_policy.py's `add_allow_policy_transform`) has already forced
`ask` for this exact invocation, carrying the JSON diff shown in the
permission dialog - approving the dialog IS the write. This module performs
it: parses `--scope`/`--intent`/the entry, VALIDATES BEFORE WRITING (a
missing `--intent` or a missing entry text is rejected rather than producing
an undocumented write - `--intent` is ALSO required at the ask-recognition
layer since the strict-grammar reopening (see escalation_policy.py's module
docstring), but it is independently re-checked here too, at the point the
config file actually changes, as defence in depth rather than a
replacement), and appends the entry. Never touches any other key.

Ported from packages/shfmt-permissions/scripts/propose_allow.py, collapsing
its two scope-specific commands into one `--scope user|project` flag and its
config file into `command-policy.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def config_path(scope):
    """The target config file for a proposal scope ('user' or 'project')."""
    if scope == "user":
        home = os.environ.get("HOME", "")
        return Path(home) / ".claude" / "command-policy.json"
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    return Path(project_dir) / ".claude" / "command-policy.json"


def parse_entry(entry_text):
    """A bare program name stays a string; a '{'-prefixed argument is parsed
    as the JSON allowedCommands entry object it represents."""
    stripped = entry_text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    return stripped


def apply_proposal(scope, entry_text):
    """Append the proposed entry to allowedCommands in the scope's config
    file. Creates the file (and its .claude/ directory) if it does not exist
    yet. Returns the path written."""
    entry = parse_entry(entry_text)
    path = config_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)

    config = json.loads(path.read_text()) if path.exists() else {}
    config.setdefault("allowedCommands", []).append(entry)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return path


def main(argv):
    parser = argparse.ArgumentParser(
        prog="add-allow-policy",
        description=(
            "Propose - and, once approved, write - a new allowedCommands entry to the "
            "user or project command-policy config. This command ALWAYS triggers a "
            "permission prompt showing the exact JSON diff; it never silently auto-runs."
        ),
    )
    parser.add_argument("entry", help="Bare program name, or a JSON allowedCommands entry object.")
    parser.add_argument(
        "--scope", choices=("user", "project"), required=True, help="Which config file to write."
    )
    parser.add_argument("--intent", required=True, help="Why this entry is needed (shown in the permission prompt).")
    args = parser.parse_args(argv)

    if not args.intent.strip():
        print("error: --intent must not be blank.", file=sys.stderr)
        return 2

    try:
        path = apply_proposal(args.scope, args.entry)
    except json.JSONDecodeError as error:
        print(f"error: '{args.entry}' is not valid JSON: {error}", file=sys.stderr)
        return 2

    print(f"Added entry to {path}")
    print(f"Reason: {args.intent}")
    return 0
