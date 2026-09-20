"""Unit tests for RedirectOperator construction.

shfmt's redirect `Op` is an integer, not a string - a sparse slice of ONE
shared token space spanning mvdan/sh's entire grammar. These tests pin the
12-value table verified live against shfmt 3.13.1 and the fail-visible
fallback for anything outside it.
"""

from redirect_operator import RedirectOperator

VERIFIED_OPS = {
    63: ">",
    64: ">>",
    65: "<",
    66: "<>",
    67: "<&",
    68: ">&",
    69: ">|",
    71: "<<",
    72: "<<-",
    73: "<<<",
    74: "&>",
    76: "&>>",
}


def test_every_verified_op_integer_maps_to_its_symbol():
    for op, symbol in VERIFIED_OPS.items():
        operator = RedirectOperator.from_op(op)

        assert operator.symbol == symbol
        assert operator.op == op
        assert operator.is_recognized


def test_two_operators_for_the_same_op_are_equal():
    assert RedirectOperator.from_op(63) == RedirectOperator.from_op(63)


def test_operators_for_different_ops_are_not_equal():
    assert RedirectOperator.from_op(63) != RedirectOperator.from_op(65)


def test_an_operator_explains_itself_naming_its_symbol():
    operator = RedirectOperator.from_op(74)

    assert "&>" in operator.explain()


def test_an_unrecognized_op_retains_the_raw_integer():
    operator = RedirectOperator.from_op(13)  # pipe '|' - a different token category

    assert operator.op == 13
    assert operator.symbol is None
    assert not operator.is_recognized


def test_an_unrecognized_op_explains_itself_without_a_symbol():
    operator = RedirectOperator.from_op(143)  # extglob '!(' token

    assert "143" in operator.explain()
