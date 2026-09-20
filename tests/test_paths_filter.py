"""Unit tests for PathsFilter - NOT a Filter{Matcher, Action}: it has no
action concept, so it stays its own value object outside that composition.

Both edge cases are load-bearing and were untested-by-name in the old suite:
empty parsed.paths passes (nothing to validate); non-empty paths with an
empty `exactly` list fails (no paths allowed).
"""

from parsed_result import ParsedResult
from path_resolution import PathResolutionContext
from paths_filter import PathsFilter


def context():
    return PathResolutionContext(cwd="/home/user/project")


def test_empty_paths_for_filtering_passes_with_nothing_to_validate():
    filter_ = PathsFilter.from_definition({"exactly": []}, context())

    assert filter_.matches(ParsedResult(paths_for_filtering=())) is True


def test_non_empty_paths_with_an_empty_exactly_list_fails():
    filter_ = PathsFilter.from_definition({"exactly": []}, context())

    assert filter_.matches(ParsedResult(paths_for_filtering=("/home/user/project/a.txt",))) is False


def test_a_path_matching_the_only_exactly_entry_passes():
    filter_ = PathsFilter.from_definition({"exactly": "a.txt"}, context())

    assert filter_.matches(ParsedResult(paths_for_filtering=("/home/user/project/a.txt",))) is True


def test_a_path_outside_every_exactly_entry_fails():
    filter_ = PathsFilter.from_definition({"exactly": "a.txt"}, context())

    assert filter_.matches(ParsedResult(paths_for_filtering=("/home/user/project/b.txt",))) is False


def test_a_string_exactly_value_is_treated_as_a_single_entry_list():
    filter_ = PathsFilter.from_definition({"exactly": "a.txt"}, context())

    assert filter_.matches(ParsedResult(paths_for_filtering=("/home/user/project/a.txt",))) is True


def test_exactly_entries_resolve_against_the_injected_cwd_not_the_process_cwd():
    filter_ = PathsFilter.from_definition({"exactly": ["a.txt"]}, PathResolutionContext(cwd="/other/dir"))

    assert filter_.matches(ParsedResult(paths_for_filtering=("/other/dir/a.txt",))) is True
    assert filter_.matches(ParsedResult(paths_for_filtering=("/home/user/project/a.txt",))) is False


def test_all_detected_paths_must_match_for_the_filter_to_pass():
    filter_ = PathsFilter.from_definition({"exactly": ["a.txt"]}, context())

    both_match = ("/home/user/project/a.txt",)
    one_does_not = ("/home/user/project/a.txt", "/home/user/project/b.txt")

    assert filter_.matches(ParsedResult(paths_for_filtering=both_match)) is True
    assert filter_.matches(ParsedResult(paths_for_filtering=one_does_not)) is False


def test_explain_names_it_as_a_paths_restriction():
    filter_ = PathsFilter.from_definition({"exactly": []}, context())

    assert filter_.explain() == "paths filter restricting which paths this entry allows"


def test_derive_alternative_points_to_an_allowed_prefix():
    filter_ = PathsFilter.from_definition({"exactly": []}, context())

    assert filter_.derive_alternative() == "use a path under one of the allowed prefixes"
