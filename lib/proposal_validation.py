"""proposal_problems(entry_text, scope, path_resolution): validates one
add-allow-policy proposal's entry text (a bare program name, or a JSON
allowedCommands entry object) the same way loading it into a real config
would - every problem `AllowedCommand.from_entry` would find at construction,
plus (for an external parser) whatever its own describe response answers.

Shared by `escalation_policy.add_allow_policy_transform` (the ask path,
refusing BEFORE asking - improvement 20260925-120037's success criterion)
and `add_allow_write.apply_proposal`/`main` (the write side, re-checking as
defence in depth, the same "ask-side check plus a write-side re-check"
posture `--intent` already has).
"""

from __future__ import annotations

import json

from allowed_command import AllowedCommand
from described_problems import described_problems_for_entry


def proposal_problems(entry_text, scope, path_resolution):
    try:
        entry = parse_entry(entry_text)
    except json.JSONDecodeError as exc:
        return (f"{entry_text!r} is not valid JSON: {exc}",)

    built = AllowedCommand.from_entry(entry, path_resolution, source=scope)
    problems = list(built.problems())

    from describer import Describer  # lazy: subprocess-touching, only reached on this rare escalation path

    problems.extend(described_problems_for_entry(built, Describer()))
    return tuple(problems)


def parse_entry(entry_text):
    """A bare program name stays a string; a '{'-prefixed argument is parsed
    as the JSON allowedCommands entry object it represents. The single
    source of truth for this shape - `add_allow_write.py` imports it from
    here rather than keeping its own copy."""
    stripped = entry_text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    return stripped
