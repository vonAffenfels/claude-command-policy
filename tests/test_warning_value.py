"""Unit tests for the structured Warning value (layer provenance, no formatting)."""

from warning_value import Warning


def test_invalid_knob_value_warning_carries_its_layer_and_knob():
    warning = Warning.invalid_knob_value(
        layer="user",
        knob="commandSubstitutionResponse",
        configured="block",
        valid_values={"deny", "via-allowed-commands"},
        in_effect="via-allowed-commands",
    )

    assert warning.layer == "user"
    assert warning.kind == "invalid_knob_value"
    assert warning.knob == "commandSubstitutionResponse"
    assert warning.configured == "block"
    assert warning.in_effect == "via-allowed-commands"


def test_invalid_knob_value_warning_message_names_knob_value_and_layer():
    warning = Warning.invalid_knob_value(
        layer="user",
        knob="commandSubstitutionResponse",
        configured="block",
        valid_values={"deny", "via-allowed-commands"},
        in_effect="via-allowed-commands",
    )

    assert "commandSubstitutionResponse" in warning.message
    assert "block" in warning.message
    assert "via-allowed-commands" in warning.message
    assert "user" in warning.message


def test_unparseable_config_file_warning_carries_its_layer_and_path():
    warning = Warning.unparseable_config_file(layer="project", path="/tmp/x/.claude/command-policy.json")

    assert warning.layer == "project"
    assert warning.kind == "unparseable_config_file"
    assert warning.path == "/tmp/x/.claude/command-policy.json"
    assert "/tmp/x/.claude/command-policy.json" in warning.message


def test_two_warnings_built_from_the_same_facts_are_equal():
    first = Warning.invalid_knob_value(
        layer="user", knob="k", configured="x", valid_values={"a"}, in_effect="a"
    )
    second = Warning.invalid_knob_value(
        layer="user", knob="k", configured="x", valid_values={"a"}, in_effect="a"
    )

    assert first == second
