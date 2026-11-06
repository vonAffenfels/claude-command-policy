"""Write-side logic behind `bin/add-allow-policy`.

By the time this module's `main()` runs, `Config.decision_for` (via
escalation_policy.py's `add_allow_policy_transform`) has already forced
`ask` for this exact invocation, carrying the JSON diff shown in the
permission dialog - approving the dialog IS the write. This module performs
it: parses `--scope`/`--intent`/`--example`/the entry, VALIDATES BEFORE
WRITING (every `--example` must be allowed by the loaded effective config
plus the entry, and at least one must not be allowed without it - the same
`example_objections_for` the ask path uses; a
missing `--intent` or a missing entry text is rejected rather than producing
an undocumented write - `--intent` is ALSO required at the ask-recognition
layer since the strict-grammar reopening (see escalation_policy.py's module
docstring), but it is independently re-checked here too, at the point the
config file actually changes, as defence in depth rather than a
replacement), and appends the entry. Never touches any other key.

The ask path (`escalation_policy.add_allow_policy_transform`) already
refuses a proposal whose entry has a static or described PROBLEM before ever
asking (improvement 20260925-120037) - `proposal_validation.proposal_problems`
is re-run here too, as the same defence-in-depth posture `--intent` already
has: the ask-side check and the write-side check are two callers of the same
function, not two independently-maintained copies of the rule.

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

from config_loader import load_config_from_environment
from escalation_policy import example_objections_for
from proposal_validation import parse_entry, proposal_problems
from reason_renderer import render_clauses
from workspace import Workspace


def config_path(scope):
    """The target config file for a proposal scope ('user' or 'project').
    The project file is the one the hooks read - the MAIN repository's, even
    when run from a linked worktree (workspace.py)."""
    if scope == "user":
        home = os.environ.get("HOME", "")
        return Path(home) / ".claude" / "command-policy.json"
    return Workspace.of_this_session().project_config_file()


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


def _example_objections(entry_text, examples):
    """The ask path's example proof, re-run against the config as loaded
    from disk right now."""
    config = load_config_from_environment()
    return example_objections_for(
        parse_entry(entry_text), examples, config.decision_for, config.decision_for_with_entry
    )


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
    parser.add_argument(
        "--example",
        action="append",
        required=True,
        help="A real command the entry must allow (repeatable). Checked against the effective config plus the entry.",
    )
    args = parser.parse_args(argv)

    if not args.intent.strip():
        print("error: --intent must not be blank.", file=sys.stderr)
        return 2

    problems = proposal_problems(args.entry, args.scope, Workspace.of_this_session().path_resolution())
    if problems:
        print("error: proposed entry is invalid - nothing was written:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    example_objections = _example_objections(args.entry, args.example)
    if example_objections:
        print("error: proposed entry fails its examples - nothing was written:", file=sys.stderr)
        print(f"  - {render_clauses(example_objections)}", file=sys.stderr)
        return 2

    try:
        path = apply_proposal(args.scope, args.entry)
    except json.JSONDecodeError as error:
        print(f"error: '{args.entry}' is not valid JSON: {error}", file=sys.stderr)
        return 2

    print(f"Added entry to {path}")
    print(f"Reason: {args.intent}")
    return 0
