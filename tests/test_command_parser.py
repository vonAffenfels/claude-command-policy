"""Unit tests for CommandParser: pure config plus interpret(raw_output).

No subprocess call lives here any more - ExternalParserFactory owns that
(see test_external_parser_factory.py). fallback is GONE from the schema:
deny+hint is a constant the pipeline leaf applies whenever the factory
yields None, so CommandParser never reads a `fallback` key at all.
"""

from command_parser import CommandParser


def test_from_definition_carries_the_configured_command():
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    assert parser.command == "/x/p.py"


def test_from_definition_defaults_timeout_ms_to_one_second():
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    assert parser.timeout_ms == 1000


def test_from_definition_carries_a_configured_timeout_ms():
    parser = CommandParser.from_definition({"command": "/x/p.py", "timeout_ms": 2500})

    assert parser.timeout_ms == 2500


def test_interpret_builds_options_and_positionals_from_raw_output():
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    result = parser.interpret(
        {
            "options": [{"name": "-v", "arguments": []}],
            "positionals": [{"index": 0, "value": "file.txt"}],
        }
    )

    assert result.options[0].name == "-v"
    assert result.positionals[0].value == "file.txt"


def test_interpret_carries_named_values():
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    result = parser.interpret({"named": {"subcommand": "commit"}})

    assert result.named == {"subcommand": "commit"}


def test_interpret_populates_both_path_fields_from_the_scripts_paths_key():
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    result = parser.interpret({"paths": ["/a/b.txt"]})

    assert result.paths_for_validation == ("/a/b.txt",)
    assert result.paths_for_filtering == ("/a/b.txt",)


def test_interpret_recurses_into_a_nested_subcommand():
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    result = parser.interpret({"subcommand": {"named": {"subcommand": "commit"}}})

    assert result.subcommand.named == {"subcommand": "commit"}


def test_interpret_defaults_missing_keys_to_empty():
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    result = parser.interpret({})

    assert result.options == ()
    assert result.positionals == ()
    assert result.named == {}
    assert result.subcommand is None
    assert result.nested_commands == ()


def test_interpret_builds_nested_commands_from_the_dedicated_channel():
    """leaf 20260914-213652's design decision: sub-commands arrive on their
    own `nestedCommands` channel, a sibling of `named` - never folded into
    an ordinary named value."""
    parser = CommandParser.from_definition({"command": "/x/p.py"})

    result = parser.interpret({"nestedCommands": [{"text": "rm -rf ./build", "shape": "shell"}]})

    assert len(result.nested_commands) == 1
    assert result.nested_commands[0].text == "rm -rf ./build"
    assert result.nested_commands[0].shape == "shell"
