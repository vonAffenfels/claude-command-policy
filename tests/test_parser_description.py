"""Unit tests for ParserDescription.from_raw: judges the SHAPE of a
describe response, independent of how it was obtained (see
test_describer.py for the subprocess edge)."""

from parser_description import ParserDescription


def test_a_well_formed_response_builds_a_description():
    description = ParserDescription.from_raw(
        {"publishesNestedCommands": True, "namedValues": ["a", "b"], "optionsWithValues": ["-x"]}
    )

    assert description.publishes_nested_commands is True
    assert description.named_values == ("a", "b")
    assert description.options_with_values == ("-x",)


def test_a_non_object_response_is_a_contract_breach():
    assert ParserDescription.from_raw(["not", "an", "object"]) is None


def test_a_missing_publishes_nested_commands_key_is_a_contract_breach():
    assert ParserDescription.from_raw({"namedValues": [], "optionsWithValues": []}) is None


def test_a_non_boolean_publishes_nested_commands_is_a_contract_breach():
    assert ParserDescription.from_raw(
        {"publishesNestedCommands": "true", "namedValues": [], "optionsWithValues": []}
    ) is None


def test_a_missing_named_values_key_is_a_contract_breach():
    assert ParserDescription.from_raw({"publishesNestedCommands": False, "optionsWithValues": []}) is None


def test_a_named_values_entry_that_is_not_a_string_is_a_contract_breach():
    assert ParserDescription.from_raw(
        {"publishesNestedCommands": False, "namedValues": [1], "optionsWithValues": []}
    ) is None


def test_a_missing_options_with_values_key_is_a_contract_breach():
    assert ParserDescription.from_raw({"publishesNestedCommands": False, "namedValues": []}) is None


def test_an_options_with_values_entry_that_is_not_a_string_is_a_contract_breach():
    assert ParserDescription.from_raw(
        {"publishesNestedCommands": False, "namedValues": [], "optionsWithValues": [1]}
    ) is None


def test_two_descriptions_built_from_equivalent_input_are_equal():
    a = ParserDescription.from_raw({"publishesNestedCommands": False, "namedValues": [], "optionsWithValues": []})
    b = ParserDescription.from_raw({"publishesNestedCommands": False, "namedValues": [], "optionsWithValues": []})

    assert a == b
