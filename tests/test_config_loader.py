"""Unit tests for the command-policy config file loader.

Pure I/O only: read the user and project files, JSON-parse them, and compose
via Config.merged_with - no merge semantics of its own (see config.py). Every
case takes its file locations as explicit tmp_path arguments so no test needs
to touch the real ~/.claude or CLAUDE_PROJECT_DIR locations.
"""

import json

from config_loader import load_config, load_config_from_environment


def test_loader_returns_defaults_when_neither_file_exists(tmp_path):
    config = load_config(tmp_path / "user.json", tmp_path / "project.json")

    assert config.allowed_commands == ()
    assert config.warnings() == ()


def test_loader_reads_the_user_config_file(tmp_path):
    user_path = tmp_path / "user.json"
    user_path.write_text(json.dumps({"allowedCommands": ["echo"]}))

    config = load_config(user_path, tmp_path / "project.json")

    assert [c.program for c in config.allowed_commands] == ["echo"]


def test_loader_merges_the_project_file_over_the_user_file(tmp_path):
    user_path = tmp_path / "user.json"
    project_path = tmp_path / "project.json"
    user_path.write_text(json.dumps({"allowedCommands": ["echo"]}))
    project_path.write_text(json.dumps({"allowedCommands": ["cat"]}))

    config = load_config(user_path, project_path)

    assert [c.program for c in config.allowed_commands] == ["echo", "cat"]


def test_an_absent_config_file_produces_no_warning(tmp_path):
    config = load_config(tmp_path / "user.json", tmp_path / "project.json")

    assert config.warnings() == ()


def test_a_present_but_unparseable_config_file_warns_by_name(tmp_path):
    user_path = tmp_path / "user.json"
    user_path.write_text("{not json")

    config = load_config(user_path, tmp_path / "project.json")

    [warning] = config.warnings()
    assert warning.kind == "unparseable_config_file"
    assert str(user_path) in warning.message


def test_an_unparseable_project_file_still_lets_a_valid_user_file_load(tmp_path):
    user_path = tmp_path / "user.json"
    project_path = tmp_path / "project.json"
    user_path.write_text(json.dumps({"allowedCommands": ["echo"]}))
    project_path.write_text("{not json")

    config = load_config(user_path, project_path)

    assert [c.program for c in config.allowed_commands] == ["echo"]
    [warning] = config.warnings()
    assert warning.layer == "project"


def test_loader_reports_no_config_found_when_neither_file_exists(tmp_path):
    """config_loader.py's `_load_layer` used to test `path.exists()` and
    discard the answer, returning `Config.defaults()` for an absent file -
    byte-identical to a present-but-empty one. This is the fix: the two
    states must read differently from `explain()` alone."""
    user_path = tmp_path / "user.json"
    project_path = tmp_path / "project.json"

    config = load_config(user_path, project_path)

    explanation = config.explain()
    assert explanation.startswith("No command-policy.json config file found at either scope")
    assert str(user_path) in explanation
    assert str(project_path) in explanation
    assert "migrate-config" in explanation


def test_loader_stays_silent_about_missing_config_when_the_user_file_exists_but_is_empty(tmp_path):
    user_path = tmp_path / "user.json"
    user_path.write_text(json.dumps({}))

    config = load_config(user_path, tmp_path / "project.json")

    assert "No command-policy.json config file found" not in config.explain()


def test_loader_stays_silent_about_missing_config_when_a_populated_config_exists(tmp_path):
    user_path = tmp_path / "user.json"
    user_path.write_text(json.dumps({"allowedCommands": ["echo"]}))

    config = load_config(user_path, tmp_path / "project.json")

    assert "No command-policy.json config file found" not in config.explain()


def test_the_no_config_found_line_renders_first_in_explain(tmp_path):
    config = load_config(tmp_path / "user.json", tmp_path / "project.json")

    assert config.explain().splitlines()[0].startswith("No command-policy.json config file found")


def test_load_config_from_environment_reads_home_and_project_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project_dir = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    (project_dir / ".claude").mkdir(parents=True)
    (home / ".claude" / "command-policy.json").write_text(json.dumps({"allowedCommands": ["echo"]}))
    (project_dir / ".claude" / "command-policy.json").write_text(json.dumps({"allowedCommands": ["cat"]}))

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))

    config = load_config_from_environment()

    assert [c.program for c in config.allowed_commands] == ["echo", "cat"]
