"""End-to-end tests for the leaf's consumer bin/ entrypoints, driven via
run_entrypoint (subprocess) per conftest.py's convention - each entrypoint is
a thin wrapper, so these prove the wiring rather than re-testing the logic
already covered by test_hook_envelopes.py / test_config.py / test_config_migration.py.
"""

import json


def _config_environment(tmp_path, user_config=None, project_config=None):
    home = tmp_path / "home"
    project_dir = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    (project_dir / ".claude").mkdir(parents=True)
    if user_config is not None:
        (home / ".claude" / "command-policy.json").write_text(json.dumps(user_config))
    if project_config is not None:
        (project_dir / ".claude" / "command-policy.json").write_text(json.dumps(project_config))
    return {"HOME": str(home), "CLAUDE_PROJECT_DIR": str(project_dir)}, home, project_dir


def test_explain_policy_prints_the_auto_allowed_commands(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("explain-policy", env=env)

    assert result.returncode == 0
    assert "echo" in result.stdout


def test_session_start_renderer_prints_plain_text(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("command-policy-render-session-start", stdin="{}", env=env)

    assert result.returncode == 0
    assert "echo" in result.stdout
    with_json = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
    assert with_json is None  # plain text, not a JSON envelope


def test_subagent_start_renderer_prints_the_hook_specific_output_envelope(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("command-policy-render-subagent-start", stdin="{}", env=env)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    assert "echo" in payload["hookSpecificOutput"]["additionalContext"]


def test_lint_on_write_reports_findings_for_a_write_touching_the_config_path(tmp_path, run_entrypoint):
    env, home, _ = _config_environment(tmp_path, user_config={"commandSubstitutionResponse": "ask"})
    config_path = home / ".claude" / "command-policy.json"
    stdin = json.dumps({"tool_input": {"file_path": str(config_path)}})

    result = run_entrypoint("command-policy-lint-config-on-write", stdin=stdin, env=env)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "commandSubstitutionResponse" in payload["systemMessage"]


def test_lint_on_write_stays_silent_for_a_write_to_an_unrelated_file(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"commandSubstitutionResponse": "ask"})
    stdin = json.dumps({"tool_input": {"file_path": "/some/other/file.json"}})

    result = run_entrypoint("command-policy-lint-config-on-write", stdin=stdin, env=env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_a_broken_user_config_file_surfaces_a_loud_warning_alongside_the_auto_allowed_rendering(
    tmp_path, run_entrypoint
):
    home = tmp_path / "home"
    project_dir = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    (project_dir / ".claude").mkdir(parents=True)
    (home / ".claude" / "command-policy.json").write_text("{not json")
    (project_dir / ".claude" / "command-policy.json").write_text(json.dumps({"allowedCommands": ["echo"]}))
    env = {"HOME": str(home), "CLAUDE_PROJECT_DIR": str(project_dir)}

    session_start = run_entrypoint("command-policy-render-session-start", stdin="{}", env=env)
    assert "echo" in session_start.stdout
    assert "command-policy.json" in session_start.stdout
    assert "could not be parsed" in session_start.stdout

    subagent_start = run_entrypoint("command-policy-render-subagent-start", stdin="{}", env=env)
    context = json.loads(subagent_start.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "echo" in context
    assert "could not be parsed" in context


# =============================================================================
# bin/migrate-config
# =============================================================================


def test_migrate_config_dry_run_writes_nothing_and_reports_the_user_scopes_migrated_config(
    shfmt_permissions_config_fixture, run_entrypoint
):
    env, home, _ = shfmt_permissions_config_fixture(user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("migrate-config", env=env)

    assert result.returncode == 0
    assert not (home / ".claude" / "command-policy.json").exists()

    report = json.loads(result.stdout)
    assert report["user"]["sourceExists"] is True
    assert report["user"]["newConfig"]["allowedCommands"] == ["echo"]
    assert any(w["key"] == "defaultDecision" for w in report["user"]["warnings"])


def test_migrate_config_reports_a_scope_with_no_source_file_as_not_present(
    shfmt_permissions_config_fixture, run_entrypoint
):
    env, _, _ = shfmt_permissions_config_fixture(user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("migrate-config", env=env)

    report = json.loads(result.stdout)
    assert report["project"]["sourceExists"] is False


def test_migrate_config_write_creates_the_command_policy_json_file(
    shfmt_permissions_config_fixture, run_entrypoint
):
    env, home, _ = shfmt_permissions_config_fixture(user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("migrate-config", args=["--write"], env=env)

    assert result.returncode == 0
    target = home / ".claude" / "command-policy.json"
    assert target.exists()
    assert json.loads(target.read_text())["allowedCommands"] == ["echo"]


def test_migrate_config_without_write_never_touches_an_existing_target(
    shfmt_permissions_config_fixture, run_entrypoint
):
    env, home, _ = shfmt_permissions_config_fixture(user_config={"allowedCommands": ["echo"]})
    target = home / ".claude" / "command-policy.json"
    target.write_text(json.dumps({"allowedCommands": ["cat"]}))

    result = run_entrypoint("migrate-config", env=env)

    assert result.returncode == 0
    assert json.loads(target.read_text())["allowedCommands"] == ["cat"]

    report = json.loads(result.stdout)
    assert report["user"]["existingTarget"]["allowedCommands"] == ["cat"]
    assert report["user"]["diff"]


def test_migrate_config_reports_no_diff_when_the_existing_target_already_matches(
    shfmt_permissions_config_fixture, run_entrypoint
):
    env, home, _ = shfmt_permissions_config_fixture(user_config={"blockedCommands": ["rm"]})
    result = run_entrypoint("migrate-config", env=env)
    new_config = json.loads(result.stdout)["user"]["newConfig"]
    (home / ".claude" / "command-policy.json").write_text(json.dumps(new_config))

    result = run_entrypoint("migrate-config", env=env)

    report = json.loads(result.stdout)
    assert report["user"]["diff"] is None


# =============================================================================
# bin/command-policy-analyze-bash-command
# =============================================================================


def test_analyze_bash_command_prints_nothing_for_an_allowed_command(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})
    stdin = json.dumps({"tool_input": {"command": "echo hi"}})

    result = run_entrypoint("command-policy-analyze-bash-command", stdin=stdin, env=env)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_analyze_bash_command_denies_with_a_hint_for_a_non_allowed_command(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})
    stdin = json.dumps({"tool_input": {"command": "rm -rf /"}})

    result = run_entrypoint("command-policy-analyze-bash-command", stdin=stdin, env=env)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "rm" in payload["hookSpecificOutput"]["permissionDecisionReason"]


def test_analyze_bash_command_prints_nothing_for_a_bypassed_command_that_needed_escalation(
    tmp_path, run_entrypoint
):
    """A wrapped command that is not itself allow-listed (but not blocked or
    sensitive either) hands the decision to whatever governs the call
    outside this hook - see escalation_policy.py's PASSTHROUGH_REASON."""
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})
    stdin = json.dumps({"tool_input": {"command": "bypass-policy touch /tmp/somefile"}})

    result = run_entrypoint("command-policy-analyze-bash-command", stdin=stdin, env=env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_analyze_bash_command_prints_nothing_for_malformed_stdin(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("command-policy-analyze-bash-command", stdin="not json", env=env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_analyze_bash_command_prints_nothing_when_the_hook_input_carries_no_command(
    tmp_path, run_entrypoint
):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})
    stdin = json.dumps({"tool_input": {}})

    result = run_entrypoint("command-policy-analyze-bash-command", stdin=stdin, env=env)

    assert result.returncode == 0
    assert result.stdout == ""


# =============================================================================
# bin/command-policy-analyze-path
# =============================================================================


def test_analyze_path_allows_a_configured_read_path(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(
        tmp_path, user_config={"allowedPaths": [{"tools": "read", "path": "/shared/doc.txt"}]}
    )
    stdin = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/shared/doc.txt"}})

    result = run_entrypoint("command-policy-analyze-path", stdin=stdin, env=env)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_analyze_path_prints_nothing_for_a_path_outside_allowed_paths(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(
        tmp_path, user_config={"allowedPaths": [{"tools": "read", "path": "/shared/doc.txt"}]}
    )
    stdin = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}})

    result = run_entrypoint("command-policy-analyze-path", stdin=stdin, env=env)

    assert result.returncode == 0
    assert result.stdout == ""


def test_analyze_path_reads_the_path_key_for_grep(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(
        tmp_path, user_config={"allowedPaths": [{"tools": "grep", "path": "/shared"}]}
    )
    stdin = json.dumps({"tool_name": "Grep", "tool_input": {"path": "/shared"}})

    result = run_entrypoint("command-policy-analyze-path", stdin=stdin, env=env)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_analyze_path_prints_nothing_for_malformed_stdin(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(
        tmp_path, user_config={"allowedPaths": [{"tools": "read", "path": "/shared/doc.txt"}]}
    )

    result = run_entrypoint("command-policy-analyze-path", stdin="not json", env=env)

    assert result.returncode == 0
    assert result.stdout == ""


# =============================================================================
# bin/audit-session-policy
# =============================================================================


def _project_transcripts_dir(home, project_dir):
    import session_audit

    return home / ".claude" / "projects" / session_audit.encode_project_dir(str(project_dir))


def test_audit_session_policy_reports_a_non_allowed_command_under_deny(
    tmp_path, run_entrypoint, fake_session_transcript_environment
):
    env, home, project_dir = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})
    transcripts_dir = _project_transcripts_dir(home, project_dir)
    transcripts_dir.mkdir(parents=True)
    fake_session_transcript_environment.write_session(
        transcripts_dir,
        "sess-1",
        [
            fake_session_transcript_environment.title_record("my-session"),
            fake_session_transcript_environment.bash_record("rm -rf /tmp/x"),
        ],
    )

    result = run_entrypoint(
        "audit-session-policy", args=["my-session", "--project-dir", str(project_dir)], env=env
    )

    assert result.returncode == 0
    assert "rm -rf /tmp/x" in result.stdout


def test_audit_session_policy_omits_an_allowed_command(
    tmp_path, run_entrypoint, fake_session_transcript_environment
):
    env, home, project_dir = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})
    transcripts_dir = _project_transcripts_dir(home, project_dir)
    transcripts_dir.mkdir(parents=True)
    fake_session_transcript_environment.write_session(
        transcripts_dir,
        "sess-1",
        [
            fake_session_transcript_environment.title_record("my-session"),
            fake_session_transcript_environment.bash_record("echo hi"),
        ],
    )

    result = run_entrypoint(
        "audit-session-policy", args=["my-session", "--project-dir", str(project_dir)], env=env
    )

    assert result.returncode == 0
    assert "echo hi" not in result.stdout


def test_audit_session_policy_errors_without_a_session_name_or_id(tmp_path, run_entrypoint):
    env, _, _ = _config_environment(tmp_path, user_config={"allowedCommands": ["echo"]})

    result = run_entrypoint("audit-session-policy", env=env)

    assert result.returncode == 2


def test_migrate_config_write_only_writes_scopes_whose_source_exists(
    shfmt_permissions_config_fixture, run_entrypoint
):
    env, home, project_dir = shfmt_permissions_config_fixture(user_config={"allowedCommands": ["echo"]})

    run_entrypoint("migrate-config", args=["--write"], env=env)

    assert (home / ".claude" / "command-policy.json").exists()
    assert not (project_dir / ".claude" / "command-policy.json").exists()
