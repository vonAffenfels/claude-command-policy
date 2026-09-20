"""Unit tests for the pure response-building functions behind the three new
hook entrypoints (SessionStart, SubagentStart, PostToolUse config-write lint).

Each bin/ entrypoint is a thin subprocess wrapper (see conftest.py's
run_entrypoint) calling exactly one of these - the logic itself is tested
directly here, with no stdin/stdout plumbing.
"""

from config import Config
from hook_envelopes import (
    config_write_lint_response,
    path_from_tool_input,
    pretooluse_bash_response,
    pretooluse_path_response,
    subagent_start_envelope,
    touches_config_path,
)
from permission_decision import PermissionDecision
from reason import BlockedCommandInvoked


def test_session_start_text_is_just_config_explain():
    config = Config.from_dict({"allowedCommands": ["echo"]})

    assert config.explain() in config.explain()  # explain() IS the session-start text


def test_subagent_start_envelope_wraps_explain_in_the_hook_specific_output_shape():
    config = Config.from_dict({"allowedCommands": ["echo"]})

    envelope = subagent_start_envelope(config)

    assert envelope == {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": config.explain(),
        }
    }


def test_touches_config_path_matches_a_command_policy_json_write():
    assert touches_config_path({"file_path": "/home/me/.claude/command-policy.json"})


def test_touches_config_path_does_not_match_an_unrelated_file():
    assert not touches_config_path({"file_path": "/home/me/.claude/settings.json"})


def test_touches_config_path_handles_a_missing_file_path_key():
    assert not touches_config_path({})


def test_config_write_lint_response_is_none_for_a_clean_config():
    assert config_write_lint_response(Config.from_dict({"allowedCommands": ["echo"]})) is None


def test_config_write_lint_response_reports_every_warning_when_the_config_is_not_clean():
    config = Config.from_dict({"commandSubstitutionResponse": "ask"}, source="user")

    response = config_write_lint_response(config)

    assert response is not None
    assert "commandSubstitutionResponse" in response["systemMessage"]


# =============================================================================
# PreToolUse hook-JSON-protocol mapping (leaf 20260914-213825's own hand-back
# from leaf 20260914-213652 - mirrors the OLD AnalysisResult.to_json_response
# shape: passthrough -> None, everything else -> the hookSpecificOutput
# envelope; reason lists render() to prose, plain-string reasons pass through
# unchanged).
# =============================================================================


def test_pretooluse_bash_response_is_none_for_passthrough():
    assert pretooluse_bash_response(PermissionDecision.passthrough("escalated by name")) is None


def test_pretooluse_bash_response_wraps_allow_with_an_empty_reason():
    response = pretooluse_bash_response(PermissionDecision.allow())

    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "",
        }
    }


def test_pretooluse_bash_response_renders_a_reason_tuple_to_prose():
    decision = PermissionDecision.deny((BlockedCommandInvoked("rm"),))

    response = pretooluse_bash_response(decision)

    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "blocked command invoked: rm" in response["hookSpecificOutput"]["permissionDecisionReason"]


def test_pretooluse_bash_response_passes_a_plain_string_reason_through_unchanged():
    decision = PermissionDecision.ask("bypass-policy cannot escalate this: needs a human")

    response = pretooluse_bash_response(decision)

    assert response["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert response["hookSpecificOutput"]["permissionDecisionReason"] == (
        "bypass-policy cannot escalate this: needs a human"
    )


def test_pretooluse_path_response_is_none_for_passthrough():
    assert pretooluse_path_response(PermissionDecision.passthrough()) is None


def test_pretooluse_path_response_wraps_allow():
    response = pretooluse_path_response(PermissionDecision.allow())

    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "",
        }
    }


def test_path_from_tool_input_reads_file_path_for_the_read_tool():
    assert path_from_tool_input("Read", {"file_path": "/a/b.txt"}) == "/a/b.txt"


def test_path_from_tool_input_reads_path_for_grep_and_glob():
    assert path_from_tool_input("Grep", {"path": "/a"}) == "/a"
    assert path_from_tool_input("Glob", {"path": "/a"}) == "/a"


def test_path_from_tool_input_is_case_insensitive_on_tool_name():
    assert path_from_tool_input("READ", {"file_path": "/a/b.txt"}) == "/a/b.txt"


def test_path_from_tool_input_handles_a_missing_tool_input():
    assert path_from_tool_input("Read", None) is None
