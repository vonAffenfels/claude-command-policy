"""Read/Grep/Glob path-permission decision - allowedPaths' own decision
domain, separate from the six-pass bash pipeline (config.py's
`_decision_for_statement`): an unmatched path is `passthrough` (no opinion,
Claude Code's own dialog decides), never `deny` - allowedPaths only ever
widens what auto-allows. Mirrors shfmt-permissions' analyze-path.py (READ
ONLY prior art), rebuilt on the `PathConfig`/`PathResolutionContext` value
objects instead of raw dicts.

Tool-alias expansion ("all" -> read/grep/glob, "search" -> grep/glob) lives
here rather than on `PathRule`/`PathConfig` - see path_config.py's own
module docstring ("Tool-alias expansion is analyze-path's concern, not
construction's").
"""

from __future__ import annotations

import os

from permission_decision import PermissionDecision

TOOL_ALIASES = {
    "all": ("read", "grep", "glob"),
    "search": ("grep", "glob"),
}


def decision_for(tool_name, path, path_config, resolution):
    if not path:
        return PermissionDecision.passthrough()

    normalized_tool = (tool_name or "").lower()
    candidate_paths = [
        rule.path for rule in path_config.rules if normalized_tool in _expanded_tools(rule.tools)
    ]
    if not candidate_paths:
        return PermissionDecision.passthrough()

    target = resolution.absolute_path_of(path)
    if any(_matches(target, allowed, resolution) for allowed in candidate_paths):
        return PermissionDecision.allow()
    return PermissionDecision.passthrough()


def _expanded_tools(tools):
    expanded = set()
    for tool in tools:
        expanded.update(TOOL_ALIASES.get(tool, (tool,)))
    return expanded


def _matches(target, allowed_raw, resolution):
    allowed = resolution.absolute_path_of(allowed_raw)
    if target == allowed:
        return True
    return resolution.is_directory(allowed) and target.startswith(allowed + os.sep)
