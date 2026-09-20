"""Unit tests for PathConfig and its PathRule entries (the allowedPaths key).

Matching against a Read/Grep/Glob path is analyze-path's job; this leaf only
constructs the value objects, merges them (union) and lets them explain
themselves.
"""

from path_config import PathConfig, PathRule


def test_a_path_rule_carries_its_tools_and_path():
    rule = PathRule.from_entry({"tools": ["read", "grep"], "path": "/shared/docs"})

    assert rule.tools == ("read", "grep")
    assert rule.path == "/shared/docs"


def test_a_path_rule_normalises_a_bare_string_tool_to_one_element():
    rule = PathRule.from_entry({"tools": "read", "path": "/shared/docs"})

    assert rule.tools == ("read",)


def test_path_config_carries_its_rules():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/docs"}])

    assert config.rules == (PathRule.from_entry({"tools": "read", "path": "/shared/docs"}),)


def test_path_config_unions_with_another_layer():
    base = PathConfig.from_entries([{"tools": "read", "path": "/a"}])
    overlay = PathConfig.from_entries([{"tools": "read", "path": "/b"}])

    merged = base.union(overlay)

    assert merged.rules == (
        PathRule.from_entry({"tools": "read", "path": "/a"}),
        PathRule.from_entry({"tools": "read", "path": "/b"}),
    )


def test_an_empty_path_config_explains_that_nothing_is_configured():
    assert "none" in PathConfig.from_entries([]).explain().lower()


def test_a_populated_path_config_explains_each_rule():
    config = PathConfig.from_entries([{"tools": "read", "path": "/shared/docs"}])

    assert "/shared/docs" in config.explain()
    assert "read" in config.explain()
