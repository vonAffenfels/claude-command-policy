"""Unit tests for DefaultParser: the dash-heuristic parser, now pure -
exercisable with no subprocess and no real filesystem access via the
injected PathResolutionContext.
"""

from default_parser import DefaultParser
from path_resolution import PathResolutionContext


def context(exists_predicate=None):
    return PathResolutionContext(cwd="/home/user/project", exists_predicate=exists_predicate)


def test_dash_prefixed_arguments_become_options():
    parser = DefaultParser.from_definition({}, context())

    result = parser.parse(["--force", "-v"])

    assert [o.name for o in result.options] == ["--force", "-v"]
    assert result.positionals == ()


def test_non_dash_arguments_become_positionals_in_order():
    parser = DefaultParser.from_definition({}, context())

    result = parser.parse(["file.txt", "other.txt"])

    assert [p.value for p in result.positionals] == ["file.txt", "other.txt"]
    assert [p.index for p in result.positionals] == [0, 1]


def test_an_absolute_positional_is_detected_as_a_path():
    parser = DefaultParser.from_definition({}, context())

    result = parser.parse(["/etc/passwd"])

    assert result.paths_for_validation == ("/etc/passwd",)
    assert result.paths_for_filtering == ("/etc/passwd",)


def test_a_home_relative_positional_is_detected_as_a_path_against_the_injected_home():
    parser = DefaultParser.from_definition({}, PathResolutionContext(cwd="/x", home="/home/user"))

    result = parser.parse(["~/notes.txt"])

    assert result.paths_for_validation == ("/home/user/notes.txt",)


def test_a_relative_positional_containing_a_slash_is_detected_as_a_path():
    parser = DefaultParser.from_definition({}, context())

    result = parser.parse(["sub/file.txt"])

    assert result.paths_for_validation == ("/home/user/project/sub/file.txt",)


def test_a_bare_word_is_a_validation_candidate_whether_or_not_the_context_says_it_exists():
    """CHANGED MEANING (improvement-20260919-112214, second fix round). This
    case previously asserted that a bare word reaches `paths_for_validation`
    only when the injected context says it exists. Under the rule that
    replaced it, this parser knows no program's grammar and so can never
    rule an argument OUT as a path operand: validation candidacy is total,
    and the exists() predicate no longer gates it.

    The predicate is not dead - it still decides FILTERING candidacy, which
    is asserted here too. That split is the whole reason ParsedResult
    carries two path fields, and this test is now the place the divergence
    is pinned."""
    parser = DefaultParser.from_definition({}, context(exists_predicate=lambda v: v == "README"))

    with_hit = parser.parse(["README"])
    with_miss = parser.parse(["missing"])

    assert with_hit.paths_for_validation == ("/home/user/project/README",)
    assert with_miss.paths_for_validation == ("/home/user/project/missing",)

    assert with_hit.paths_for_filtering == ("/home/user/project/README",)
    assert with_miss.paths_for_filtering == ()


def test_a_bare_word_filtering_path_uses_the_injected_predicate_not_the_real_filesystem():
    """Re-pointed at `paths_for_filtering` in the same change: asserting
    this against `paths_for_validation` would now pass no matter what the
    predicate returned, so it would have kept its name while proving
    nothing."""
    parser = DefaultParser.from_definition({}, context(exists_predicate=lambda v: True))

    result = parser.parse(["definitely-not-a-real-file-anywhere"])

    assert result.paths_for_filtering == ("/home/user/project/definitely-not-a-real-file-anywhere",)


def test_consumes_value_for_option_is_always_false():
    """The default parser has no configured option vocabulary at all - it
    can never consume a value for any option name (leaf 20260914-213652's
    A6 validation)."""
    parser = DefaultParser.from_definition({}, context())

    assert parser.consumes_value_for_option("-m") is False
    assert parser.consumes_value_for_option("--anything") is False
