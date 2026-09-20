"""End-to-end tests for the two escalation-path bin/ entrypoints' RUNTIME
halves - what actually happens once a human approves the `ask`/`passthrough`
Config.decision_for (lib/escalation_policy.py) already produced for them.
Driven via run_entrypoint (subprocess) per conftest.py's convention.
"""

import json


def test_bypass_policy_execs_the_wrapped_command(run_entrypoint, tmp_path):
    marker = tmp_path / "ran"

    result = run_entrypoint("bypass-policy", args=["touch", str(marker)])

    assert result.returncode == 0, result.stderr
    assert marker.exists()


def test_bypass_policy_with_no_argv_does_nothing(run_entrypoint):
    result = run_entrypoint("bypass-policy")

    assert result.returncode == 0
    assert result.stdout == ""


def test_bypass_policy_reports_a_program_that_does_not_exist(run_entrypoint):
    result = run_entrypoint("bypass-policy", args=["this-program-does-not-exist-anywhere"])

    assert result.returncode != 0
    assert "this-program-does-not-exist-anywhere" in result.stderr


def test_add_allow_policy_writes_the_proposed_entry_to_the_user_config(run_entrypoint, tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    env = {"HOME": str(home)}

    result = run_entrypoint(
        "add-allow-policy", args=["rg", "--scope", "user", "--intent", "search without prompts"], env=env
    )

    assert result.returncode == 0, result.stderr
    written = json.loads((home / ".claude" / "command-policy.json").read_text())
    assert written["allowedCommands"] == ["rg"]


def test_add_allow_policy_writes_a_json_entry_object(run_entrypoint, tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    env = {"HOME": str(home)}
    entry = json.dumps({"program": "git", "onlyTheseVariables": ["HOME"]})

    result = run_entrypoint("add-allow-policy", args=[entry, "--scope", "user", "--intent", "why"], env=env)

    assert result.returncode == 0, result.stderr
    written = json.loads((home / ".claude" / "command-policy.json").read_text())
    assert written["allowedCommands"] == [{"program": "git", "onlyTheseVariables": ["HOME"]}]


def test_add_allow_policy_writes_to_the_project_config_for_project_scope(run_entrypoint, tmp_path):
    project_dir = tmp_path / "project"
    (project_dir / ".claude").mkdir(parents=True)
    env = {"CLAUDE_PROJECT_DIR": str(project_dir)}

    result = run_entrypoint(
        "add-allow-policy", args=["rg", "--scope", "project", "--intent", "why"], env=env
    )

    assert result.returncode == 0, result.stderr
    written = json.loads((project_dir / ".claude" / "command-policy.json").read_text())
    assert written["allowedCommands"] == ["rg"]


def test_add_allow_policy_refuses_to_write_without_an_intent(run_entrypoint, tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    env = {"HOME": str(home)}

    result = run_entrypoint("add-allow-policy", args=["rg", "--scope", "user"], env=env)

    assert result.returncode != 0
    assert not (home / ".claude" / "command-policy.json").exists()
