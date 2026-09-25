"""DefaultParser: the dash-prefixed-is-an-option heuristic parser.

Pure: parse(arguments) needs nothing but the PathResolutionContext injected
at construction - no ambient os.path.exists()/abspath()/expanduser() read
lives here any more (contrast with today's DefaultParser._detect_paths).

PATH CANDIDACY IS TOTAL, AND THAT IS THE POINT (improvement-20260919-112214).
This parser knows NOTHING about any program's argument grammar, so it can
never rule an argument OUT as a path operand. `paths_for_validation`
therefore carries EVERY argument - options included - rather than only the
ones a shape heuristic happens to recognise. No knowledge means no
exemption: if the engine cannot rule out that an argument is a path, it IS
a path candidate.

What that closes, measured rather than reasoned: with candidacy restricted
to positionals that LOOK path-shaped, `ls --color=/etc` allowed outright
(an option-shaped word never reached detection at all), and one allow-listed
string-producing program was enough to hand any path-taking entry an
arbitrary absolute path - `ls $(echo /etc)`, `cat $(echo ~/.ssh/id_rsa)`,
`rg -f $(echo /etc/passwd) pattern` all allowed. Both holes are the same
mistake: treating "this argument does not look like a path" as knowledge.

`paths_for_filtering` deliberately does NOT follow: it feeds `PathsFilter`'s
`exactly` set-membership semantics (paths_filter.py), where a non-path
argument is not a conservative extra candidate but a wrong member that would
fail the filter. This is exactly the per-consumer divergence ParsedResult
split the two fields for (see parsed_result.py's module docstring).

Accepted residual, recorded rather than guessed at: an attached short-option
value (`-f/etc/passwd`, no `=`) is resolved as one whole word and so reads as
project-relative. Splitting it would need an option vocabulary this parser by
definition does not have; an entry that needs `-f` understood declares a
parser that understands it.
"""

from __future__ import annotations

from parsed_result import ParsedOption, ParsedPositional, ParsedResult


class DefaultParser:
    def __init__(self, path_resolution):
        self._path_resolution = path_resolution

    @classmethod
    def from_definition(cls, definition, path_resolution):
        return cls(path_resolution)

    def consumes_value_for_option(self, option):
        """The default parser has no configured option vocabulary at all -
        it never assigns an argument to an option (see parse() below), so it
        can never consume a value for any option name. Used by
        allowed_command_policy.py's A6 validation: an `optionValue` filter
        naming an option this parser could never populate is a config error,
        not a silently-inert filter."""
        return False

    def publishes_nested_commands(self):
        """The default parser has no sub-command channel at all - it never
        populates `ParsedResult.nested_commands` (see parse() below), so a
        `nestedCommand` filter beside it can never have anything to check.
        Used by allowed_command.py's cross-object capability check: a
        `nestedCommand` filter needs a parser that can publish sub-commands,
        which is knowable statically for every PURE parser (this one and
        StructuredParser) - see ProvidedParser/CommandParser, where the
        answer is dynamic and left to the describe protocol instead."""
        return False

    def parse(self, arguments):
        options = []
        positionals = []
        index = 0

        for argument in arguments:
            if argument.startswith("-"):
                options.append(ParsedOption(name=argument))
            else:
                positionals.append(ParsedPositional(index=index, value=argument))
                index += 1

        return ParsedResult(
            options=options,
            positionals=positionals,
            paths_for_validation=tuple(self._every_argument_as_a_path_candidate(arguments)),
            paths_for_filtering=tuple(self._detect_paths(p.value for p in positionals)),
        )

    def _every_argument_as_a_path_candidate(self, arguments):
        """An empty argument is the one thing this parser CAN rule out - no
        file is named by the empty string - so it contributes no candidate.
        Every other argument does, whatever its shape."""
        candidates = []
        for argument in arguments:
            operand = _path_operand_of(argument)
            if not operand:
                continue
            candidates.append(self._path_resolution.absolute_path_of(operand))
        return candidates

    def _detect_paths(self, values):
        paths = []
        for value in values:
            if not value:
                continue
            if value.startswith("/") or value.startswith("~") or "/" in value or value.startswith("."):
                paths.append(self._path_resolution.absolute_path_of(value))
            elif self._path_resolution.exists(value):
                paths.append(self._path_resolution.absolute_path_of(value))
        return paths


def _path_operand_of(argument):
    """The part of `argument` that could name a path. For an option-shaped
    `--name=value` word that is `value` alone: the option NAME is never a
    path operand, and resolving the whole word instead would bury an
    absolute `value` under the project root and read as contained
    (`--color=/etc` resolving to `<project>/--color=/etc`), which is how
    the literal form of this hole stayed open. Splitting on `=` is the same
    rule StructuredParser already applies to a `--name=value` word."""
    if argument.startswith("-") and "=" in argument:
        return argument.partition("=")[2]
    return argument
