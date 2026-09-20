"""ArgumentKnowability: what an invocation's own arguments prove, given that
some of them may be only a FRAGMENT of their real runtime value.

Replaces the substitution-specific `_substitution_indices` /
`_substitution_override` pair (allowed_command_policy.py) with one concept
covering variables and substitutions uniformly - both are unknowable at
analysis time, and a matcher comparing a fragment as though it were the
complete argument is unsound in both directions (improvement-20260919-
112214). Built directly from `Argument` value objects (`statement.py`),
which already carry `contains_substitution` / `referenced_variables` per
word - this class only ever COMBINES that existing per-word signal; it
parses nothing itself.

Three independent questions, three methods - deliberately not one combined
"is this okay" verdict, since each feeds a different rule at the call site:

  - `defeats_absence_proof()` - the `block` rule. Unknowable content
    ANYWHERE defeats it, dash-prefixed words included (the old dash-skip in
    `_substitution_indices` let an option-shaped word carrying a substitution
    escape even the unconditional block rule - see the improvement's Finding
    3). This is the one method that must consider EVERY argument.
  - `knowable_texts()` - the `required`-for-non-index-matchers rule. Drops
    unknowable arguments entirely rather than contributing "" in their
    place, so a second, pure re-parse over the result proves presence from
    literal evidence alone without an unknowable neighbour diluting a joined-
    text search (`rg safe $HOME` against `required ^safe$` must ALLOW - the
    literal `safe` is complete and provable in its own word).
  - `first_shifting_position(scheme)` - the `required`-for-index-matchers
    rule. Only a word-count-CHANGING expansion shifts what follows it
    (`argument.word_safe` is False), and - unlike the other two methods -
    the dash heuristic still gates which arguments even participate in the
    scan, exactly as `_substitution_indices` did: option-vs-positional
    counting is a property specific to the two index schemes
    (`argumentAtIndex`'s combined space, `positionalArgAtIndex`'s
    positional-only space), not to unknowability in general.
"""

from __future__ import annotations

import enum


class IndexScheme(enum.Enum):
    """Which of ParsedResult's two indexing spaces a `required` index filter
    counts in - COMBINED is `argumentAtIndex`'s (`all_argument_texts()`,
    options-then-positionals); POSITIONAL is `positionalArgAtIndex`'s
    (positionals only)."""

    COMBINED = "combined"
    POSITIONAL = "positional"


class ArgumentKnowability:
    def __init__(self, arguments):
        self._arguments = tuple(arguments)

    @classmethod
    def of(cls, arguments):
        return cls(arguments)

    def defeats_absence_proof(self):
        return any(not _is_fully_knowable(argument) for argument in self._arguments)

    def knowable_texts(self):
        return [argument.text for argument in self._arguments if _is_fully_knowable(argument)]

    def texts_with_unknowable_marked(self, marker):
        """Every argument's text, with `marker` appended to each argument
        that is NOT fully knowable - the probe that asks a parser which
        SLOTS it treats as path operands (allowed_command_policy.py's
        `_an_unknowable_argument_occupies_a_path_operand`).

        Appended rather than substituted so the word keeps the shape the
        parser reasons about: `--color=$(echo /etc)` stays option-shaped and
        `./sub$ESC` keeps its relative-path prefix, so the parser classifies
        the same slot it would have classified for real. Position within the
        word is deliberately not modelled - the question is only whether the
        SLOT is a path operand, never where inside it the unknown content
        sits, so appending to `./a$ESC/b` is as informative as splicing."""
        return [
            argument.text if _is_fully_knowable(argument) else argument.text + marker
            for argument in self._arguments
        ]

    def first_shifting_position(self, scheme):
        """`scheme` is an `IndexScheme`. None means nothing in this
        invocation can shift anything."""
        n_options = sum(1 for argument in self._arguments if argument.text.startswith("-"))
        positional_seen = 0
        for argument in self._arguments:
            if argument.text.startswith("-"):
                continue
            if not argument.word_safe:
                return n_options + positional_seen if scheme is IndexScheme.COMBINED else positional_seen
            positional_seen += 1
        return None


def _is_fully_knowable(argument):
    return not argument.contains_substitution and not argument.referenced_variables
