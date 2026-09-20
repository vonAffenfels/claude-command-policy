"""Unit tests for session_audit: the decision-engine-agnostic half of the
old shfmt-permissions `shfmt-session-approvals` (session/transcript
resolution, permission-mode reading, rendering), ported largely unchanged,
with `classify()` rebuilt on the new `Config.decision_for` and the
new outcome vocabulary's bucket names re-derived (see this leaf's
Implementation Notes).
"""

import json

from config import Config
import session_audit


def set_mtime(path, mtime):
    import os

    os.utime(path, (mtime, mtime))


# =============================================================================
# encode_project_dir
# =============================================================================


def test_encode_project_dir_turns_slashes_into_dashes():
    assert session_audit.encode_project_dir("/home/user/proj") == "-home-user-proj"


def test_encode_project_dir_encodes_a_dot_segment_as_double_dash_first():
    assert session_audit.encode_project_dir("/home/user/.claude") == "-home-user--claude"


# =============================================================================
# extract_bash_commands
# =============================================================================


def test_extract_bash_commands_collects_in_order(tmp_path, fake_session_transcript_environment):
    env = fake_session_transcript_environment
    transcript = env.write_session(
        tmp_path, "sess-1", [env.bash_record("git status"), env.bash_record("npm run build")]
    )

    assert session_audit.extract_bash_commands(transcript) == ["git status", "npm run build"]


def test_extract_bash_commands_ignores_non_bash_tool_uses(tmp_path, fake_session_transcript_environment):
    env = fake_session_transcript_environment
    transcript = env.write_session(
        tmp_path, "sess-1", [env.tool_record("Read", {"file_path": "/etc/hosts"}), env.bash_record("ls -la")]
    )

    assert session_audit.extract_bash_commands(transcript) == ["ls -la"]


def test_extract_bash_commands_includes_subagent_commands_by_default(
    tmp_path, fake_session_transcript_environment
):
    env = fake_session_transcript_environment
    transcript = env.write_session(tmp_path, "sess-1", [env.bash_record("git status")])
    env.write_subagent(tmp_path, "sess-1", "agent-abc", [env.bash_record("rg pattern")])

    assert session_audit.extract_bash_commands(transcript) == ["git status", "rg pattern"]


def test_extract_bash_commands_no_subagents_flag_scopes_to_main_transcript(
    tmp_path, fake_session_transcript_environment
):
    env = fake_session_transcript_environment
    transcript = env.write_session(tmp_path, "sess-1", [env.bash_record("git status")])
    env.write_subagent(tmp_path, "sess-1", "agent-abc", [env.bash_record("rg pattern")])

    assert session_audit.extract_bash_commands(transcript, include_subagents=False) == ["git status"]


def test_extract_bash_commands_ignores_meta_json_sidecar_files(
    tmp_path, fake_session_transcript_environment
):
    env = fake_session_transcript_environment
    transcript = env.write_session(tmp_path, "sess-1", [env.bash_record("git status")])
    subagents_dir = tmp_path / "sess-1" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-abc.meta.json").write_text('{"not":"a transcript"}')
    (subagents_dir / "agent-abc.jsonl").write_text(json.dumps(env.bash_record("rg pattern")) + "\n")

    assert session_audit.extract_bash_commands(transcript) == ["git status", "rg pattern"]


# =============================================================================
# resolve_session
# =============================================================================


def test_resolve_session_returns_none_when_no_transcript_matches_name(
    tmp_path, fake_session_transcript_environment
):
    env = fake_session_transcript_environment
    env.write_session(tmp_path, "sess-1", [env.title_record("other-name")])

    assert session_audit.resolve_session("wanted", tmp_path) is None


def test_resolve_session_single_match_reports_session_id_and_no_others(
    tmp_path, fake_session_transcript_environment
):
    env = fake_session_transcript_environment
    env.write_session(tmp_path, "sess-1", [env.title_record("wanted")])

    match = session_audit.resolve_session("wanted", tmp_path)

    assert match.session_id == "sess-1"
    assert match.transcript_path == tmp_path / "sess-1.jsonl"
    assert match.other_count == 0


def test_resolve_session_multiple_matches_pick_most_recent_and_count_others(
    tmp_path, fake_session_transcript_environment
):
    env = fake_session_transcript_environment
    older = env.write_session(tmp_path, "sess-old", [env.title_record("wanted")])
    newer = env.write_session(tmp_path, "sess-new", [env.title_record("wanted")])
    set_mtime(older, 1000)
    set_mtime(newer, 2000)

    match = session_audit.resolve_session("wanted", tmp_path)

    assert match.session_id == "sess-new"
    assert match.other_count == 1


# =============================================================================
# read_permission_modes
# =============================================================================


def test_read_permission_modes_empty_when_no_records(tmp_path, fake_session_transcript_environment):
    env = fake_session_transcript_environment
    transcript = env.write_session(tmp_path, "sess-1", [env.bash_record("ls")])

    assert session_audit.read_permission_modes(transcript) == []


def test_read_permission_modes_collects_distinct_modes_in_first_seen_order(
    tmp_path, fake_session_transcript_environment
):
    env = fake_session_transcript_environment
    transcript = env.write_session(
        tmp_path,
        "sess-1",
        [
            env.permission_mode_record("default"),
            env.permission_mode_record("acceptEdits"),
            env.permission_mode_record("default"),
        ],
    )

    assert session_audit.read_permission_modes(transcript) == ["default", "acceptEdits"]


# =============================================================================
# is_bypass_wrapped
# =============================================================================


def test_is_bypass_wrapped_recognizes_the_sole_invoked_wrapper():
    assert session_audit.is_bypass_wrapped("bypass-policy rm -rf /") is True


def test_is_bypass_wrapped_rejects_a_command_merely_sharing_the_line():
    assert session_audit.is_bypass_wrapped("bypass-policy true && rm -rf /") is False


def test_is_bypass_wrapped_rejects_an_ordinary_command():
    assert session_audit.is_bypass_wrapped("ls -la") is False


# =============================================================================
# classify
# =============================================================================


def _config():
    return Config.from_dict(
        {"allowedCommands": ["ls"], "blockedCommands": ["rm"], "commandSubstitutionResponse": "deny"}
    )


def test_classify_buckets_commands_by_recomputed_decision():
    """Under the deny+hint model almost every non-allowed command decides
    'deny' (with a hint) - 'ask'/'passthrough' are reserved for the
    escalation paths (see the module docstring and this leaf's
    Implementation Notes on re-deriving the outcome vocabulary)."""
    commands = ["ls -la", "rm -rf x", "echo $(cat file.txt)", "foobar"]

    buckets = session_audit.classify(commands, _config())

    assert buckets["allow"] == [(1, "ls -la")]
    denied_commands = {command for _, command in buckets["deny"]}
    assert denied_commands == {"rm -rf x", "echo $(cat file.txt)", "foobar"}


def test_classify_dedupes_counts_and_sorts_by_count_desc():
    commands = ["ls -la", "ls -la", "ls -la", "ls foo", "ls foo", "ls bar"]

    buckets = session_audit.classify(commands, _config())

    assert buckets["allow"] == [(3, "ls -la"), (2, "ls foo"), (1, "ls bar")]


def test_classify_buckets_a_bypass_wrapped_command_separately():
    commands = ["foobar", "bypass-policy rm -rf /"]

    buckets = session_audit.classify(commands, _config())

    assert (1, "bypass-policy rm -rf /") in buckets[session_audit.BYPASS_BUCKET]
    assert not any(command == "bypass-policy rm -rf /" for _, command in buckets["deny"])


def test_classify_buckets_an_add_allow_policy_proposal_as_ask():
    commands = ['add-allow-policy --scope user --intent "why" "ls foo"']

    buckets = session_audit.classify(commands, _config())

    assert buckets["ask"] == [(1, 'add-allow-policy --scope user --intent "why" "ls foo"')]


# =============================================================================
# render
# =============================================================================


def render_report(buckets, **overrides):
    header = dict(
        session_name="my-session",
        session_id="sess-1",
        transcript_path="/x/sess-1.jsonl",
        last_modified="2026-09-08 09:00:00",
        permission_modes=["default"],
        shfmt_present=True,
        other_count=0,
    )
    header.update(overrides)
    return session_audit.render(buckets, **header)


def empty_buckets(**filled):
    buckets = {decision: [] for decision in session_audit.DECISIONS}
    buckets[session_audit.BYPASS_BUCKET] = []
    buckets.update(filled)
    return buckets


def test_render_shows_the_deny_section_with_its_count_and_omits_allow():
    buckets = empty_buckets(deny=[(2, "rm -rf x")], allow=[(9, "ls -la")])

    report = render_report(buckets)

    assert "2x  rm -rf x" in report
    assert "ls -la" not in report


def test_render_shows_ask_and_passthrough_sections():
    buckets = empty_buckets(ask=[(1, "add-allow-policy ...")], passthrough=[(1, "foobar")])

    report = render_report(buckets)

    assert "## Will prompt (ask)" in report
    assert "1x  add-allow-policy ..." in report
    assert "1x  foobar" in report


def test_render_header_warns_when_accept_edits_was_active():
    report = render_report(empty_buckets(), permission_modes=["default", "acceptEdits"])

    assert "acceptEdits" in report
    assert "suppressed" in report


def test_render_loud_warning_when_shfmt_absent():
    report = render_report(empty_buckets(), shfmt_present=False)

    assert "shfmt is NOT installed" in report
    assert "INVALID" in report


def test_render_notes_older_sessions_sharing_name():
    report = render_report(empty_buckets(), other_count=3)

    assert "3 older" in report
    assert "--session-id" in report


def test_render_bypass_section_reports_intervention_count():
    report = render_report(empty_buckets(**{session_audit.BYPASS_BUCKET: [(2, "bypass-policy rm -rf /")]}))

    assert "## Bypassed" in report
    assert "intervention" in report
    assert "2x  bypass-policy rm -rf /" in report


def test_render_footer_points_to_add_allow_policy():
    report = render_report(empty_buckets())

    assert "add-allow-policy" in report
