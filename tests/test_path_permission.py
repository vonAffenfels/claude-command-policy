"""Unit tests for path_permission.decision_for: the Read/Grep/Glob
allowedPaths decision - a domain separate from the six-pass bash pipeline
(config.py's decision_for). An unmatched path is `passthrough`, never
`deny` - allowedPaths only ever widens what auto-allows, mirroring
shfmt-permissions' analyze-path.py (READ ONLY prior art).
"""

from path_config import PathConfig
from path_permission import decision_for
from path_resolution import PathResolutionContext


def _resolution(cwd="/project", is_directory=lambda path: False):
    return PathResolutionContext(cwd=cwd, home="/home/user", is_directory_predicate=is_directory)


def test_no_path_is_passthrough():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared"}])

    result = decision_for("Read", None, config, _resolution())

    assert result.decision == "passthrough"


def test_no_rule_configured_at_all_is_passthrough():
    config = PathConfig.from_entries([])

    result = decision_for("Read", "/shared/doc.txt", config, _resolution())

    assert result.decision == "passthrough"


def test_a_rule_for_a_different_tool_does_not_match():
    config = PathConfig.from_entries([{"tools": "grep", "path": "/shared"}])

    result = decision_for("Read", "/shared/doc.txt", config, _resolution())

    assert result.decision == "passthrough"


def test_an_exact_path_match_allows():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/doc.txt"}])

    result = decision_for("Read", "/shared/doc.txt", config, _resolution())

    assert result.decision == "allow"


def test_a_path_outside_an_exact_rule_is_passthrough():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/doc.txt"}])

    result = decision_for("Read", "/shared/other.txt", config, _resolution())

    assert result.decision == "passthrough"


def test_a_directory_rule_admits_a_path_underneath_it():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/docs"}])
    resolution = _resolution(is_directory=lambda path: path == "/shared/docs")

    result = decision_for("Read", "/shared/docs/sub/doc.txt", config, resolution)

    assert result.decision == "allow"


def test_a_directory_rule_rejects_a_sibling_directory():
    """A near-miss sibling (`/shared/docs2`) must not be admitted by a rule
    for `/shared/docs` - mirrors PathResolutionContext.is_contained's own
    Flag List E8 guard against `/home/username` under `/home/user`."""
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/docs"}])
    resolution = _resolution(is_directory=lambda path: path == "/shared/docs")

    result = decision_for("Read", "/shared/docs2/doc.txt", config, resolution)

    assert result.decision == "passthrough"


def test_a_non_directory_rule_only_matches_exactly():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/doc.txt"}])
    resolution = _resolution(is_directory=lambda path: False)

    result = decision_for("Read", "/shared/doc.txt/nested", config, resolution)

    assert result.decision == "passthrough"


def test_the_all_alias_expands_to_read_grep_and_glob():
    config = PathConfig.from_entries([{"tools": "all", "path": "/shared/doc.txt"}])

    assert decision_for("Read", "/shared/doc.txt", config, _resolution()).decision == "allow"
    assert decision_for("Grep", "/shared/doc.txt", config, _resolution()).decision == "allow"
    assert decision_for("Glob", "/shared/doc.txt", config, _resolution()).decision == "allow"


def test_the_search_alias_expands_to_grep_and_glob_but_not_read():
    config = PathConfig.from_entries([{"tools": "search", "path": "/shared/doc.txt"}])

    assert decision_for("Grep", "/shared/doc.txt", config, _resolution()).decision == "allow"
    assert decision_for("Read", "/shared/doc.txt", config, _resolution()).decision == "passthrough"


def test_tool_name_matching_is_case_insensitive():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/doc.txt"}])

    result = decision_for("READ", "/shared/doc.txt", config, _resolution())

    assert result.decision == "allow"


def test_a_relative_target_resolves_against_the_injected_cwd():
    config = PathConfig.from_entries([{"tools": "read", "path": "/project/doc.txt"}])

    result = decision_for("Read", "doc.txt", config, _resolution(cwd="/project"))

    assert result.decision == "allow"


def test_a_relative_rule_path_also_resolves_against_the_injected_cwd():
    config = PathConfig.from_entries([{"tools": "read", "path": "doc.txt"}])

    result = decision_for("Read", "/project/doc.txt", config, _resolution(cwd="/project"))

    assert result.decision == "allow"
