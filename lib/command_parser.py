"""CommandParser: pure config plus interpret(raw_output) -> ParsedResult.

No subprocess call lives here - ExternalParserFactory performs the actual
external execution and hands this parser its raw, already-JSON-decoded
output. `fallback` is GONE from the schema: deny+hint is a constant the
pipeline applies whenever the factory yields None, so there is nothing left
for this parser to read a fallback choice from.
"""

from __future__ import annotations

from parsed_result import NestedCommand, ParsedOption, ParsedPositional, ParsedResult

DEFAULT_TIMEOUT_MS = 1000


class CommandParser:
    def __init__(self, command, timeout_ms=DEFAULT_TIMEOUT_MS):
        self.command = command
        self.timeout_ms = timeout_ms

    @classmethod
    def from_definition(cls, definition):
        return cls(
            command=definition.get("command", ""),
            timeout_ms=definition.get("timeout_ms", DEFAULT_TIMEOUT_MS),
        )

    def interpret(self, raw_output):
        options = [
            ParsedOption(name=option["name"], arguments=option.get("arguments", []))
            for option in raw_output.get("options", [])
        ]
        positionals = [
            ParsedPositional(index=positional["index"], value=positional["value"])
            for positional in raw_output.get("positionals", [])
        ]
        subcommand = None
        if raw_output.get("subcommand"):
            subcommand = self.interpret(raw_output["subcommand"])
        paths = tuple(raw_output.get("paths", []))
        nested_commands = tuple(
            NestedCommand(text=entry.get("text", ""), shape=entry.get("shape", "shell"))
            for entry in raw_output.get("nestedCommands", [])
        )

        return ParsedResult(
            options=options,
            positionals=positionals,
            subcommand=subcommand,
            named=raw_output.get("named", {}),
            paths_for_validation=paths,
            paths_for_filtering=paths,
            nested_commands=nested_commands,
        )
