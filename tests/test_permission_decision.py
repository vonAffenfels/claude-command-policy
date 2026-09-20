"""Unit tests for PermissionDecision: the simple {decision, reason}
container replacing AnalysisResult."""

from permission_decision import PermissionDecision


def test_allow_carries_no_reason():
    decision = PermissionDecision.allow()

    assert decision.decision == "allow"
    assert decision.reason is None
    assert decision.is_allow is True


def test_deny_carries_its_reason():
    decision = PermissionDecision.deny("blocked command invoked: rm")

    assert decision.decision == "deny"
    assert decision.reason == "blocked command invoked: rm"
    assert decision.is_allow is False


def test_ask_and_passthrough_are_distinct_from_allow_and_deny():
    assert PermissionDecision.ask("needs a durable fix").decision == "ask"
    assert PermissionDecision.passthrough("escalated by name").decision == "passthrough"


def test_equality_compares_decision_and_reason():
    assert PermissionDecision.deny("x") == PermissionDecision.deny("x")
    assert PermissionDecision.deny("x") != PermissionDecision.deny("y")
    assert PermissionDecision.allow() == PermissionDecision.allow()
