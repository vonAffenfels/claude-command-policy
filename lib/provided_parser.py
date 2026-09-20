"""ProvidedParser: resolves a bundled reference parser script by name.

Config: {"name": "git", "timeout_ms": 1000} -> resolves to
parsers/git.py. Pure: it never calls subprocess
itself - it delegates interpretation to an internal CommandParser, exactly
like the pipeline would delegate to any other Parser value object.

Whether the named script exists is checked through the injected
PathResolutionContext, same as DefaultParser/StructuredParser/PathsFilter -
no Parser value object reads the real filesystem directly.
"""

from __future__ import annotations

from pathlib import Path

from command_parser import CommandParser, DEFAULT_TIMEOUT_MS

PARSERS_DIR = Path(__file__).resolve().parent.parent / "parsers"


class ProvidedParser:
    def __init__(self, name, path_resolution, timeout_ms=DEFAULT_TIMEOUT_MS):
        self.name = name
        self.timeout_ms = timeout_ms
        self._command_parser = CommandParser(
            command=self._resolve_command(path_resolution), timeout_ms=timeout_ms
        )

    @classmethod
    def from_definition(cls, definition, path_resolution):
        return cls(
            name=definition.get("name", ""),
            path_resolution=path_resolution,
            timeout_ms=definition.get("timeout_ms", DEFAULT_TIMEOUT_MS),
        )

    def _resolve_command(self, path_resolution):
        script_path = str(PARSERS_DIR / f"{self.name}.py")
        return script_path if path_resolution.exists(script_path) else ""

    @property
    def command(self):
        return self._command_parser.command

    def interpret(self, raw_output):
        return self._command_parser.interpret(raw_output)
