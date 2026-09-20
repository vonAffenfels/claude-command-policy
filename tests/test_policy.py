"""Unit tests for the Policy base: the for_statement/matches/decision/pass_
protocol shared by every pass."""

import pytest

from permission_decision import PermissionDecision
from policy import Policy


class _FakePolicy(Policy):
    pass_ = 3

    def __init__(self, denies=False):
        super().__init__()
        self._denies = denies

    def matches(self):
        return self._denies and self.statement == "bound-statement"

    def decision(self):
        return PermissionDecision.deny("fake objection")


def test_for_statement_binds_a_new_instance_without_mutating_the_original():
    unbound = _FakePolicy(denies=True)

    bound = unbound.for_statement("bound-statement")

    assert bound is not unbound
    assert unbound.statement is None
    assert bound.statement == "bound-statement"


def test_matches_and_decision_see_the_bound_statement():
    bound = _FakePolicy(denies=True).for_statement("bound-statement")

    assert bound.matches() is True
    assert bound.decision() == PermissionDecision.deny("fake objection")


def test_base_matches_and_decision_are_not_implemented():
    class _Bare(Policy):
        pass_ = 0

    bare = _Bare().for_statement("x")

    with pytest.raises(NotImplementedError):
        bare.matches()
    with pytest.raises(NotImplementedError):
        bare.decision()
