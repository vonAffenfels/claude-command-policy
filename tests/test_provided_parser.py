"""Unit tests for ProvidedParser: resolves a bundled reference parser script
by name from parsers/ and delegates interpretation
to an internal CommandParser - it never calls subprocess itself either.

Script existence is checked through the injected PathResolutionContext, not
the real filesystem - see test_path_resolution.py for that contract.
"""

from pathlib import Path

from path_resolution import PathResolutionContext
from provided_parser import ProvidedParser

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_GIT_PARSER = PLUGIN_ROOT / "parsers" / "git.py"


def context_where_only(*existing_suffixes):
    return PathResolutionContext(
        cwd="/irrelevant",
        exists_predicate=lambda path: any(path.endswith(suffix) for suffix in existing_suffixes),
    )


def test_from_definition_resolves_the_command_to_the_bundled_script_path_when_it_exists():
    parser = ProvidedParser.from_definition({"name": "git"}, context_where_only("git.py"))

    assert parser.command == str(BUNDLED_GIT_PARSER)


def test_from_definition_resolves_to_an_empty_command_when_the_script_does_not_exist():
    parser = ProvidedParser.from_definition({"name": "git"}, context_where_only("npm.py"))

    assert parser.command == ""


def test_from_definition_defaults_timeout_ms_to_one_second():
    parser = ProvidedParser.from_definition({"name": "git"}, context_where_only("git.py"))

    assert parser.timeout_ms == 1000


def test_from_definition_carries_a_configured_timeout_ms():
    parser = ProvidedParser.from_definition({"name": "git", "timeout_ms": 2000}, context_where_only("git.py"))

    assert parser.timeout_ms == 2000


def test_interpret_delegates_to_an_internal_command_parser():
    parser = ProvidedParser.from_definition({"name": "git"}, context_where_only("git.py"))

    result = parser.interpret({"named": {"subcommand": "commit"}})

    assert result.named == {"subcommand": "commit"}


def test_the_real_bundled_script_resolves_against_the_real_filesystem():
    """One integration-style check that the injected context's default
    real-filesystem constructor (`for_process`) actually finds the real
    bundled git.py - the fixed, plugin-root-relative layout the scripts live
    in, not a user-supplied argument path.
    """
    parser = ProvidedParser.from_definition({"name": "git"}, PathResolutionContext.for_process())

    assert parser.command == str(BUNDLED_GIT_PARSER)
