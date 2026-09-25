"""Unit tests for AllowedCommand construction and normalisation.

Filter/parser SHAPE validation belongs to leaf 20260914-213502 (Filter/Parser);
AllowedCommand only normalises an entry into its fields and stores the filter
definitions opaquely.
"""

import pytest

from allowed_command import AllowedCommand


def test_a_bare_string_entry_normalises_to_a_program_with_no_filters():
    entry = AllowedCommand.from_entry("echo")

    assert entry.program == "echo"
    assert entry.filters == ()


def test_an_object_entry_with_no_filters_key_normalises_the_same_as_a_bare_string():
    bare = AllowedCommand.from_entry("echo")
    object_entry = AllowedCommand.from_entry({"program": "echo"})

    assert bare == object_entry


def test_an_object_entry_carries_its_filters():
    entry = AllowedCommand.from_entry(
        {"program": "echo", "filters": [{"type": "optionPresent", "option": "-n", "action": "block"}]}
    )

    assert entry.filters == ({"type": "optionPresent", "option": "-n", "action": "block"},)


def test_an_object_entry_carries_its_only_these_variables():
    entry = AllowedCommand.from_entry({"program": "echo", "onlyTheseVariables": ["HOME"]})

    assert entry.only_these_variables == ("HOME",)


def test_a_bare_string_entry_declares_no_only_these_variables():
    entry = AllowedCommand.from_entry("echo")

    assert entry.only_these_variables == ()


def test_has_no_path_parameters_defaults_to_false():
    entry = AllowedCommand.from_entry("cat")

    assert entry.has_no_path_parameters is False


def test_an_object_entry_carries_has_no_path_parameters():
    entry = AllowedCommand.from_entry({"program": "cat", "hasNoPathParameters": True})

    assert entry.has_no_path_parameters is True


def test_an_object_entry_carries_its_command_parser():
    entry = AllowedCommand.from_entry(
        {"program": "git", "commandParser": {"type": "structured", "options": [{"option": "-m", "arguments": 1}]}}
    )

    assert entry.command_parser == {"type": "structured", "options": [{"option": "-m", "arguments": 1}]}


def test_a_bare_string_entry_has_no_command_parser():
    entry = AllowedCommand.from_entry("git")

    assert entry.command_parser is None


def test_two_entries_built_from_equivalent_input_are_equal():
    assert AllowedCommand.from_entry("echo") == AllowedCommand.from_entry("echo")


def test_a_bare_entry_explains_itself_as_placing_no_constraint():
    entry = AllowedCommand.from_entry("echo")

    explanation = entry.explain()

    assert "echo" in explanation
    assert "no filters" in explanation.lower()


def test_a_filtered_entry_explains_its_filter_count():
    entry = AllowedCommand.from_entry(
        {
            "program": "echo",
            "filters": [
                {"type": "optionPresent", "option": "-n", "action": "block"},
                {"type": "optionPresent", "option": "-e", "action": "required"},
            ],
        }
    )

    explanation = entry.explain()

    assert "echo" in explanation
    assert "2" in explanation


def test_explain_states_which_variables_are_permitted_when_only_these_variables_is_set():
    entry = AllowedCommand.from_entry({"program": "touch", "onlyTheseVariables": ["SESSION_ID", "HOME"]})

    explanation = entry.explain()

    assert "SESSION_ID" in explanation
    assert "HOME" in explanation


def test_explain_says_nothing_about_variables_when_only_these_variables_is_empty():
    entry = AllowedCommand.from_entry("touch")

    explanation = entry.explain()

    assert "variable" not in explanation.lower()


# -- programGlob --------------------------------------------------------


def test_an_object_entry_carries_its_program_glob():
    entry = AllowedCommand.from_entry(
        {"programGlob": {"marketplace": "vonaffenfels-dev-tools", "plugin": "improvement", "path": "bin/foo"}}
    )

    assert entry.program_glob == {
        "marketplace": "vonaffenfels-dev-tools",
        "plugin": "improvement",
        "path": "bin/foo",
    }
    assert entry.program is None


def test_a_bare_string_entry_has_no_program_glob():
    entry = AllowedCommand.from_entry("echo")

    assert entry.program_glob is None


def test_a_program_glob_entry_rejects_a_leading_slash_path():
    """A malformed programGlob is a construction-time PROBLEM (improvement
    20260925-120037), not a raise - the entry never matches any invocation
    (has_valid_program_glob is False) and its problem is reported through
    Config.warnings() instead."""
    entry = AllowedCommand.from_entry({"programGlob": {"marketplace": "m", "plugin": "p", "path": "/bin/foo"}})

    assert entry.has_valid_program_glob is False
    assert any("must not start with '/'" in problem for problem in entry.problems())


@pytest.mark.parametrize("field", ["marketplace", "plugin", "path"])
def test_a_program_glob_entry_rejects_dot_dot_in_any_field(field):
    program_glob = {"marketplace": "m", "plugin": "p", "path": "bin/foo"}
    program_glob[field] = "../escape"

    entry = AllowedCommand.from_entry({"programGlob": program_glob})

    assert entry.has_valid_program_glob is False
    assert any("must not contain '..'" in problem for problem in entry.problems())


@pytest.mark.parametrize("field", ["marketplace", "plugin", "path"])
def test_a_program_glob_entry_rejects_a_missing_field(field):
    """Carried-forward finding from leaf 20260915-011123's review: an
    incomplete programGlob dict must be rejected, not left to raise an
    uncaught KeyError at MATCH time inside `_program_glob_pattern` - the old
    engine returned None (skip the entry) for exactly this case. This engine
    reports it as a construction-time problem and never matches any
    invocation with it, which is strictly better than either the old silent
    skip or a match-time crash."""
    program_glob = {"marketplace": "m", "plugin": "p", "path": "bin/foo"}
    del program_glob[field]

    entry = AllowedCommand.from_entry({"programGlob": program_glob})

    assert entry.has_valid_program_glob is False
    assert any(f"missing required field {field!r}" in problem for problem in entry.problems())


def test_program_glob_and_program_are_mutually_exclusive():
    entry = AllowedCommand.from_entry(
        {"program": "foo", "programGlob": {"marketplace": "m", "plugin": "p", "path": "bin/foo"}}
    )

    assert entry.has_valid_program_glob is False
    assert any("both 'program' and 'programGlob'" in problem for problem in entry.problems())
