"""Report which Bash commands run in a Claude Code session are NOT
auto-approved by command-policy under the current merged config.

Because Claude Code records no auto-vs-manual permission decision on disk,
the decision is RECOMPUTED deterministically: resolve the session name to
its transcript, extract every Bash command run (including subagent-issued
commands), and re-run each through the current merged `Config`'s
`decision_for`.

Ported largely unchanged from `packages/shfmt-permissions/bin/shfmt-session-
approvals` (READ ONLY prior art): session/transcript resolution,
permission-mode reading, and command extraction are decision-engine-
agnostic. Only `classify()` (which decision method it calls) and `render()`
(the bucket headings) change for the new deny+hint outcome model - see
below.

WHY THE BUCKETS ARE DIFFERENT FROM THE OLD SCRIPT. Under the old engine,
`deny` was rare (blocked commands only) and `ask`/`passthrough` were the
common "not auto-approved" outcomes. Under the new default-deny-with-hint
model, almost every non-allowed command decides `deny` (carrying the
equivalence-search hint) - `ask` is now reserved for the two escalation
paths (a `bypass-policy`-forced ask, or an `add-allow-policy` proposal) and
`passthrough` for a bypass that needed no forcing. So `deny` is now the
PRIMARY section a human reviewing this report acts on, not an informational
tail - `render()`'s heading text reflects that.

A bypass-wrapped command is bucketed under `BYPASS_BUCKET` regardless of its
own decision, the same "priced user intervention, not an ordinary gap" rule
the old script used - see `classify()`.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from statement import Statement

DECISIONS = ("allow", "deny", "ask", "passthrough")

BYPASS_WRAPPER_PROGRAM = "bypass-policy"
BYPASS_BUCKET = "bypass"

SUPPRESSING_MODES = ("acceptEdits", "bypassPermissions")

DENY_HEADING = "## Not auto-approved (deny - see each command's hint for an auto-approved alternative)"
ASK_HEADING = "## Will prompt (ask)"
PASSTHROUGH_HEADING = "## No opinion (passthrough - Claude Code's own permission rules decide)"
BYPASS_HEADING = "## Bypassed (counts as a user intervention - see bypass-policy)"
CONFIG_HANDOFF = "Hand chosen commands to add-allow-policy to add allow-list entries."


@dataclass
class SessionMatch:
    """A transcript resolved from a session name.

    other_count is how many OLDER sessions share the same name (0 when
    unique).
    """

    session_id: str
    transcript_path: Path
    mtime: float
    other_count: int


def encode_project_dir(cwd):
    """Encode an absolute cwd to its ~/.claude/projects/ directory name.

    Claude Code encodes a project path by replacing '/.' with '--' first (so
    a leading-dot segment like '/.claude' becomes '--claude'), then every
    remaining '/' with '-'.
    """
    return cwd.replace("/.", "--").replace("/", "-")


def _iter_transcript_records(transcript_path):
    """Yield parsed JSON records from a JSONL transcript, skipping bad lines."""
    with open(transcript_path) as transcript_file:
        for line in transcript_file:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _transcript_has_title(transcript_path, name):
    return any(
        record.get("type") == "custom-title" and record.get("customTitle") == name
        for record in _iter_transcript_records(transcript_path)
    )


def resolve_session(name, project_transcript_dir):
    """Resolve a session name to its most-recently-modified matching
    transcript.

    A transcript MATCHES when it carries a {type:'custom-title',
    customTitle:name} record. Names are reused across sessions; the most
    recent (by file mtime) wins and other_count records how many older
    sessions share the name. Returns None when no transcript matches.
    """
    project_transcript_dir = Path(project_transcript_dir)
    matches = [
        transcript
        for transcript in sorted(project_transcript_dir.glob("*.jsonl"))
        if _transcript_has_title(transcript, name)
    ]
    if not matches:
        return None

    most_recent = max(matches, key=lambda transcript: transcript.stat().st_mtime)
    return SessionMatch(
        session_id=most_recent.stem,
        transcript_path=most_recent,
        mtime=most_recent.stat().st_mtime,
        other_count=len(matches) - 1,
    )


def read_permission_modes(transcript_path):
    """Distinct permission modes observed in a transcript, in first-seen
    order.

    A mode of 'acceptEdits' or 'bypassPermissions' means live prompts were
    suppressed while it was active - the recompute still reports what is
    not allow-listed, but the header flags that suppression.
    """
    modes = []
    for record in _iter_transcript_records(transcript_path):
        if record.get("type") != "permission-mode":
            continue
        mode = record.get("permissionMode")
        if mode and mode not in modes:
            modes.append(mode)
    return modes


def _bash_commands_in_transcript(transcript_path):
    """Bash tool_use commands issued by assistant records in one transcript file."""
    commands = []
    for record in _iter_transcript_records(transcript_path):
        if record.get("type") != "assistant":
            continue
        content = record.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use" and item.get("name") == "Bash":
                command = item.get("input", {}).get("command")
                if command:
                    commands.append(command)
    return commands


def _subagent_transcripts(transcript_path):
    """Subagent transcript files for a session's main transcript, sorted by
    name.

    Subagent Bash lives in <session-id>/subagents/*.jsonl (the '.jsonl' glob
    excludes the '.meta.json' sidecars). session-id is the transcript
    filename without its extension.
    """
    transcript_path = Path(transcript_path)
    session_id = transcript_path.stem
    subagents_dir = transcript_path.parent / session_id / "subagents"
    if not subagents_dir.is_dir():
        return []
    return sorted(subagents_dir.glob("*.jsonl"))


def extract_bash_commands(transcript_path, include_subagents=True):
    """Every Bash command run in a session's main transcript.

    When include_subagents is True, subagent-issued Bash commands (recorded
    in <session-id>/subagents/*.jsonl, not the main transcript) are included
    too - they also pass through the PreToolUse hook and can prompt.
    """
    commands = _bash_commands_in_transcript(transcript_path)
    if include_subagents:
        for subagent_transcript in _subagent_transcripts(transcript_path):
            commands.extend(_bash_commands_in_transcript(subagent_transcript))
    return commands


def is_bypass_wrapped(command):
    """Whether `command` is exactly `bypass-policy <wrapped>` - the same
    "sole invoked program" recognition rule escalation_policy.py uses, so a
    command merely SHARING a line with the wrapper (`bypass-policy true &&
    rm -rf /`) is not counted as an intervention."""
    statement = Statement.from_command(command)
    if statement is None:
        return False
    return statement.as_sole_invoked_program() == BYPASS_WRAPPER_PROGRAM


def classify(commands, config):
    """Bucket commands by their recomputed permission decision.

    Commands are deduped by exact string; each bucket holds (count, command)
    entries sorted by count descending, then command ascending for
    stability. `config` is the current merged `Config` - `decision_for` is
    called directly rather than through an injected analyzer, since that is
    now the one settled public entrypoint.

    A bypass-wrapped command is bucketed under BYPASS_BUCKET instead of
    whatever it would otherwise decide: it is a priced user intervention
    (see bypass-policy), not an ordinary gap.
    """
    counts = Counter(commands)
    buckets = {decision: [] for decision in DECISIONS}
    buckets[BYPASS_BUCKET] = []
    for command, count in counts.items():
        if is_bypass_wrapped(command):
            buckets[BYPASS_BUCKET].append((count, command))
            continue
        decision = config.decision_for(command).decision
        buckets.setdefault(decision, []).append((count, command))
    for entries in buckets.values():
        entries.sort(key=lambda entry: (-entry[0], entry[1]))
    return buckets


def _format_entries(entries):
    """Render (count, command) entries as '<count>x  <command>' lines."""
    if not entries:
        return ["(none)"]
    return [f"{count}x  {command}" for count, command in entries]


def _render_section(heading, entries):
    return [heading, *_format_entries(entries), ""]


def render(
    buckets,
    *,
    session_name,
    session_id,
    transcript_path,
    last_modified,
    permission_modes,
    shfmt_present,
    other_count,
):
    """Render the approval-gap report as a plain-text string.

    Pure over its arguments: all filesystem/env facts are gathered at the
    CLI edge and passed in. Omits already-auto-approved (allow) commands;
    `deny` is now the primary section (see this module's docstring), with
    `ask`/`passthrough`/bypass following.
    """
    lines = [
        f"Session: {session_name}",
        f"Session ID: {session_id}",
        f"Transcript: {transcript_path}",
        f"Last modified: {last_modified}",
        f"Permission mode(s): {', '.join(permission_modes) if permission_modes else 'unknown'}",
    ]

    if any(mode in SUPPRESSING_MODES for mode in permission_modes):
        lines.append(
            "⚠ acceptEdits/bypassPermissions was active - live prompts were suppressed; "
            "the list below is recomputed against the current config."
        )

    if shfmt_present:
        lines.append("shfmt: present")
    else:
        lines.append(
            "⚠⚠ shfmt is NOT installed - every command was forced to 'passthrough'. "
            "THIS REPORT IS INVALID. Install shfmt and re-run."
        )

    if other_count > 0:
        lines.append(
            f"Note: {other_count} older session(s) share this name - analyzed the most recent. "
            "Target another with --session-id <uuid>."
        )

    lines.append("")
    lines.extend(_render_section(DENY_HEADING, buckets.get("deny", [])))
    lines.extend(_render_section(ASK_HEADING, buckets.get("ask", [])))
    lines.extend(_render_section(PASSTHROUGH_HEADING, buckets.get("passthrough", [])))

    bypass_entries = buckets.get(BYPASS_BUCKET, [])
    if bypass_entries:
        lines.extend(_render_section(BYPASS_HEADING, bypass_entries))

    lines.append(CONFIG_HANDOFF)
    return "\n".join(lines)
