"""StructuredParser: DECLARED knowledge of a program's argument grammar.

Pure: parse(arguments) needs nothing but the PathResolutionContext injected
at construction.

PATH CANDIDACY DEFAULTS TO ACTIVE FOR EVERY SLOT (improvement-20260920-131722),
mirroring DefaultParser's total candidacy (improvement-20260919-112214) - only
an explicit `path: false` declaration rules a slot out. Before this, an
undeclared positional fell back to a "does this look path-shaped" guess
(`_detect_path_heuristic`) and an option's value was only ever a candidate
when the option was named in the old `pathOptions` key - both are the same
exemption DefaultParser lost, so attaching a structured parser was measurably
WEAKER than attaching no parser at all: `tool $(echo /etc/passwd)`,
`tool --colors=/etc/passwd` and `tool --colors /etc/passwd` all ALLOWed
against a `structured` parser declaring nothing, while the same commands
DENY with no parser at all. A config author who declares nothing now gets
maximum strictness; every relaxation is an explicit, auditable, falsifiable
statement about the program's real grammar (the same character
`hasNoPathParameters` has - a true claim, never a waiver).

This completes the ladder the decision model names: no parser means no
knowledge means everything is a candidate; a `structured` parser means
DECLARED knowledge, and a slot is ruled out exactly when the config says so;
a `provided`/`command` parser means CODE-level knowledge.

The four former parallel keys (`options`, `optionsWithArguments`,
`pathOptions`, `pathPositionals`) collapse into one per-slot declaration: an
`options` list of `{option, arguments, path}` records (`arguments` defaults
to `0`, `path` defaults to `true`; a bare string is shorthand for a valueless
flag) and a `positionals` list of `{index, path}` records. The three retired
keys raise `ConfigError` naming the replacement rather than being silently
ignored or reinterpreted - silently ignoring `optionsWithArguments` would
change TOKENIZATION (an option's value becomes a stray positional, shifting
every later index), and silently ignoring `pathOptions`/`pathPositionals`
would leave an author believing they had declared something.

`paths_for_validation` (the containment boundary) wants every candidate it
cannot rule out: every positional's value and every option's consumed
value(s), unless that slot is declared `path: false`, plus every option
TOKEN itself, declared or not - mirroring DefaultParser's uniform treatment
of every dash-word (harmless: a token resolves project-relative and stays
contained). `paths_for_filtering` feeds `PathsFilter`'s `exactly`
set-membership semantics, where a surplus entry is a WRONG MEMBER rather than
a spare check, so it deliberately does NOT follow the widening: it carries
only explicitly declared path slots (an option or positional whose `path` is
not `false`) plus the old shape heuristic over UNDECLARED positionals only.
Dropping the heuristic there entirely would fail open (a `paths` filter's
`exactly` set can no longer reject an in-project surplus path it never
listed), so it survives, scoped to that one field.

The candidate for a joined `--name=value` form is the VALUE alone, never the
whole word - resolving the whole word buries an absolute value under the
project root (`<project>/--colors=/etc/passwd`), where it reads as CONTAINED.
This tokenizer already splits `--name=value` this way; the fix is that the
value becomes a validation candidate by default rather than only when the
option was named in a `pathOptions` list.

Accepted residual, carried over deliberately: an attached short-option value
with no `=` (`-f/etc/passwd`) is still read as one project-relative word (the
tokenizer only splits the `--name=value` form). An entry needing `-f`
understood that way declares a `provided` parser instead.
"""

from __future__ import annotations

from config import ConfigError
from parsed_result import ParsedOption, ParsedPositional, ParsedResult

_RETIRED_KEYS = {
    "optionsWithArguments": "'options' (a list of {\"option\": ..., \"arguments\": N} records)",
    "pathOptions": "'options' (give the option's own record a \"path\" field)",
    "pathPositionals": "'positionals' (a list of {\"index\": ..., \"path\": ...} records)",
}


class OptionDeclaration:
    def __init__(self, arguments=0, path=True):
        self.arguments = arguments
        self.path = path


class PositionalDeclaration:
    def __init__(self, path=True):
        self.path = path


class StructuredParser:
    def __init__(self, options, positionals, double_dash_stops, path_resolution):
        self._options = options
        self._positionals = positionals
        self._double_dash_stops = double_dash_stops
        self._path_resolution = path_resolution

    @classmethod
    def from_definition(cls, definition, path_resolution):
        _reject_retired_keys(definition)
        return cls(
            options=_option_declarations_from(definition.get("options", [])),
            positionals=_positional_declarations_from(definition.get("positionals", [])),
            double_dash_stops=bool(definition.get("doubleDashStops", False)),
            path_resolution=path_resolution,
        )

    def consumes_value_for_option(self, option):
        """Whether this parser's own `options` declarations say `option`
        consumes one or more arguments - see DefaultParser.
        consumes_value_for_option for why this capability question needs an
        answer per parser type. A bare-flag declaration (`arguments` of `0`,
        the default) answers `False` just as an undeclared option does."""
        declaration = self._options.get(option)
        return declaration is not None and declaration.arguments > 0

    def parse(self, arguments):
        options = []
        positionals = []
        index = 0
        i = 0
        options_stopped = False

        while i < len(arguments):
            argument = arguments[i]

            if self._double_dash_stops and argument == "--" and not options_stopped:
                options_stopped = True
                i += 1
                continue

            if options_stopped or not argument.startswith("-"):
                positionals.append(ParsedPositional(index=index, value=argument))
                index += 1
                i += 1
                continue

            option_name = argument
            option_arguments = []

            if "=" in argument and argument.startswith("--"):
                option_name, _, value = argument.partition("=")
                option_arguments = [value]
            else:
                declaration = self._options.get(option_name)
                if declaration is not None:
                    for _ in range(declaration.arguments):
                        i += 1
                        if i < len(arguments):
                            option_arguments.append(arguments[i])

            options.append(ParsedOption(name=option_name, arguments=option_arguments))
            i += 1

        return ParsedResult(
            options=options,
            positionals=positionals,
            paths_for_validation=tuple(self._paths_for_validation(options, positionals)),
            paths_for_filtering=tuple(self._paths_for_filtering(options, positionals)),
        )

    def _paths_for_validation(self, options, positionals):
        """Every slot this parser cannot rule out, plus every option token
        itself - see the module docstring for why the token is unconditional
        while the consumed value(s) respect the slot's own `path` field."""
        candidates = []
        for option in options:
            candidates.append(self._path_resolution.absolute_path_of(option.name))
            if _is_ruled_out(self._options.get(option.name)):
                continue
            for value in option.arguments:
                if value:
                    candidates.append(self._path_resolution.absolute_path_of(value))

        for positional in positionals:
            if _is_ruled_out(self._positionals.get(positional.index)):
                continue
            if positional.value:
                candidates.append(self._path_resolution.absolute_path_of(positional.value))

        return candidates

    def _paths_for_filtering(self, options, positionals):
        """Precise, not conservative: only explicitly declared path slots,
        plus the shape heuristic over positionals nobody declared at all -
        see the module docstring for why this field never widens."""
        candidates = []
        heuristic_indices = set()

        for option in options:
            declaration = self._options.get(option.name)
            if declaration is not None and declaration.path:
                for value in option.arguments:
                    if value:
                        candidates.append(self._path_resolution.absolute_path_of(value))

        for positional in positionals:
            declaration = self._positionals.get(positional.index)
            if declaration is None:
                heuristic_indices.add(positional.index)
            elif declaration.path and positional.value:
                candidates.append(self._path_resolution.absolute_path_of(positional.value))

        for positional in positionals:
            if positional.index in heuristic_indices:
                detected = self._detect_path_heuristic(positional.value)
                if detected:
                    candidates.append(detected)

        return candidates

    def _detect_path_heuristic(self, value):
        if not value:
            return None
        if value.startswith("/") or value.startswith("~") or "/" in value or value.startswith("."):
            return self._path_resolution.absolute_path_of(value)
        if self._path_resolution.exists(value):
            return self._path_resolution.absolute_path_of(value)
        return None


def _is_ruled_out(declaration):
    """A slot is ruled out only by an explicit `path: false` declaration -
    an undeclared slot (`declaration is None`) is never ruled out, matching
    the secure default."""
    return declaration is not None and not declaration.path


def _reject_retired_keys(definition):
    for key, replacement in _RETIRED_KEYS.items():
        if key in definition:
            raise ConfigError(f"commandParser key {key!r} was retired; declare {replacement} instead")


def _option_declarations_from(options_config):
    declarations = {}
    for item in options_config:
        if isinstance(item, str):
            declarations[item] = OptionDeclaration(arguments=0, path=True)
        elif isinstance(item, dict) and item.get("option"):
            declarations[item["option"]] = OptionDeclaration(
                arguments=item.get("arguments", 0),
                path=item.get("path", True),
            )
    return declarations


def _positional_declarations_from(positionals_config):
    declarations = {}
    for item in positionals_config:
        if isinstance(item, dict) and "index" in item:
            declarations[item["index"]] = PositionalDeclaration(path=item.get("path", True))
    return declarations
