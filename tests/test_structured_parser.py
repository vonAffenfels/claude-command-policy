"""Unit tests for StructuredParser: DECLARED knowledge of a program's
argument grammar, now pure via the injected PathResolutionContext.

Path candidacy for `paths_for_validation` defaults to ACTIVE for every slot
(improvement-20260920-131722, mirroring DefaultParser's total candidacy from
improvement-20260919-112214) - only an explicit `path: false` declaration
rules a slot out. `paths_for_filtering` keeps the old heuristic-over-
undeclared-positionals behaviour, because PathsFilter's `exactly` semantics
wants a precise set, not a conservative one.
"""

from config import ConfigError
import pytest

from path_resolution import PathResolutionContext
from structured_parser import StructuredParser


def context(exists_predicate=None):
    return PathResolutionContext(cwd="/home/user/project", exists_predicate=exists_predicate)


# --- tokenization: consuming options, doubleDashStops, equals-style ---


def test_a_declared_option_consumes_its_configured_number_of_arguments():
    parser = StructuredParser.from_definition({"options": [{"option": "-c", "arguments": 1}]}, context())

    result = parser.parse(["-c", "value", "positional"])

    assert result.options[0].name == "-c"
    assert result.options[0].arguments == ("value",)
    assert [p.value for p in result.positionals] == ["positional"]


def test_a_declared_option_can_consume_multiple_arguments():
    parser = StructuredParser.from_definition({"options": [{"option": "--range", "arguments": 2}]}, context())

    result = parser.parse(["--range", "1", "10"])

    assert result.options[0].arguments == ("1", "10")


def test_a_bare_string_option_declaration_is_a_valueless_flag():
    """A bare string item in `options` means exactly what the (formerly
    inert) `options` key already meant: the option exists, but consumes
    nothing - so a stale `options: ["-v"]` list keeps its former meaning."""
    parser = StructuredParser.from_definition({"options": ["-v"]}, context())

    result = parser.parse(["-v", "value"])

    assert result.options[0].name == "-v"
    assert result.options[0].arguments == ()
    assert [p.value for p in result.positionals] == ["value"]
    assert parser.consumes_value_for_option("-v") is False


def test_an_undeclared_dash_argument_is_still_an_option_with_no_consumed_arguments():
    parser = StructuredParser.from_definition({}, context())

    result = parser.parse(["-v"])

    assert result.options[0].name == "-v"
    assert result.options[0].arguments == ()


def test_equals_style_long_options_split_name_and_value():
    parser = StructuredParser.from_definition({}, context())

    result = parser.parse(["--config=value"])

    assert result.options[0].name == "--config"
    assert result.options[0].arguments == ("value",)


def test_double_dash_stops_option_parsing_when_configured():
    parser = StructuredParser.from_definition({"doubleDashStops": True}, context())

    result = parser.parse(["-v", "--", "-not-an-option"])

    assert [o.name for o in result.options] == ["-v"]
    assert [p.value for p in result.positionals] == ["-not-an-option"]


def test_consumes_value_for_option_reflects_the_declared_argument_count():
    parser = StructuredParser.from_definition({"options": [{"option": "-m", "arguments": 1}]}, context())

    assert parser.consumes_value_for_option("-m") is True
    assert parser.consumes_value_for_option("-v") is False


# --- path candidacy for validation: total by default, ruled out only by declaration ---


def test_an_undeclared_positional_is_a_validation_candidate_even_when_it_does_not_look_like_a_path():
    """The headline behaviour change: no shape heuristic drives validation
    any more. `notafile` has no slash, no leading dot/tilde, and does not
    exist - the OLD heuristic would have ruled it out. It must now still be
    a validation candidate, precisely because nothing declared it is not a
    path. `paths_for_filtering`, by contrast, keeps the heuristic and must
    NOT contain it."""
    parser = StructuredParser.from_definition({}, context())

    result = parser.parse(["notafile"])

    assert result.paths_for_validation == ("/home/user/project/notafile",)
    assert result.paths_for_filtering == ()


def test_a_positional_declared_path_false_is_excluded_from_validation():
    parser = StructuredParser.from_definition({"positionals": [{"index": 0, "path": False}]}, context())

    result = parser.parse(["anything"])

    assert result.paths_for_validation == ()


def test_a_positional_declared_path_true_resolves_via_the_injected_context():
    parser = StructuredParser.from_definition({"positionals": [{"index": 0, "path": True}]}, context())

    result = parser.parse(["input.txt"])

    assert result.paths_for_validation == ("/home/user/project/input.txt",)


def test_an_undeclared_options_consumed_value_is_a_validation_candidate():
    """`-o` is declared to consume one argument but says nothing about
    path-ness, so the secure default (path-active) applies to its value."""
    parser = StructuredParser.from_definition({"options": [{"option": "-o", "arguments": 1}]}, context())

    result = parser.parse(["-o", "out.txt"])

    assert "/home/user/project/out.txt" in result.paths_for_validation


def test_an_options_value_declared_path_false_is_excluded_from_validation():
    parser = StructuredParser.from_definition(
        {"options": [{"option": "--colors", "arguments": 1, "path": False}]}, context()
    )

    result = parser.parse(["--colors", "anything"])

    assert "/home/user/project/anything" not in result.paths_for_validation


def test_an_undeclared_bare_flags_own_token_is_still_a_validation_candidate():
    """Every option token is a candidate whether or not it is declared -
    mirroring DefaultParser's uniform treatment. Harmless: an option token
    resolves project-relative and stays contained, so declaring valueless
    flags is optional."""
    parser = StructuredParser.from_definition({}, context())

    result = parser.parse(["--verbose"])

    assert result.paths_for_validation == ("/home/user/project/--verbose",)


def test_joined_form_contributes_the_value_alone_not_the_whole_word():
    """`--colors=/etc/passwd` must resolve to `/etc/passwd`, never
    `<project>/--colors=/etc/passwd` - burying the value under the project
    root is exactly how the literal twin of this hole stayed open."""
    parser = StructuredParser.from_definition({}, context())

    result = parser.parse(["--colors=/etc/passwd"])

    assert "/etc/passwd" in result.paths_for_validation
    assert not any("--colors=" in path for path in result.paths_for_validation)


def test_an_empty_argument_contributes_no_validation_candidate():
    parser = StructuredParser.from_definition({}, context())

    result = parser.parse([""])

    assert result.paths_for_validation == ()


# --- path candidacy for filtering: declarations plus heuristic, never widened ---


def test_a_declared_path_option_value_is_a_filtering_candidate():
    parser = StructuredParser.from_definition({"options": [{"option": "-o", "arguments": 1}]}, context())

    result = parser.parse(["-o", "out.txt"])

    assert result.paths_for_filtering == ("/home/user/project/out.txt",)


def test_a_declared_non_path_option_value_is_not_a_filtering_candidate():
    parser = StructuredParser.from_definition(
        {"options": [{"option": "-o", "arguments": 1, "path": False}]}, context()
    )

    result = parser.parse(["-o", "out.txt"])

    assert result.paths_for_filtering == ()


def test_an_undeclared_positional_still_uses_heuristic_path_detection_for_filtering_only():
    parser = StructuredParser.from_definition({}, context())

    result = parser.parse(["/etc/passwd"])

    assert result.paths_for_filtering == ("/etc/passwd",)
    assert result.paths_for_validation == ("/etc/passwd",)


def test_a_positional_declared_path_false_is_not_sent_through_the_filtering_heuristic():
    """Declared-false is a definitive answer, not merely 'undeclared' -
    it must not fall through to the heuristic either."""
    parser = StructuredParser.from_definition({"positionals": [{"index": 0, "path": False}]}, context())

    result = parser.parse(["/etc/passwd"])

    assert result.paths_for_filtering == ()


# --- retired keys fail loudly ---


def test_options_with_arguments_is_a_retired_key():
    with pytest.raises(ConfigError):
        StructuredParser.from_definition({"optionsWithArguments": ["-c"]}, context())


def test_path_options_is_a_retired_key():
    with pytest.raises(ConfigError):
        StructuredParser.from_definition({"pathOptions": ["-o"]}, context())


def test_path_positionals_is_a_retired_key():
    with pytest.raises(ConfigError):
        StructuredParser.from_definition({"pathPositionals": [0]}, context())
