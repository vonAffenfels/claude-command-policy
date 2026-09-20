"""AllowedCommand: one entry of an allowedCommands list.

Absorbs the bare-string-vs-object-entry normalisation that today's
shfmt-permissions duplicates at two call sites (`_check_command_allowed` and
`render_config._entry_as_dict`). Filter/parser SHAPE is owned by leaf
20260914-213502 (Filter/Parser) - AllowedCommand stores `filters` and
`command_parser` opaquely, as whatever the config author wrote.

`programGlob` (renamed from the old engine's `pluginProgram`, improvement
20260915-011123) is a config-SHAPE-only field here: this entry stores and
validates the `marketplace`/`plugin`/`path` dict, but does not resolve
`CLAUDE_CODE_PLUGIN_CACHE_DIR` or match it against an invocation - that is
leaf 20260914-213652's `AllowedCommandPolicy` matching-time obligation (see
this leaf's Implementation Notes for the cross-leaf hand-back).
"""

from __future__ import annotations


class AllowedCommand:
    def __init__(
        self,
        program,
        filters=(),
        only_these_variables=(),
        has_no_path_parameters=False,
        command_parser=None,
        program_glob=None,
    ):
        self.program = program
        self.filters = tuple(filters)
        self.only_these_variables = tuple(only_these_variables)
        self.has_no_path_parameters = has_no_path_parameters
        self.command_parser = command_parser
        self.program_glob = program_glob

    @classmethod
    def from_entry(cls, entry):
        if isinstance(entry, str):
            return cls(program=entry)

        program_glob = entry.get("programGlob")
        if program_glob is not None:
            from config import ConfigError  # lazy: config.py imports AllowedCommand at module level

            _validate_program_glob(program_glob)
            if entry.get("program") is not None:
                raise ConfigError("an allowedCommands entry may not declare both 'program' and 'programGlob'")

        return cls(
            program=entry.get("program"),
            filters=entry.get("filters") or (),
            only_these_variables=entry.get("onlyTheseVariables") or (),
            has_no_path_parameters=bool(entry.get("hasNoPathParameters", False)),
            command_parser=entry.get("commandParser"),
            program_glob=program_glob,
        )

    @property
    def program_label(self):
        """A human-readable stand-in for `program` on a `programGlob` entry,
        which has no plain program name of its own - used everywhere a
        Reason or `explain()` needs something to print (`allowed_command_
        policy.py`'s reason construction sites included)."""
        if self.program is not None:
            return self.program
        if self.program_glob is not None:
            glob = self.program_glob
            return f"programGlob({glob.get('marketplace')}/{glob.get('plugin')}/.../{glob.get('path')})"
        return "<unresolved>"

    def explain(self):
        label = self.program_label
        if not self.filters:
            explanation = f"- {label}: no filters — permits every invocation."
        else:
            explanation = f"- {label}: must pass {len(self.filters)} filter(s)."
        if self.only_these_variables:
            explanation += f" (only variables permitted: {', '.join(self.only_these_variables)})"
        return explanation

    def _fields(self):
        return (
            self.program,
            self.filters,
            self.only_these_variables,
            self.has_no_path_parameters,
            _stable(self.command_parser),
            _stable(self.program_glob),
        )

    def __eq__(self, other):
        if not isinstance(other, AllowedCommand):
            return NotImplemented
        return self._fields() == other._fields()

    def __hash__(self):
        return hash(self._fields())

    def __repr__(self):
        return f"AllowedCommand(program={self.program!r}, filters={self.filters!r})"


def _validate_program_glob(program_glob):
    """Mirrors the old engine's `pluginProgram` validation: for security,
    `path` must not start with `/` and none of `marketplace`/`plugin`/`path`
    may contain `..`. Completeness is checked FIRST - all three keys must be
    present - so an incomplete dict fails loudly and early here rather than
    raising an uncaught `KeyError` at MATCH time inside
    `_program_glob_pattern` (`allowed_command_policy.py`), which has no
    business re-validating what construction should have already caught."""
    from config import ConfigError  # lazy: config.py imports AllowedCommand at module level

    for field in ("marketplace", "plugin", "path"):
        if field not in program_glob:
            raise ConfigError(f"programGlob is missing required field {field!r}: {program_glob!r}")

    path = program_glob["path"]
    if path.startswith("/"):
        raise ConfigError(f"programGlob.path must not start with '/': {path!r}")
    for field in ("marketplace", "plugin", "path"):
        value = program_glob[field]
        if ".." in value:
            raise ConfigError(f"programGlob.{field} must not contain '..': {value!r}")


def _stable(value):
    """A hashable, order-independent stand-in for a dict, for equality/hash only."""
    if isinstance(value, dict):
        return tuple(sorted((k, _stable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_stable(v) for v in value)
    return value
