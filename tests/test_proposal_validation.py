"""Unit tests for proposal_problems: validates an add-allow-policy proposal's
entry text the same way loading it into a real config would - shared by
escalation_policy.add_allow_policy_transform (the ask path) and
add_allow_write (the write side's re-check).
"""

import json

from path_resolution import PathResolutionContext
from proposal_validation import parse_entry, proposal_problems

CONTEXT = PathResolutionContext(cwd="/project")


def test_a_bare_program_name_has_no_problems():
    assert proposal_problems("rg", "user", CONTEXT) == ()


def test_a_well_formed_json_entry_has_no_problems():
    entry = json.dumps({"program": "git", "onlyTheseVariables": ["HOME"]})

    assert proposal_problems(entry, "user", CONTEXT) == ()


def test_invalid_json_is_reported_as_a_problem():
    problems = proposal_problems("{not json", "user", CONTEXT)

    assert len(problems) == 1
    assert "not valid JSON" in problems[0]


def test_an_unknown_filter_type_is_reported_as_a_problem():
    entry = json.dumps({"program": "echo", "filters": [{"type": "madeUp", "action": "block"}]})

    problems = proposal_problems(entry, "user", CONTEXT)

    assert any("madeUp" in problem for problem in problems)


def test_a_malformed_program_glob_is_reported_as_a_problem():
    entry = json.dumps({"programGlob": {"marketplace": "m", "plugin": "p", "path": "/bin/foo"}})

    problems = proposal_problems(entry, "user", CONTEXT)

    assert any("must not start with '/'" in problem for problem in problems)


def test_an_option_value_filter_the_default_parser_never_populates_is_reported_as_a_problem():
    entry = json.dumps(
        {
            "program": "git",
            "filters": [{"type": "optionValue", "option": "-m", "pattern": "wip", "action": "block"}],
        }
    )

    problems = proposal_problems(entry, "user", CONTEXT)

    assert any("-m" in problem for problem in problems)


def test_parse_entry_leaves_a_bare_program_name_as_a_string():
    assert parse_entry("rg") == "rg"


def test_parse_entry_parses_a_brace_prefixed_argument_as_json():
    assert parse_entry('{"program": "rg"}') == {"program": "rg"}
