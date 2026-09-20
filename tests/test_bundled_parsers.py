"""Unit coverage for bundled parser scripts (`parsers/`).

Convention inherited from the shfmt-permissions plugin's own parser tests
(`run_parser`: subprocess with JSON on stdin, JSON back on stdout) - NOT an
import across plugins, since the engine itself only ever reaches a bundled
parser as a subprocess (see `ExternalParserFactory`).

Scope: the four wrapper parsers ported by improvement-20260918-223632
(`timeout`, `nix`, `nix-shell`, `xargs`) plus `spawn-claude`
(improvement-20260920-142519) - the other bundled parsers remain uncovered on
the command-policy side (see that improvement file's Observed section).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PARSERS_DIR = Path(__file__).resolve().parent.parent / "parsers"


def run_parser(parser_name: str, arguments: list[str]) -> dict:
    """Run a bundled parser script exactly as the engine does and return its
    parsed JSON output."""
    parser_path = PARSERS_DIR / f"{parser_name}.py"
    input_data = json.dumps({"arguments": arguments})

    result = subprocess.run(
        [sys.executable, str(parser_path)],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Parser failed: {result.stderr}")

    return json.loads(result.stdout)


# =============================================================================
# Test: timeout.py's nestedCommands output
# =============================================================================


class TestTimeoutParserNestedCommands:
    def test_wrapped_command_is_published_as_argv_shaped_nested_command(self):
        result = run_parser("timeout", ["10", "echo", "hi"])

        assert result["nestedCommands"] == [{"text": "echo hi", "shape": "argv"}]

    def test_named_command_channel_is_kept_unchanged_alongside_the_new_channel(self):
        result = run_parser("timeout", ["10", "echo", "hi"])

        assert result["named"]["command"] == "echo hi"

    def test_duration_positional_is_excluded_from_the_nested_command(self):
        result = run_parser("timeout", ["-s", "KILL", "10", "rm", "-rf", "/tmp/x"])

        assert result["nestedCommands"] == [{"text": "rm -rf /tmp/x", "shape": "argv"}]

    def test_no_inner_command_publishes_no_nested_commands_key(self):
        result = run_parser("timeout", ["10"])

        assert "nestedCommands" not in result

    def test_spaced_argument_survives_as_one_word(self):
        """Re-quoting preserves word boundaries so propagation re-parses the
        nested text into the original argv, not a re-split shell string."""
        result = run_parser("timeout", ["10", "bash", "-c", "rm -rf /"])

        assert result["nestedCommands"] == [{"text": "bash -c 'rm -rf /'", "shape": "argv"}]


# =============================================================================
# Test: nix.py's nestedCommands output
# =============================================================================


class TestNixParserNestedCommands:
    def test_dash_c_command_is_published_as_argv_shaped_nested_command(self):
        result = run_parser("nix", ["develop", ".#backend", "-c", "npm", "install"])

        assert result["nestedCommands"] == [{"text": "npm install", "shape": "argv"}]

    def test_named_command_channel_is_kept_unchanged_alongside_the_new_channel(self):
        result = run_parser("nix", ["develop", "-c", "echo", "hi"])

        assert result["named"]["command"] == "echo hi"

    def test_long_command_option_is_also_published(self):
        result = run_parser("nix", ["develop", "--command", "npm", "run", "build"])

        assert result["nestedCommands"] == [{"text": "npm run build", "shape": "argv"}]

    def test_dash_c_less_invocation_publishes_no_nested_commands_key(self):
        """`nix run` names a flake installable, not a resolvable command word -
        honestly publishing nothing rather than guessing."""
        result = run_parser("nix", ["run", "nixpkgs#hello"])

        assert "nestedCommands" not in result

    def test_develop_with_no_command_publishes_no_nested_commands_key(self):
        result = run_parser("nix", ["develop"])

        assert "nestedCommands" not in result


# =============================================================================
# Test: nix-shell.py's nestedCommands output
# =============================================================================


class TestNixShellParserNestedCommands:
    def test_run_option_is_published_as_shell_shaped_nested_command(self):
        """--run's argument is ONE shell string, not already-split argv - the
        opposite shape from timeout/nix, and the reason each parser's
        extraction semantics are specified separately rather than shared."""
        result = run_parser("nix-shell", ["--run", "cd x && make"])

        assert result["nestedCommands"] == [{"text": "cd x && make", "shape": "shell"}]

    def test_command_option_is_also_published_as_shell_shaped(self):
        result = run_parser("nix-shell", ["--command", "echo hi"])

        assert result["nestedCommands"] == [{"text": "echo hi", "shape": "shell"}]

    def test_named_command_channel_is_kept_unchanged_alongside_the_new_channel(self):
        result = run_parser("nix-shell", ["--run", "echo hi"])

        assert result["named"]["command"] == "echo hi"

    def test_last_of_two_run_options_wins(self):
        """nix-shell only honours the LAST --run/--command; publishing an
        earlier, ignored one would evaluate a command that never runs."""
        result = run_parser("nix-shell", ["--run", "echo first", "--run", "echo second"])

        assert result["nestedCommands"] == [{"text": "echo second", "shape": "shell"}]

    def test_bare_invocation_publishes_no_nested_commands_key(self):
        """No `--run`/`--command` at all means no command is ever going to
        run - the honest-nothing case, unlike bare xargs's known `echo`."""
        result = run_parser("nix-shell", [])

        assert "nestedCommands" not in result

    def test_shell_nix_with_no_run_publishes_no_nested_commands_key(self):
        result = run_parser("nix-shell", ["shell.nix"])

        assert "nestedCommands" not in result


# =============================================================================
# Test: xargs.py's nestedCommands output (NEW parser — never ported)
# =============================================================================


class TestXargsParserNestedCommands:
    def test_command_and_initial_args_are_published_as_argv_shaped_nested_command(self):
        result = run_parser("xargs", ["rm", "./build"])

        assert result["nestedCommands"] == [{"text": "rm ./build", "shape": "argv"}]

    def test_named_command_channel_is_also_published(self):
        result = run_parser("xargs", ["rm", "./build"])

        assert result["named"]["command"] == "rm ./build"

    def test_bare_xargs_publishes_the_documented_echo_default(self):
        """No command argument at all - xargs' own documented default,
        publishable because it is statically known, unlike nix-shell's
        genuine 'nothing is going to run'."""
        result = run_parser("xargs", [])

        assert result["nestedCommands"] == [{"text": "echo", "shape": "argv"}]

    def test_own_value_consuming_option_is_walked_before_the_command(self):
        """-n consumes a value (max-args), so it must not be mistaken for a
        flag that would shift COMMAND one word to the right."""
        result = run_parser("xargs", ["-n", "1", "rm", "./build"])

        assert result["nestedCommands"] == [{"text": "rm ./build", "shape": "argv"}]

    def test_unknown_dash_prefixed_token_is_a_valueless_flag_not_the_command(self):
        """--dry-run is not one of xargs' value-consuming options, so it is
        treated as a bare flag - the same convention every sibling parser
        uses - and must not be mistaken for COMMAND."""
        result = run_parser("xargs", ["--dry-run", "rm", "./build"])

        assert {"name": "--dry-run", "arguments": []} in result["options"]
        assert result["nestedCommands"] == [{"text": "rm ./build", "shape": "argv"}]

    def test_double_dash_terminates_option_parsing_so_the_next_token_is_command(self):
        """`--` ends option parsing so a COMMAND that looks like an option
        (or an INITIAL-ARG that does) is never misread as one."""
        result = run_parser("xargs", ["--", "--not-an-option", "arg"])

        assert result["options"] == []
        assert result["nestedCommands"] == [{"text": "--not-an-option arg", "shape": "argv"}]

    def test_paths_are_always_empty(self):
        """Inner-command paths are validated via propagation, not by this
        wrapper's own parser - xargs never publishes paths."""
        result = run_parser("xargs", ["rm", "./build"])

        assert result["paths"] == []


# =============================================================================
# Test: spawn-claude.py's span split and forwarded-args path candidacy
#
# improvement-20260920-142519. Three spans, three treatments: the session
# name (argument 0) and the prompt (everything after the FIRST literal `--`)
# are positively known not to be paths and published on `named` only; the
# forwarded-args span (everything between them) gets total path candidacy,
# mirroring `default_parser.py` - no flag-name enumeration anywhere.
# =============================================================================


class TestSpawnClaudeParserSeparatorHandling:
    def test_no_separator_forwards_everything_and_publishes_no_prompt(self):
        result = run_parser("spawn-claude", ["name", "--settings", "value"])

        assert result["named"].get("prompt") is None
        assert [o["name"] for o in result["options"]] == ["--settings"]
        assert [p["value"] for p in result["positionals"]] == ["value"]

    def test_one_separator_splits_forwarded_args_from_the_prompt(self):
        result = run_parser(
            "spawn-claude",
            ["name", "--permission-mode", "acceptEdits", "--", "do", "the", "thing"],
        )

        assert [o["name"] for o in result["options"]] == ["--permission-mode"]
        assert [p["value"] for p in result["positionals"]] == ["acceptEdits"]
        assert result["named"]["prompt"] == "do the thing"

    def test_a_second_separator_is_ordinary_prompt_text(self):
        result = run_parser("spawn-claude", ["name", "--", "a", "--", "b"])

        assert result["named"]["prompt"] == "a -- b"
        assert result["options"] == []
        assert result["positionals"] == []

    def test_a_dash_prefixed_word_after_the_separator_is_prompt_text_not_a_forwarded_flag(self):
        result = run_parser("spawn-claude", ["name", "--", "--", "literal", "dashes"])

        assert result["named"]["prompt"] == "-- literal dashes"
        assert result["options"] == []

    def test_an_empty_argument_list_returns_an_empty_shape_rather_than_raising(self):
        result = run_parser("spawn-claude", [])

        assert result["options"] == []
        assert result["positionals"] == []
        assert result["paths"] == []
        assert result["named"] == {}


class TestSpawnClaudeParserForwardedArgsPathCandidacy:
    def test_a_space_separated_flag_value_contributes_the_value_as_the_candidate(self):
        result = run_parser("spawn-claude", ["name", "--settings", "/etc/passwd"])

        assert result["paths"] == ["/etc/passwd"]

    def test_a_joined_flag_value_contributes_the_value_not_the_whole_word(self):
        """The burying failure this trunk keeps re-finding: `--settings=/etc/
        passwd` must resolve to `/etc/passwd`, never `<project>/--settings=
        /etc/passwd`."""
        result = run_parser("spawn-claude", ["name", "--settings=/etc/passwd"])

        assert result["paths"] == ["/etc/passwd"]

    def test_the_session_name_never_contributes_a_path_candidate(self):
        result = run_parser("spawn-claude", ["/etc/passwd"])

        assert result["paths"] == []

    def test_the_prompt_never_contributes_a_path_candidate(self):
        result = run_parser("spawn-claude", ["name", "--", "/etc/passwd"])

        assert result["paths"] == []

    def test_a_bare_flag_with_no_value_contributes_no_path_candidate_of_its_own(self):
        result = run_parser("spawn-claude", ["name", "--focus", "--permission-mode", "acceptEdits"])

        assert len(result["paths"]) == 1
        assert result["paths"][0].endswith("/acceptEdits")

    def test_sessionname_and_prompt_are_published_on_named_only(self):
        result = run_parser("spawn-claude", ["myname", "--", "hello", "world"])

        assert result["named"]["sessionName"] == "myname"
        assert result["named"]["prompt"] == "hello world"
        assert "myname" not in [o["name"] for o in result["options"]]
        assert "myname" not in [p["value"] for p in result["positionals"]]
