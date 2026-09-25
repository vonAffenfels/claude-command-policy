"""Describer: the edge-level collaborator that asks an external
(`command`/`provided`) parser script its own static capabilities via stdin
`{"describe": true}` - the describe-channel counterpart to
`ExternalParserFactory`'s `{"arguments": [...]}` channel
(external_parser_factory.py's module docstring).

Memoises per script path within its OWN instance, never at module or
process-wide scope (improvement 20260925-120037's Design Decisions,
'Describe runs only on reporting paths, with the describer passed in'): a
describer is constructed fresh, as a local, by each reporting entrypoint
(`command-policy-render-session-start`, `-render-subagent-start`,
`explain-policy`, `command-policy-lint-config-on-write`, `add-allow-policy`'s
ask path) and dropped at exit - so "per-process cache" means that
entrypoint's local object, never a mutable field shared across the
copy-on-write `Config` copies that pass through it.

A script that does not answer describe correctly - non-zero exit, timeout,
malformed JSON, or JSON missing/mis-shaping any of the three required keys -
is a breach of contract, reported as a PROBLEM by `Config.described_problems`
(never silently treated as "capability unknown", matching every other
external-parser failure mode's fail-closed posture in this package).
"""

from __future__ import annotations

import json
import subprocess

from parser_description import ParserDescription

DEFAULT_DESCRIBE_TIMEOUT_MS = 1000


class Describer:
    def __init__(self):
        self._memo = {}

    def describe(self, command, timeout_ms=DEFAULT_DESCRIBE_TIMEOUT_MS):
        """`command` is a script path (an `ExternalParserFactory`-style
        `parser.command` string), never a parser object - so a caller
        holding only the command string can reuse this too. Returns a
        `ParserDescription`, or `None` for an empty command, a subprocess
        failure, or any contract breach."""
        if not command:
            return None
        if command not in self._memo:
            self._memo[command] = self._describe_uncached(command, timeout_ms)
        return self._memo[command]

    def _describe_uncached(self, command, timeout_ms):
        try:
            result = subprocess.run(
                [command],
                input=json.dumps({"describe": True}),
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

        if result.returncode != 0:
            return None

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        return ParserDescription.from_raw(raw)
