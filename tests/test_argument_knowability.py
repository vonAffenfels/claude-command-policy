"""Unit tests for ArgumentKnowability (improvement-20260919-112214): the
per-argument value object replacing `_substitution_indices` /
`_substitution_override`. Built directly from `Argument` value objects so a
test can construct the exact fixture it needs without going through a full
`Statement.from_command()` parse - `Statement.from_command` IS exercised
too, in the decision-spec suite and in test_allowed_command_policy.py, but
these tests pin the value object's own three behaviours in isolation.
"""

from statement import Argument
from argument_knowability import ArgumentKnowability, IndexScheme


def _knowable(text):
    return Argument(text=text, contains_substitution=False, referenced_variables=(), word_safe=True)


def _unknowable_variable(text="", word_safe=False):
    return Argument(text=text, contains_substitution=False, referenced_variables=("HOME",), word_safe=word_safe)


def _unknowable_substitution(text="", word_safe=False):
    return Argument(text=text, contains_substitution=True, referenced_variables=(), word_safe=word_safe)


class TestDefeatsAbsenceProof:
    """The `block` rule: unknowable content ANYWHERE defeats absence proof,
    regardless of dash-prefix - the fix for the dash-skip bug that let
    `--dang$(echo x)` slip an unconditional block filter."""

    def test_false_when_every_argument_is_fully_knowable(self):
        knowability = ArgumentKnowability.of([_knowable("safe"), _knowable("--flag")])

        assert knowability.defeats_absence_proof() is False

    def test_true_for_an_unknowable_variable_reference(self):
        knowability = ArgumentKnowability.of([_knowable("other"), _unknowable_variable()])

        assert knowability.defeats_absence_proof() is True

    def test_true_for_an_unknowable_substitution(self):
        knowability = ArgumentKnowability.of([_unknowable_substitution()])

        assert knowability.defeats_absence_proof() is True

    def test_true_even_when_the_unknowable_argument_is_dash_prefixed(self):
        """The dash-skip bug: `_substitution_indices` used to `continue` past
        any argument starting with "-", so `--dang$(echo x)` was invisible to
        the absence rule entirely. Knowability must not repeat that mistake."""
        knowability = ArgumentKnowability.of([_unknowable_substitution(text="--dang")])

        assert knowability.defeats_absence_proof() is True

    def test_false_for_an_empty_argument_list(self):
        assert ArgumentKnowability.of([]).defeats_absence_proof() is False


class TestKnowableTexts:
    """The `required`-for-non-index-matchers rule: unknowable arguments are
    DROPPED, not contributed as "" - so a literal elsewhere in the command
    stays provable instead of being diluted into a non-matching join."""

    def test_returns_every_text_when_all_arguments_are_knowable(self):
        knowability = ArgumentKnowability.of([_knowable("safe"), _knowable("--flag")])

        assert knowability.knowable_texts() == ["safe", "--flag"]

    def test_omits_an_unknowable_arguments_text_entirely(self):
        """Not "": the unknowable argument must be absent from the list, so a
        second pure parse over the result never sees a spurious empty
        positional in its place."""
        knowability = ArgumentKnowability.of([_knowable("safe"), _unknowable_variable()])

        assert knowability.knowable_texts() == ["safe"]

    def test_preserves_order_of_the_surviving_knowable_arguments(self):
        knowability = ArgumentKnowability.of(
            [_knowable("first"), _unknowable_variable(), _knowable("third")]
        )

        assert knowability.knowable_texts() == ["first", "third"]


class TestFirstShiftingPosition:
    """The index-shift rule: only a word-count-CHANGING expansion shifts a
    pinned index (`not argument.word_safe`), and the dash heuristic still
    determines option-vs-positional counting exactly as before - only the
    trigger condition (word_safe rather than contains_substitution) changed,
    so a fully-knowable word never shifts and a word-safe (double-quoted)
    expansion never shifts either."""

    def test_none_when_nothing_can_shift(self):
        knowability = ArgumentKnowability.of([_knowable("first"), _knowable("second")])

        assert knowability.first_shifting_position(IndexScheme.COMBINED) is None
        assert knowability.first_shifting_position(IndexScheme.POSITIONAL) is None

    def test_a_word_safe_double_quoted_expansion_does_not_shift(self):
        """The one newly-ALLOWED shape: a double-quoted substitution/variable
        is guaranteed to be exactly one word, so it must not be treated as a
        shift source even though it is not fully knowable."""
        word_safe_expansion = _unknowable_substitution(text="", word_safe=True)
        knowability = ArgumentKnowability.of([word_safe_expansion, _knowable("expected-second")])

        assert knowability.first_shifting_position(IndexScheme.POSITIONAL) is None

    def test_combined_scheme_counts_all_options_plus_positionals_before_the_shift(self):
        """Mirrors `_substitution_indices`'s own combined-index arithmetic:
        ALL dash-prefixed arguments count toward n_options (options always
        precede positionals in ParsedResult.all_argument_texts()), plus the
        positionals seen strictly before the first shifting one."""
        knowability = ArgumentKnowability.of(
            [_unknowable_substitution(), _knowable("--required-second-argument")]
        )

        assert knowability.first_shifting_position(IndexScheme.COMBINED) == 1

    def test_positional_scheme_counts_only_positionals_before_the_shift(self):
        knowability = ArgumentKnowability.of(
            [_knowable("expected-first"), _unknowable_substitution()]
        )

        assert knowability.first_shifting_position(IndexScheme.POSITIONAL) == 1

    def test_dash_prefixed_arguments_are_skipped_by_the_shift_scan_itself(self):
        """The Implementation Notes' explicit carve-out: the dash heuristic
        stays for the two INDEX schemes, so a dash-prefixed unknowable
        argument is not itself treated as a shift source by this scan (the
        block rule above is what closes that particular hole instead)."""
        knowability = ArgumentKnowability.of(
            [_unknowable_substitution(text="--dang"), _knowable("after")]
        )

        assert knowability.first_shifting_position(IndexScheme.COMBINED) is None
        assert knowability.first_shifting_position(IndexScheme.POSITIONAL) is None
