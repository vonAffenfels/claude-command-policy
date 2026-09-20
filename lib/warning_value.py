"""A structured Warning value emitted by Config construction.

Every consumer (SessionStart renders plain text, SubagentStart wraps a JSON
envelope, the write-linter reports inline) needs different formatting, so a
Warning carries its facts as fields (layer, kind, the specific details) rather
than only a pre-formatted string. `.message` is a ready-to-print rendering,
kept alongside the fields for the common case of a consumer that just wants
text.
"""

from __future__ import annotations


class Warning:
    def __init__(self, layer, kind, message, **details):
        self.layer = layer
        self.kind = kind
        self.message = message
        self._details = details

    def __getattr__(self, name):
        try:
            return self._details[name]
        except KeyError:
            raise AttributeError(name) from None

    def __eq__(self, other):
        if not isinstance(other, Warning):
            return NotImplemented
        return (
            self.layer == other.layer
            and self.kind == other.kind
            and self.message == other.message
            and self._details == other._details
        )

    def __repr__(self):
        return f"Warning(layer={self.layer!r}, kind={self.kind!r}, message={self.message!r})"

    @classmethod
    def invalid_knob_value(cls, layer, knob, configured, valid_values, in_effect):
        valid_list = ", ".join(f"'{v}'" for v in sorted(valid_values))
        message = (
            f"{layer} config set '{knob}' to '{configured}', which is not a valid value "
            f"(valid: {valid_list}). '{in_effect}' is in effect instead."
        )
        return cls(
            layer,
            "invalid_knob_value",
            message,
            knob=knob,
            configured=configured,
            valid_values=set(valid_values),
            in_effect=in_effect,
        )

    @classmethod
    def unparseable_config_file(cls, layer, path):
        message = f"{layer} config file at {path} could not be parsed as JSON and was ignored."
        return cls(layer, "unparseable_config_file", message, path=path)

    @classmethod
    def uncompilable_filter_pattern(cls, layer, program, filter_type, pattern):
        message = (
            f"{layer} config's '{program}' entry has a {filter_type} filter whose pattern "
            f"{pattern!r} does not compile. This filter now always fails closed, so the "
            "entry can never vouch through it."
        )
        return cls(
            layer,
            "uncompilable_filter_pattern",
            message,
            program=program,
            filter_type=filter_type,
            pattern=pattern,
        )

    @classmethod
    def dead_decision_knob_removed(cls, layer, knob):
        """Emitted unconditionally by `config_migration.py` for each of the
        four dead decision knobs, regardless of whether the source config set
        it - the user is losing that behaviour either way (improvement
        20260915-011123)."""
        message = (
            f"'{knob}' no longer exists in command-policy. Deny-by-default replaces it, and it is "
            "materially STRICTER than the old default (defaultDecision: 'passthrough'): anything not "
            "explicitly auto-allowed is now denied with a hint, instead of being silently passed "
            "through to Claude Code's own permission rules. Review your allowedCommands after migrating."
        )
        return cls(layer, "dead_decision_knob_removed", message, key=knob)

    @classmethod
    def propagate_reshaped_to_nested_command(cls, layer, program):
        """Emitted per migrated `propagate` entry - the reshape into a plain
        `nestedCommand` filter drops the old `namedValue` selector entirely,
        since the new engine reads whatever the entry's own commandParser
        publishes on its `nestedCommands` channel instead."""
        message = (
            f"'{program}' entry's propagate was reshaped into an ordinary nestedCommand filter. Its "
            "old namedValue selector no longer applies - the new engine reads whatever the entry's "
            "commandParser publishes on its own nestedCommands channel. Verify that parser actually "
            "publishes sub-commands there (the bundled nix-shell/nix/timeout reference parsers do not "
            "yet), or this entry will now deny the wrapped command instead of propagating to it."
        )
        return cls(layer, "propagate_reshaped_to_nested_command", message, key="propagate", program=program)

    @classmethod
    def structured_parser_defaults_to_path_active(cls, layer, program):
        """Emitted unconditionally by `config_migration.py` for EVERY
        migrated `structured` commandParser, regardless of its content - the
        same posture `dead_decision_knob_removed` takes, and for the same
        reason: the migrated config is materially STRICTER than its source.
        A slot the old engine guessed was not a path (or never named in
        `pathOptions`/`pathPositionals` at all) is now a path candidate by
        default (improvement-20260920-131722); the fix is to declare
        `path: false` on the slots that genuinely are not paths."""
        message = (
            f"'{program}' entry's structured commandParser now treats every positional and option value as a "
            "path candidate by default - only an explicit 'path: false' on a slot's own declaration rules it out. "
            "Slots the old engine guessed were not paths (or that were never named in 'pathOptions'/"
            "'pathPositionals' at all) may now cause commands to DENY that previously allowed. Review this entry's "
            "'options'/'positionals' declarations and add 'path: false' to any slot that genuinely never carries a "
            "path."
        )
        return cls(layer, "structured_parser_defaults_to_path_active", message, key="commandParser", program=program)

    @classmethod
    def structured_parser_inert_path_option(cls, layer, program, option):
        """Emitted per `pathOptions` member absent from `options_with_
        arguments` in the OLD config - that combination contributed NOTHING
        under the old engine (the value parsed as a stray positional, and
        the option's own `arguments` list stayed empty), so it is a
        declaration the old author believed in and never got. The migration
        emits the option's new declaration without inventing an `arguments`
        count the source config never asserted."""
        message = (
            f"'{program}' entry's structured commandParser declared '{option}' in 'pathOptions', but it was never "
            "in 'options_with_arguments' - under the old engine this consumed no value at all, so the declaration "
            "was already inert. Migrated as a valueless-flag declaration with 'path: true'; if this option really "
            "does take a path argument, add an 'arguments' count to its migrated entry."
        )
        return cls(
            layer, "structured_parser_inert_path_option", message, key="pathOptions", program=program, option=option
        )

    @classmethod
    def allowed_read_paths_migrated(cls, layer):
        """Emitted once when the deprecated `allowedReadPaths` key is present
        - converted into equivalent `allowedPaths` entries and merged with
        any pre-existing ones."""
        message = (
            "'allowedReadPaths' (deprecated) was converted into equivalent allowedPaths entries "
            "(tools: 'read') and merged with any existing allowedPaths."
        )
        return cls(layer, "allowed_read_paths_migrated", message, key="allowedReadPaths")
