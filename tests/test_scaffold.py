"""Smoke tests proving the command-policy scaffold is real.

No `bin/` entrypoint in this plugin is a stub any more: `bypass-policy` and
`add-allow-policy` graduated in leaf 20260915-010959, and
`audit-session-policy`/`command-policy-analyze-bash-command`/
`command-policy-analyze-path` graduated in this leaf (20260914-213825) - see
test_consumer_entrypoints.py for each one's own behavioural coverage. This
file keeps only the generic bootstrap/lib-reachability smoke tests.
"""

import os
from pathlib import Path

import config

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIND_AUTO_ALLOWED_COMMAND_AGENT_PATH = PLUGIN_ROOT / "agents" / "find-auto-allowed-command.md"
FIND_AUTO_ALLOWED_COMMAND_SKILL_DIR = PLUGIN_ROOT / "skills" / "find-auto-allowed-command"


def test_a_real_lib_module_imports_directly():
    assert config.Config is not None


def test_find_auto_allowed_command_agent_exists():
    """improvement-20260919-081655: the equivalence search converts from a
    same-conversation SKILL to a zero-context AGENT - this is the structural
    half of that conversion pytest can actually assert (the agent's
    reasoning quality cannot be)."""
    assert FIND_AUTO_ALLOWED_COMMAND_AGENT_PATH.is_file()


def test_find_auto_allowed_command_skill_no_longer_exists():
    """The skill was `user-invocable: false` with the deny-reason pointer as
    its only caller - once that pointer routes to the agent, the skill is
    unreachable code and must be deleted outright, not left as a stale
    duplicate the agent's instructions can drift from."""
    assert not FIND_AUTO_ALLOWED_COMMAND_SKILL_DIR.exists()


def test_find_auto_allowed_command_agent_body_carries_the_decomposition_step():
    """improvement-20260919-230721: a near-miss denial caused by an
    unreadable argument ($(...) or a variable) is often DECOMPOSABLE into two
    auto-allowed commands. The agent's reasoning procedure must consider this
    before it is allowed to conclude no auto-approved route exists - this
    structural check is the pytest-testable half; the reasoning quality
    itself is not (same limitation the agent-exists test above records)."""
    body = FIND_AUTO_ALLOWED_COMMAND_AGENT_PATH.read_text()

    assert "decompos" in body.lower()
    assert "ordered pair" in body.lower() or "ordered PAIR" in body


def test_bin_entrypoint_reaches_lib_via_bootstrap(run_entrypoint):
    result = run_entrypoint("command-policy-analyze-bash-command", stdin="{}")

    assert result.returncode == 0, result.stderr


def test_cwd_pinned_inside_project_pins_cwd_and_claude_project_dir_together(cwd_pinned_inside_project):
    original_cwd = os.getcwd()
    original_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")

    with cwd_pinned_inside_project() as pinned_dir:
        assert os.getcwd() == str(pinned_dir)
        assert os.environ["CLAUDE_PROJECT_DIR"] == str(pinned_dir)

    assert os.getcwd() == original_cwd
    assert os.environ.get("CLAUDE_PROJECT_DIR") == original_project_dir
