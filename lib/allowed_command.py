"""AllowedCommand: one entry of an allowedCommands list.

Absorbs the bare-string-vs-object-entry normalisation that today's
shfmt-permissions duplicates at two call sites (`_check_command_allowed` and
`render_config._entry_as_dict`).

`from_entry` builds this entry's `Filter`/parser value objects ONCE, at
construction time, rather than storing `filters`/`commandParser` opaquely for
`AllowedCommandPolicy` to rebuild - and potentially raise on - every
decision. `filters`/`command_parser`/`program_glob` keep carrying the RAW
definitions the config author wrote (`__eq__`/`__hash__`/`explain` read
these, unchanged); `built_filters`/`parser` carry the constructed value
objects `AllowedCommandPolicy` actually evaluates against a command.

Every defect this construction can find - an unrecognised filter/parser
type, an uncompilable pattern, a retired StructuredParser key, an unresolved
`provided` script, a malformed `programGlob`, an `optionValue`/`nestedCommand`
filter naming a capability a PURE parser (default/structured) does not have -
becomes a PROBLEM rather than a raised `ConfigError`: a human-readable string
in `problems()`, never an exception. An entry with a problem simply never
vouches for any invocation (see allowed_command_policy.py); `Config.from_dict`
turns `problems()` into layered `Warning`s so a config author sees them
through the ordinary `explain()`/SessionStart/lint channel instead of a
crashed hook.

`programGlob` (renamed from the old engine's `pluginProgram`, improvement
20260915-011123) is a config-SHAPE-only field here: this entry stores and
validates the `marketplace`/`plugin`/`path` dict, but does not resolve
`CLAUDE_CODE_PLUGIN_CACHE_DIR` or match it against an invocation - that is
`AllowedCommandPolicy`'s matching-time obligation.
"""

from __future__ import annotations

from path_resolution import PathResolutionContext

# `filter` and `parser_factory` are imported LAZILY (inside the functions
# below) rather than at module level: both transitively import `config`
# (ConfigError), and `config.py` imports `AllowedCommand` at ITS module
# level - an eager import here would recreate the exact
# config -> allowed_command -> filter -> config cycle this module's OTHER
# lazy `from config import ConfigError` imports already exist to avoid.

_PROGRAM_GLOB_REQUIRED_FIELDS = ("marketplace", "plugin", "path")


class AllowedCommand:
    def __init__(
        self,
        program,
        filters=(),
        only_these_variables=(),
        has_no_path_parameters=False,
        command_parser=None,
        program_glob=None,
        source="config",
        built_filters=(),
        parser=None,
        static_problems=(),
        has_valid_program_glob=False,
    ):
        self.program = program
        self.filters = tuple(filters)
        self.only_these_variables = tuple(only_these_variables)
        self.has_no_path_parameters = has_no_path_parameters
        self.command_parser = command_parser
        self.program_glob = program_glob
        self.source = source
        self.built_filters = tuple(built_filters)
        self.parser = parser
        self.has_valid_program_glob = has_valid_program_glob
        self._static_problems = tuple(static_problems)

    @classmethod
    def from_entry(cls, entry, path_resolution=None, source="config"):
        from parser_factory import build_parser  # lazy: see the module-level comment on imports

        if isinstance(entry, str):
            entry = {"program": entry}

        resolution = path_resolution or PathResolutionContext.for_project()
        program = entry.get("program")
        program_glob = entry.get("programGlob")
        raw_filters = tuple(entry.get("filters") or ())
        command_parser_definition = entry.get("commandParser")

        program_glob_problems = _program_glob_problems(program, program_glob)
        parser = build_parser(command_parser_definition, resolution)
        built_filters, filter_problems = _build_filters(raw_filters, resolution, parser)

        return cls(
            program=program,
            filters=raw_filters,
            only_these_variables=entry.get("onlyTheseVariables") or (),
            has_no_path_parameters=bool(entry.get("hasNoPathParameters", False)),
            command_parser=command_parser_definition,
            program_glob=program_glob,
            source=source,
            built_filters=built_filters,
            parser=parser,
            static_problems=program_glob_problems + _parser_problems(parser) + filter_problems,
            has_valid_program_glob=program_glob is not None and not program_glob_problems,
        )

    def problems(self):
        """Every static defect found while building this entry - an
        unrecognised filter/parser type, an uncompilable pattern, a retired
        StructuredParser key, an unresolved `provided` script, a malformed
        `programGlob`, or an `optionValue`/`nestedCommand` filter naming a
        capability this entry's parser statically does not have. Empty for a
        well-formed entry. Never needs I/O - a DESCRIBED problem (one only an
        external parser's own describe call can answer) is a separate,
        later concern (`Config.described_problems`)."""
        return self._static_problems

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


def _build_filters(raw_filters, path_resolution, parser):
    """Builds every filter, then applies the cross-object capability checks
    (`optionValue` needs a value-consuming parser, `nestedCommand` needs a
    sub-command-publishing parser) that a Filter cannot judge alone - it
    never sees the entry's parser. A filter downgraded by either check
    becomes an `InvalidFilter` too, so decision-time evaluation needs no
    separate awareness of "cross-object" versus "own-definition" problems -
    every filter simply is or is not valid."""
    from filter import Filter, InvalidFilter  # lazy: see the module-level comment on imports

    built = []
    problems = []
    for definition in raw_filters:
        candidate = Filter.from_definition(definition, path_resolution)
        candidate, capability_problem = _apply_capability_check(candidate, definition, parser)
        built.append(candidate)
        if isinstance(candidate, InvalidFilter):
            problems.extend(candidate.problems)
        elif capability_problem is not None:
            problems.append(capability_problem)
    return tuple(built), tuple(problems)


def _apply_capability_check(candidate, definition, parser):
    from filter import InvalidFilter  # lazy: see the module-level comment on imports

    if isinstance(candidate, InvalidFilter):
        return candidate, None

    filter_type = definition.get("type")

    if filter_type == "optionValue":
        option = definition.get("option")
        if hasattr(parser, "consumes_value_for_option") and not parser.consumes_value_for_option(option):
            problem = (
                f"optionValue filter names option {option!r}, which this entry's parser never "
                "populates with a value"
            )
            return InvalidFilter((problem,)), problem

    if filter_type == "nestedCommand":
        if hasattr(parser, "publishes_nested_commands") and not parser.publishes_nested_commands():
            problem = (
                "a nestedCommand filter needs a parser that can publish sub-commands "
                "(commandParser type 'command' or 'provided'); the default/structured "
                "parser can never populate the nestedCommands channel"
            )
            return InvalidFilter((problem,)), problem

    return candidate, None


def _parser_problems(parser):
    from parser_factory import InvalidParser  # lazy: see the module-level comment on imports

    if isinstance(parser, InvalidParser):
        return parser.problems
    return ()


def _program_glob_problems(program, program_glob):
    """Mirrors the old engine's `pluginProgram` validation: for security,
    `path` must not start with `/` and none of `marketplace`/`plugin`/`path`
    may contain `..`. Returns problems rather than raising (improvement
    20260925-120037) - a malformed `programGlob` no longer aborts config
    load; the entry simply never matches any invocation (see
    `has_valid_program_glob`) and its problem surfaces through
    `Config.warnings()` instead."""
    if program_glob is None:
        return ()

    problems = []
    if program is not None:
        problems.append("an allowedCommands entry may not declare both 'program' and 'programGlob'")

    for field in _PROGRAM_GLOB_REQUIRED_FIELDS:
        if field not in program_glob:
            problems.append(f"programGlob is missing required field {field!r}: {program_glob!r}")

    path = program_glob.get("path")
    if isinstance(path, str) and path.startswith("/"):
        problems.append(f"programGlob.path must not start with '/': {path!r}")

    for field in _PROGRAM_GLOB_REQUIRED_FIELDS:
        value = program_glob.get(field)
        if isinstance(value, str) and ".." in value:
            problems.append(f"programGlob.{field} must not contain '..': {value!r}")

    return tuple(problems)


def _stable(value):
    """A hashable, order-independent stand-in for a dict, for equality/hash only."""
    if isinstance(value, dict):
        return tuple(sorted((k, _stable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_stable(v) for v in value)
    return value
