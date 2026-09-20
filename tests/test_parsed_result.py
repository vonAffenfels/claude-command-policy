"""Unit tests for ParsedOption/ParsedPositional/ParsedResult.

ParsedResult carries TWO independently-named path fields
(paths_for_validation, paths_for_filtering) rather than the old shared
`paths` bag - see the trunk's KNOWN DEFECT note this leaf dissolves.
"""

from parsed_result import ParsedOption, ParsedPositional, ParsedResult


def test_a_result_with_no_arguments_has_no_argument_texts():
    result = ParsedResult()

    assert result.all_argument_texts() == []


def test_all_argument_texts_includes_option_names_and_their_arguments_in_order():
    result = ParsedResult(
        options=[ParsedOption("-c", ["value"]), ParsedOption("-v", [])],
        positionals=[ParsedPositional(0, "file.txt")],
    )

    assert result.all_argument_texts() == ["-c", "value", "-v", "file.txt"]


def test_positional_values_extracts_only_positional_values_in_order():
    result = ParsedResult(
        positionals=[ParsedPositional(0, "a"), ParsedPositional(1, "b")],
    )

    assert result.positional_values() == ["a", "b"]


def test_named_defaults_to_an_empty_dict():
    assert ParsedResult().named == {}


def test_named_values_are_carried_as_given():
    result = ParsedResult(named={"subcommand": "commit"})

    assert result.named == {"subcommand": "commit"}


def test_paths_for_validation_and_paths_for_filtering_are_independent_fields():
    result = ParsedResult(
        paths_for_validation=("/a",),
        paths_for_filtering=("/a", "/b"),
    )

    assert result.paths_for_validation == ("/a",)
    assert result.paths_for_filtering == ("/a", "/b")


def test_paths_default_to_empty():
    result = ParsedResult()

    assert result.paths_for_validation == ()
    assert result.paths_for_filtering == ()


def test_subcommand_defaults_to_none():
    assert ParsedResult().subcommand is None


def test_subcommand_carries_a_nested_parsed_result():
    subcommand = ParsedResult(named={"subcommand": "commit"})
    result = ParsedResult(subcommand=subcommand)

    assert result.subcommand is subcommand
