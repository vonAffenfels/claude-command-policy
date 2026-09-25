"""described_problems_for_entry(entry, describer): every PROBLEM only a
parser's own describe response can answer for ONE `AllowedCommand` - shared
by `Config.described_problems` (every entry in a merged config) and
`escalation_policy.add_allow_policy_transform` (one proposed entry, checked
BEFORE asking - improvement 20260925-120037's 'refuse before asking' success
criterion). A neutral module, imported by both, so neither importer creates
a cycle with the other (`config.py` already imports `escalation_policy.py`
at module level).

Static problems (an unrecognised type, a pure-parser capability mismatch,
...) are `AllowedCommand.problems()`'s own job - this module covers only
what needs the describe subprocess: a `command`/`provided` parser breaching
the describe contract, a `nestedCommand` filter beside a parser whose
description says it never publishes sub-commands, or an
`optionValue`/`namedValue` filter naming a capability the description never
lists.
"""

from __future__ import annotations


def described_problems_for_entry(entry, describer):
    """Empty for a pure parser (`DefaultParser`/`StructuredParser`, or an
    already-invalid `InvalidParser` stand-in - both expose `.parse()`, the
    same duck-typed pure-vs-external signal `allowed_command_policy.py`'s
    own dispatch uses) - only a real external (`command`/`provided`) parser
    needs its own describe response consulted."""
    parser = entry.parser
    if hasattr(parser, "parse"):
        return ()

    command = getattr(parser, "command", None)
    description = describer.describe(command) if command else None
    if description is None:
        return (
            f"parser script {command!r} did not answer the describe protocol correctly "
            "(non-zero exit, timeout, malformed JSON, or a response missing/mis-shaping one "
            "of its required keys)",
        )

    return tuple(
        problem
        for definition in entry.filters
        for problem in (_described_filter_problem(definition, description),)
        if problem is not None
    )


def _described_filter_problem(definition, description):
    filter_type = definition.get("type")

    if filter_type == "nestedCommand" and not description.publishes_nested_commands:
        return (
            "a nestedCommand filter needs a parser that can publish sub-commands, but this "
            "parser's own describe response says it never does"
        )

    if filter_type == "optionValue":
        option = definition.get("option")
        if option not in description.options_with_values:
            return (
                f"optionValue filter names option {option!r}, which this parser's own describe "
                "response never lists as a value it publishes"
            )

    if filter_type == "namedValue":
        name = definition.get("name")
        if name not in description.named_values:
            return (
                f"namedValue filter names {name!r}, which this parser's own describe response "
                "never lists as a value it publishes"
            )

    return None
