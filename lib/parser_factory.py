"""build_parser(definition, path_resolution): resolves an allowedCommands
entry's `commandParser` definition into a parser value object - moved out of
AllowedCommandPolicy's own `_build_parser` (leaf 20260914-213652) so parser
construction happens ONCE, at AllowedCommand construction time
(allowed_command.py), rather than being rebuilt - and re-raising - on every
decision.

Never raises: an unrecognised `type`, a retired StructuredParser key, or an
unresolvable `provided` script name all degrade to an `InvalidParser`
carrying human-readable `problems`, the parser-side counterpart to
filter.py's `InvalidFilter`. `StructuredParser.from_definition` itself still
raises `ConfigError` for a retired key (its own, lower-level unit contract,
covered by test_structured_parser.py) - this factory is what catches it so
the defect never escapes as far as `decision_for`.
"""

from __future__ import annotations

from command_parser import CommandParser
from config import ConfigError
from default_parser import DefaultParser
from provided_parser import ProvidedParser
from structured_parser import StructuredParser


class InvalidParser:
    """Stand-in for a `commandParser` this factory could not build. Always
    fails to interpret any invocation - mirroring ExternalParserFactory's
    own None-on-failure contract - so an entry using it can never vouch and
    instead reports `ParserCouldNotInterpretInvocation`. `problems` is a
    tuple of human-readable strings, surfaced through
    `AllowedCommand.problems()`."""

    def __init__(self, problems):
        self.problems = tuple(problems)

    def parse(self, arguments):
        return None


def build_parser(definition, path_resolution):
    if definition is None:
        return DefaultParser(path_resolution)

    parser_type = definition.get("type")
    if parser_type == "structured":
        return _build_structured(definition, path_resolution)
    if parser_type == "provided":
        return _build_provided(definition, path_resolution)
    if parser_type == "command":
        return CommandParser.from_definition(definition)

    return InvalidParser(
        (f"commandParser has no recognised 'type' ({parser_type!r}); there is no implicit default parser type",)
    )


def _build_structured(definition, path_resolution):
    try:
        return StructuredParser.from_definition(definition, path_resolution)
    except ConfigError as exc:
        return InvalidParser((str(exc),))


def _build_provided(definition, path_resolution):
    name = definition.get("name", "")
    parser = ProvidedParser.from_definition(definition, path_resolution)
    if not parser.command:
        return InvalidParser((f"provided parser {name!r} names no bundled script - no parsers/{name}.py exists",))
    return parser
