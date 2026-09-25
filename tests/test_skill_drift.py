"""Skill drift test: asserts skills/config/SKILL.md names every member of
each code registry it documents - so adding a filter type, a top-level or
entry key, a parser type, a bundled parser, or an add-allow-policy violation
code without documenting it fails this suite, rather than the skill quietly
going stale.

Registries are extracted from the SOURCE, not hand-duplicated here, so this
test actually catches an addition to the code that the skill was never told
about - a hardcoded registry would only ever catch a skill/test mismatch,
never a skill/code one.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = PLUGIN_ROOT / "lib"
PARSERS_DIR = PLUGIN_ROOT / "parsers"
SKILL_PATH = PLUGIN_ROOT / "skills" / "config" / "SKILL.md"

SKILL_TEXT = SKILL_PATH.read_text()

from filter import _PATTERN_MATCHER_BY_TYPE  # noqa: E402
from reason_renderer import _ADD_ALLOW_POLICY_VIOLATION_EXPLANATIONS  # noqa: E402


def _regex_matches(pattern, source_file):
    text = (LIB_DIR / source_file).read_text()
    return set(re.findall(pattern, text))


def test_skill_file_exists_and_is_user_invocable():
    assert SKILL_PATH.exists()
    frontmatter = SKILL_TEXT.split("---")[1]
    assert "name: config" in frontmatter
    assert "user-invocable: true" in frontmatter


# -- filter types -------------------------------------------------------

FILTER_TYPES = set(_PATTERN_MATCHER_BY_TYPE) | {"paths", "nestedCommand"}


@pytest.mark.parametrize("filter_type", sorted(FILTER_TYPES))
def test_skill_names_every_filter_type(filter_type):
    assert filter_type in SKILL_TEXT, f"filter type {filter_type!r} is not documented in {SKILL_PATH}"


def test_filter_type_registry_is_not_accidentally_empty():
    """Guards the guard: if filter.py's registry ever became empty (an
    import error swallowed, a rename that broke the regex), the parametrized
    test above would silently collect zero cases and this suite would stop
    protecting anything."""
    assert len(FILTER_TYPES) == 10


# -- top-level config keys -----------------------------------------------

TOP_LEVEL_KEYS = _regex_matches(r'cfg\.get\("([^"]+)"', "config.py") | {"commandSubstitutionResponse"}


@pytest.mark.parametrize("key", sorted(TOP_LEVEL_KEYS))
def test_skill_names_every_top_level_key(key):
    assert key in SKILL_TEXT, f"top-level key {key!r} is not documented in {SKILL_PATH}"


def test_top_level_key_registry_is_not_accidentally_empty():
    assert len(TOP_LEVEL_KEYS) == 7


# -- allowedCommands entry keys -------------------------------------------

ENTRY_KEYS = _regex_matches(r'entry\.get\("([^"]+)"', "allowed_command.py")


@pytest.mark.parametrize("key", sorted(ENTRY_KEYS))
def test_skill_names_every_entry_key(key):
    assert key in SKILL_TEXT, f"allowedCommands entry key {key!r} is not documented in {SKILL_PATH}"


def test_entry_key_registry_is_not_accidentally_empty():
    assert len(ENTRY_KEYS) == 6


# -- commandParser types ---------------------------------------------------

PARSER_TYPES = _regex_matches(r'parser_type == "([^"]+)"', "parser_factory.py")


@pytest.mark.parametrize("parser_type", sorted(PARSER_TYPES))
def test_skill_names_every_parser_type(parser_type):
    assert f'"type": "{parser_type}"' in SKILL_TEXT, f"parser type {parser_type!r} is not documented in {SKILL_PATH}"


def test_parser_type_registry_is_not_accidentally_empty():
    assert len(PARSER_TYPES) == 3


# -- bundled parsers --------------------------------------------------------

BUNDLED_PARSER_NAMES = sorted(p.stem for p in PARSERS_DIR.glob("*.py"))


@pytest.mark.parametrize("parser_name", BUNDLED_PARSER_NAMES)
def test_skill_names_every_bundled_parser(parser_name):
    assert parser_name in SKILL_TEXT, f"bundled parser {parser_name!r} is not documented in {SKILL_PATH}"


def test_bundled_parser_registry_is_not_accidentally_empty():
    assert len(BUNDLED_PARSER_NAMES) == 17


def _describes_publishing_nested_commands(parser_name):
    result = subprocess.run(
        [sys.executable, str(PARSERS_DIR / f"{parser_name}.py")],
        input=json.dumps({"describe": True}),
        capture_output=True,
        text=True,
        timeout=5,
    )
    return json.loads(result.stdout)["publishesNestedCommands"]


def test_skills_claimed_wrapper_parser_set_matches_what_bundled_parsers_actually_describe():
    """The skill names exactly which bundled parsers can publish on the
    nestedCommands channel - cross-checked against each parser's own
    describe() response, not just asserted in prose (test_bundled_parsers.py
    already checks describe() itself; this checks the SKILL stayed honest
    about it)."""
    actual_wrappers = {name for name in BUNDLED_PARSER_NAMES if _describes_publishing_nested_commands(name)}

    # Normalise line-wrapping (a markdown formatter may rewrap this exact
    # sentence across lines) before searching for it as one string.
    flattened = " ".join(SKILL_TEXT.split())
    match = re.search(
        r"((?:`[\w-]+`,?\s*)+)are the wrapper parsers that can publish", flattened
    )
    assert match, f"expected a 'wrapper parsers that can publish' sentence naming them in {SKILL_PATH}"
    claimed_wrappers = set(re.findall(r"`([\w-]+)`", match.group(1)))

    assert claimed_wrappers == actual_wrappers


# -- add-allow-policy violation codes ---------------------------------------

VIOLATION_CODES = set(_ADD_ALLOW_POLICY_VIOLATION_EXPLANATIONS)


@pytest.mark.parametrize("code", sorted(VIOLATION_CODES))
def test_skill_names_every_add_allow_policy_violation_code(code):
    assert code in SKILL_TEXT, f"add-allow-policy violation code {code!r} is not documented in {SKILL_PATH}"


def test_violation_code_registry_is_not_accidentally_empty():
    assert len(VIOLATION_CODES) == 8


# -- dropped legacy keys must not be taught as VALID current syntax --------
#
# Some of these ARE mentioned in the skill, deliberately, as "this is
# retired, use X instead" (structured parser's retired keys, the removed
# defaultDecision knob) - exactly the guidance a config author migrating an
# old file needs. That is different from teaching them as valid schema, which
# is what this list actually guards against. Keys the skill has no reason to
# mention at all stay in the list; the two categories are kept apart, in
# their own list, precisely so a future retired-key mention doesn't
# accidentally widen this one without a conscious decision to do so.

DROPPED_LEGACY_KEYS = (
    "sensitiveVariableResponse",
    "pathValidationResponse",
    "filterRejectionResponse",
    "propagate",
    "pathValidation",
    "allowedVariables",
    "pluginProgram",
    "allowedReadPaths",
    "options_with_arguments",
    "bypass-shfmt-permissions",
)


@pytest.mark.parametrize("legacy_key", DROPPED_LEGACY_KEYS)
def test_skill_contains_no_dropped_legacy_keys(legacy_key):
    assert legacy_key not in SKILL_TEXT, f"dropped legacy key {legacy_key!r} still appears in {SKILL_PATH}"
