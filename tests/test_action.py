"""Unit tests for Action: the block/required inversion shared by eight of
the nine filter classes today, now in exactly one place.

Target-absent handling lives in the three-state Matcher contract, not here -
see test_matcher.py for the four target-absent cases under both actions.
"""

import pytest

from action import Action
from config import ConfigError
from match_outcome import MatchOutcome


def test_block_action_passes_when_the_matcher_did_not_match():
    action = Action.from_definition({"action": "block"})

    assert action.applies_to(MatchOutcome.NOT_MATCHED) is True


def test_block_action_fails_when_the_matcher_matched():
    action = Action.from_definition({"action": "block"})

    assert action.applies_to(MatchOutcome.MATCHED) is False


def test_required_action_passes_when_the_matcher_matched():
    action = Action.from_definition({"action": "required"})

    assert action.applies_to(MatchOutcome.MATCHED) is True


def test_required_action_fails_when_the_matcher_did_not_match():
    action = Action.from_definition({"action": "required"})

    assert action.applies_to(MatchOutcome.NOT_MATCHED) is False


def test_action_defaults_to_block_when_not_configured():
    action = Action.from_definition({})

    assert action.applies_to(MatchOutcome.MATCHED) is False
    assert action.applies_to(MatchOutcome.NOT_MATCHED) is True


def test_an_unrecognised_action_value_is_a_config_error():
    """A typo'd action ('blcok') must not silently coerce to 'block' - see
    test_unknown_filter_action_is_rejected_at_config_load_time."""
    with pytest.raises(ConfigError):
        Action.from_definition({"action": "blcok"})
