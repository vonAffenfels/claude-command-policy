"""ExternalParserFactory: the edge-level collaborator that performs the
actual subprocess call for CommandParser/ProvidedParser.

This is the ONLY place subprocess.run appears among this leaf's value
objects - CommandParser/ProvidedParser are pure config plus interpret(raw)
and never call it themselves. Every failure mode (non-zero exit, timeout,
malformed JSON, missing or non-executable script, empty command path)
collapses to None; the pipeline leaf (20260914-213652) turns a None into the
constant deny+hint outcome - there is no configurable fallback any more.
"""

from __future__ import annotations

import json
import subprocess


class ExternalParserFactory:
    def raw_output_for(self, parser, arguments):
        if not parser.command:
            return None

        try:
            result = subprocess.run(
                [parser.command],
                input=json.dumps({"arguments": list(arguments)}),
                capture_output=True,
                text=True,
                timeout=parser.timeout_ms / 1000.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

        if result.returncode != 0:
            return None

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
