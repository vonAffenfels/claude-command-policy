"""Unit tests for Describer: the edge-level collaborator that asks an
external parser script its own static capabilities via stdin
{"describe": true} - the describe-channel counterpart to
ExternalParserFactory (test_external_parser_factory.py).
"""

from pathlib import Path

from describer import Describer
from parser_description import ParserDescription

FIXTURES = Path(__file__).parent / "fixtures" / "fake_parsers"


def fixture(name):
    return str(FIXTURES / name)


def test_a_well_behaved_script_returns_its_parsed_description():
    describer = Describer()

    description = describer.describe(fixture("describes_correctly.py"))

    assert description == ParserDescription(
        publishes_nested_commands=True, named_values=["echoed"], options_with_values=["-m"]
    )


def test_an_empty_command_yields_none():
    describer = Describer()

    assert describer.describe("") is None


def test_a_non_zero_exit_yields_none():
    describer = Describer()

    assert describer.describe(fixture("exits_nonzero.py")) is None


def test_a_timeout_yields_none():
    describer = Describer()

    assert describer.describe(fixture("sleeps_forever.py"), timeout_ms=50) is None


def test_malformed_json_output_yields_none():
    describer = Describer()

    assert describer.describe(fixture("prints_garbage.py")) is None


def test_a_missing_script_yields_none():
    describer = Describer()

    assert describer.describe(fixture("does_not_exist.py")) is None


def test_a_non_executable_script_yields_none():
    describer = Describer()

    assert describer.describe(fixture("not_executable.py")) is None


def test_a_response_missing_a_required_key_is_a_contract_breach():
    describer = Describer()

    assert describer.describe(fixture("describe_missing_key.py")) is None


def test_a_response_with_a_wrongly_typed_key_is_a_contract_breach():
    describer = Describer()

    assert describer.describe(fixture("describe_wrong_type.py")) is None


def test_a_script_never_written_for_describe_is_a_contract_breach():
    """A pre-existing parser script that answers {"arguments": [...]} but
    was never taught the describe channel still returns SOME JSON - just
    not describe-shaped JSON - so this is the same contract-breach path as
    a missing key, not a malformed-JSON or non-zero-exit failure."""
    describer = Describer()

    assert describer.describe(fixture("echoes_named_value.py")) is None


def test_describe_is_memoised_per_script_path(monkeypatch):
    describer = Describer()
    calls = {"n": 0}
    real_describe = Describer._describe_uncached

    def counting_describe(self, command, timeout_ms):
        calls["n"] += 1
        return real_describe(self, command, timeout_ms)

    monkeypatch.setattr(Describer, "_describe_uncached", counting_describe)

    describer.describe(fixture("describes_correctly.py"))
    describer.describe(fixture("describes_correctly.py"))

    assert calls["n"] == 1


def test_a_second_describer_instance_has_its_own_memo():
    fresh = Describer()

    assert fresh.describe(fixture("describes_correctly.py")) is not None
