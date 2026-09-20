"""Pure response-building functions behind the command-policy hook
entrypoints.

SessionStart takes plain text on stdout, SubagentStart requires the JSON
hookSpecificOutput.additionalContext envelope, and the PostToolUse config
linter reports only when its own write touched the config file - see
shfmt-permissions' session-start-render.py / subagent-start-render.py /
lint-config-on-write.py for the measured protocol these mirror. Each bin/
entrypoint stays a thin subprocess wrapper calling exactly one of these; the
logic itself is unit-tested here with no stdin/stdout plumbing.

`pretooluse_bash_response`/`pretooluse_path_response` are leaf
20260914-213825's own hand-back from leaf 20260914-213652 ("Leaf
20260914-213825 owns the mapping to the hook's JSON protocol"): they mirror
the OLD `AnalysisResult.to_json_response()` shape (READ ONLY prior art at
packages/shfmt-permissions/scripts/analyze-bash-command.py:847-857) -
`passthrough` -> `None` (hook prints nothing, Claude Code's own dialog takes
over); every other outcome -> the `hookSpecificOutput.permissionDecision`/
`permissionDecisionReason` envelope. A `PermissionDecision`'s `reason` is
either a tuple of `Reason` value objects (the ordinary pipeline) or an
already-rendered string (the escalation transformers in
escalation_policy.py) - `_reason_text` renders the former via
`reason_renderer.render` and passes the latter through unchanged.
"""

from __future__ import annotations

from reason_renderer import render

CONFIG_FILE_NAME = "command-policy.json"

_TOOL_INPUT_PATH_KEYS = {"read": "file_path"}
_DEFAULT_PATH_KEY = "path"


def subagent_start_envelope(config):
    return {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": config.explain(),
        }
    }


def touches_config_path(tool_input):
    file_path = tool_input.get("file_path") or ""
    return file_path.endswith(CONFIG_FILE_NAME)


def config_write_lint_response(config):
    warnings = config.warnings()
    if not warnings:
        return None

    lines = ["command-policy config lint findings (merged user + project config):"]
    lines.extend(f"  - {warning.message}" for warning in warnings)
    return {"systemMessage": "\n".join(lines)}


def pretooluse_bash_response(decision):
    return _pretooluse_response(decision)


def pretooluse_path_response(decision):
    return _pretooluse_response(decision)


def _pretooluse_response(decision):
    if decision.decision == "passthrough":
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.decision,
            "permissionDecisionReason": _reason_text(decision.reason),
        }
    }


def _reason_text(reason):
    if reason is None:
        return ""
    if isinstance(reason, str):
        return reason
    return render(reason)


def path_from_tool_input(tool_name, tool_input):
    """Read's own `file_path` vs Grep/Glob's `path` key split - mirrors
    shfmt-permissions' analyze-path.py `extract_path_from_hook_input`."""
    tool_input = tool_input or {}
    key = _TOOL_INPUT_PATH_KEYS.get((tool_name or "").lower(), _DEFAULT_PATH_KEY)
    return tool_input.get(key)
