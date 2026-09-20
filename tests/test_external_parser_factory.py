"""Unit tests for ExternalParserFactory: the edge-level collaborator that
performs the actual subprocess call for CommandParser/ProvidedParser - the
ONLY place subprocess.run appears in this leaf's output.

Every failure mode collapses to None (the pipeline leaf, 20260914-213652,
turns a None into the constant deny+hint outcome - there is no configurable
fallback any more).
"""

import json
import sys
from pathlib import Path

from external_parser_factory import ExternalParserFactory

FIXTURES = Path(__file__).parent / "fixtures" / "fake_parsers"


class _FakeParser:
    def __init__(self, command, timeout_ms=1000):
        self.command = command
        self.timeout_ms = timeout_ms


def fixture(name):
    return _FakeParser(command=str(FIXTURES / name))


def test_a_well_behaved_script_returns_its_parsed_json():
    factory = ExternalParserFactory()

    output = factory.raw_output_for(fixture("echoes_named_value.py"), ["arg1"])

    assert output == {"named": {"echoed": "arg1"}}


def test_a_non_zero_exit_yields_none():
    factory = ExternalParserFactory()

    assert factory.raw_output_for(fixture("exits_nonzero.py"), []) is None


def test_a_timeout_yields_none():
    factory = ExternalParserFactory()
    parser = _FakeParser(command=str(FIXTURES / "sleeps_forever.py"), timeout_ms=50)

    assert factory.raw_output_for(parser, []) is None


def test_malformed_json_output_yields_none():
    factory = ExternalParserFactory()

    assert factory.raw_output_for(fixture("prints_garbage.py"), []) is None


def test_a_missing_script_yields_none():
    factory = ExternalParserFactory()
    parser = _FakeParser(command=str(FIXTURES / "does_not_exist.py"))

    assert factory.raw_output_for(parser, []) is None


def test_a_non_executable_script_yields_none():
    factory = ExternalParserFactory()
    parser = _FakeParser(command=str(FIXTURES / "not_executable.py"))

    assert factory.raw_output_for(parser, []) is None


def test_an_empty_command_path_yields_none():
    factory = ExternalParserFactory()
    parser = _FakeParser(command="")

    assert factory.raw_output_for(parser, []) is None


def test_arguments_are_passed_to_the_script_as_json_on_stdin():
    factory = ExternalParserFactory()

    output = factory.raw_output_for(fixture("echoes_named_value.py"), ["hello world"])

    assert output == {"named": {"echoed": "hello world"}}
