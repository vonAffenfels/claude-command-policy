"""ParserDescription: an external/bundled parser's own static capabilities,
answered via the describe protocol (stdin `{"describe": true}`) - see
describer.py's module docstring for the edge-level collaborator that asks
for one.

Three fields, matching the three questions a "described problem" needs
answered (config.py's `described_problems`): whether the parser can ever
populate the `nestedCommands` channel, which `named` keys it may publish,
and which options it ever hands a value to.
"""

from __future__ import annotations


class ParserDescription:
    def __init__(self, publishes_nested_commands, named_values, options_with_values):
        self.publishes_nested_commands = publishes_nested_commands
        self.named_values = tuple(named_values)
        self.options_with_values = tuple(options_with_values)

    @classmethod
    def from_raw(cls, raw):
        """`None` when `raw` breaches the describe contract: not an object,
        or any of the three required keys missing or mis-shaped. A script
        that does not answer describe correctly is a PROBLEM - the caller
        (`Describer`) is what turns a `None` here into that reported
        problem; this class only judges the SHAPE of what came back."""
        if not isinstance(raw, dict):
            return None
        if not isinstance(raw.get("publishesNestedCommands"), bool):
            return None

        named_values = raw.get("namedValues")
        if not _is_list_of_str(named_values):
            return None

        options_with_values = raw.get("optionsWithValues")
        if not _is_list_of_str(options_with_values):
            return None

        return cls(raw["publishesNestedCommands"], named_values, options_with_values)

    def __eq__(self, other):
        if not isinstance(other, ParserDescription):
            return NotImplemented
        return (
            self.publishes_nested_commands == other.publishes_nested_commands
            and self.named_values == other.named_values
            and self.options_with_values == other.options_with_values
        )

    def __repr__(self):
        return (
            f"ParserDescription(publishes_nested_commands={self.publishes_nested_commands!r}, "
            f"named_values={self.named_values!r}, options_with_values={self.options_with_values!r})"
        )


def _is_list_of_str(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
