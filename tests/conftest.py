"""Shared fixtures and path setup for the command-policy plugin test suite.

Run with: cd tests && nix-shell --run pytest

Deliberately carries no importlib module-loader fixture: bin/ entrypoints
are thin wrappers over
lib/ modules and are only ever exercised end-to-end via run_entrypoint - see
improvement-20260915-010936's "Whether conftest.py should be able to load a
bin/ entrypoint as a module" design decision.
"""

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = PLUGIN_ROOT / "lib"
BIN_DIR = PLUGIN_ROOT / "bin"

# Make the importable lib/ modules available to tests by direct `import config`
# etc. - lib/ is a sys.path entry, not a package (no __init__ file).
sys.path.insert(0, str(LIB_DIR))


@pytest.fixture
def ast_of():
    """Parse a bash command string to its raw shfmt JSON AST dict.

    Statement-construction tests go straight from a command string to the raw
    AST a test wants to poke by hand (e.g. to build a synthetic/mocked
    unrecognized Cmd.Type), reusing this leaf's own probing methodology
    instead of reinventing it per test.
    """

    def _ast_of(command):
        result = subprocess.run(
            ["shfmt", "-tojson"], input=command, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    return _ast_of


@pytest.fixture
def run_entrypoint():
    """Drive a bin/ entrypoint end-to-end via subprocess.

    Returns a callable (name, args=(), stdin=None, env=None) -> CompletedProcess,
    exercising the real shebang + CLI contract. `env` overlays os.environ so PATH
    (needed by `/usr/bin/env python3`) is inherited while other variables can be
    overridden.
    """

    def _run(name, args=(), stdin=None, env=None):
        entry = BIN_DIR / name
        if not entry.exists():
            raise FileNotFoundError(f"no entrypoint named {name!r} in bin/")

        full_env = {**os.environ, **(env or {})}
        return subprocess.run(
            [str(entry), *map(str, args)],
            input=stdin,
            capture_output=True,
            text=True,
            env=full_env,
        )

    return _run


@pytest.fixture
def cwd_pinned_inside_project(tmp_path):
    """Pin process cwd and CLAUDE_PROJECT_DIR explicitly for one `with` block.

    Every path/redirect case in the specification suite MUST use this rather
    than inheriting pytest's ambient cwd - see Flag List F1: a green
    tilde-redirect test in the old suite was an artefact of pytest's cwd
    differing from CLAUDE_PROJECT_DIR, not evidence of safe behaviour.
    Defaults both to the same fresh temp directory; pass `project_dir`/`cwd`
    explicitly to pin them to different values instead.
    """

    @contextlib.contextmanager
    def _pin(project_dir=None, cwd=None):
        target_project_dir = str(project_dir if project_dir is not None else tmp_path)
        target_cwd = str(cwd if cwd is not None else target_project_dir)

        original_cwd = os.getcwd()
        original_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        try:
            os.chdir(target_cwd)
            os.environ["CLAUDE_PROJECT_DIR"] = target_project_dir
            yield Path(target_cwd)
        finally:
            os.chdir(original_cwd)
            if original_project_dir is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = original_project_dir

    return _pin


@pytest.fixture
def assert_migration_warns_about():
    """Structural counterpart to `assert_reason_includes` (test_permission_
    decisions.py) for migration warnings: asserts one of `result.warnings`
    carries the given `key` - a dropped knob name, or a structural-reshape
    marker like "propagate"/"allowedReadPaths" - rather than substring-
    matching rendered prose.
    """

    def _assert(result, knob_or_key):
        matches = [w for w in result.warnings if getattr(w, "key", None) == knob_or_key]
        assert matches, f"expected a migration warning with key {knob_or_key!r}; got: {result.warnings!r}"

    return _assert


@pytest.fixture
def shfmt_permissions_config_fixture(tmp_path):
    """Builds a temp `~/.claude/shfmt-permissions.json` (and optionally a
    project one) so `bin/migrate-config` entrypoint tests don't hand-roll
    file I/O per case. Mirrors test_consumer_entrypoints.py's own
    `_config_environment`, but for the OLD engine's config file name.
    """

    def _build(user_config=None, project_config=None):
        home = tmp_path / "home"
        project_dir = tmp_path / "project"
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        (project_dir / ".claude").mkdir(parents=True, exist_ok=True)
        if user_config is not None:
            (home / ".claude" / "shfmt-permissions.json").write_text(json.dumps(user_config))
        if project_config is not None:
            (project_dir / ".claude" / "shfmt-permissions.json").write_text(json.dumps(project_config))
        return {"HOME": str(home), "CLAUDE_PROJECT_DIR": str(project_dir)}, home, project_dir

    return _build


@pytest.fixture
def assert_config_is_reachable():
    """Fail loudly if a test's raw config dict round-trips through
    `Config.from_dict` into a warning - i.e. holds a value no real
    command-policy.json could produce cleanly.

    The `Config.from_dict`-shaped successor to test_permission_decisions.py's
    own `assert_config_is_reachable`: now that `Config.from_dict` itself
    validates and warns, a test fixture that silently relies on a corrected
    value is exactly the false confidence that guard existed to catch.
    """

    def _assert(cfg):
        from config import Config

        result = Config.from_dict(cfg)
        assert not result.warnings(), (
            f"config fixture {cfg!r} does not round-trip cleanly through "
            f"Config.from_dict - it produced: {result.warnings()!r}"
        )

    return _assert


@pytest.fixture
def fake_session_transcript_environment():
    """Builders for a fabricated Claude Code session transcript + permission-
    mode file, so `session_audit` tests don't touch a real session - mirrors
    `packages/shfmt-permissions/tests/test_shfmt_session_approvals.py`'s own
    module-level helpers, bundled as one fixture per this leaf's Test
    Architecture ('New helpers to create').
    """

    def _bash_record(command):
        return {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}]},
        }

    def _tool_record(tool_name, tool_input):
        return {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": tool_name, "input": tool_input}]},
        }

    def _title_record(name):
        return {"type": "custom-title", "customTitle": name}

    def _permission_mode_record(mode):
        return {"type": "permission-mode", "permissionMode": mode}

    def _write_transcript(path, records):
        path.write_text("".join(json.dumps(r) + "\n" for r in records))

    def _write_session(project_dir, session_id, records):
        transcript_path = project_dir / f"{session_id}.jsonl"
        _write_transcript(transcript_path, records)
        return transcript_path

    def _write_subagent(project_dir, session_id, agent_name, records):
        subagents_dir = project_dir / session_id / "subagents"
        subagents_dir.mkdir(parents=True, exist_ok=True)
        agent_path = subagents_dir / f"{agent_name}.jsonl"
        _write_transcript(agent_path, records)
        return agent_path

    return SimpleNamespace(
        bash_record=_bash_record,
        tool_record=_tool_record,
        title_record=_title_record,
        permission_mode_record=_permission_mode_record,
        write_session=_write_session,
        write_subagent=_write_subagent,
    )
