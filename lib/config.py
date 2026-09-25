"""Config value object for the command-policy engine.

`Config.from_dict(cfg)` is the settled public entrypoint (leaf 20260914-213049)
every consumer calls. Leaf 20260914-213153 built parsing, validation, merge,
warnings and explain; leaf 20260914-213652 (this leaf) wires `decision_for`'s
real body - the uniform policy pipeline over the six Pass value objects in
`lib/*_policy.py`, sorted by `Pass` and returning the first objection's
decision, `allow` when none objects (see `pass_.py` and `policy.py`).

Construction path: `Config.defaults()` is the base layer. `Config.from_dict`
builds every nested value object from an already-parsed dict, validating the
one surviving decision knob and collecting warnings. `Config.merged_with`
composes two layers copy-on-write - each nested value object owns its own
composition rule (union for every collection, overlay-wins for the knob);
Config itself only concatenates warnings and decides the knob's overlay-wins
rule. The file loader (lib/config_loader.py) is pure I/O and carries none of
this - see its module docstring.
"""

from __future__ import annotations

from allowed_command import AllowedCommand
from blocked_commands_policy import BlockedCommandsPolicy
from command_substitution_policy import CommandSubstitutionPolicy
from escalation_policy import add_allow_policy_transform, bypass_chain_hint, bypass_transform
from layer_presence import LayerPresence
from name_collection import AllowedPathPrefixes, BlockedCommands, SensitiveVariables
from path_config import PathConfig
from path_resolution import PathResolutionContext
from path_permission import decision_for as path_permission_decision_for
from permission_decision import PermissionDecision
from redirect_path_validation_policy import RedirectPathValidationPolicy
from sensitive_path import SensitivePath
from sensitive_paths_policy import SensitivePathsPolicy
from sensitive_variables_policy import SensitiveVariablesPolicy
from statement import Statement
from warning_value import Warning

# AllowedCommandPolicy is imported lazily inside _policies() below - its own
# module imports `from config import ConfigError`, so importing it here at
# module level would be a circular import (config.py would not yet have
# finished defining ConfigError while still executing its own top-level
# imports).

COMMAND_SUBSTITUTION_RESPONSE_KNOB = "commandSubstitutionResponse"
VALID_COMMAND_SUBSTITUTION_RESPONSES = {"deny", "via-allowed-commands"}
DEFAULT_COMMAND_SUBSTITUTION_RESPONSE = "via-allowed-commands"
DEFAULT_MAX_NESTED_DEPTH = 10

# Static text, never config-derived (improvement-20260919-230721) - renders
# unconditionally so it reaches a user whose config is empty or absent, who
# faces the most denials and needs the hint most. Placed LAST in explain()
# (after commandSubstitutionResponse and any WARNINGS section) so it never
# collides with LayerPresence's own "no config file found" line, which
# renders FIRST for the opposite reason (it explains the empty sections
# beneath it).
_DECOMPOSITION_ADVISORY = (
    "RECOVERY TIP: a denial caused by an unreadable argument ($(...) or a variable) can often be decomposed into two "
    "auto-allowed commands instead of escalating - run the value-producing command first, read its output, confirm "
    "it is the value you expected, then re-issue the original command with that value written in literally.\n"
    "See command-policy:find-auto-allowed-command for how to recognise when this applies."
)


class ConfigError(Exception):
    """Raised for a config no author could have meant.

    Part of the settled entrypoint contract (leaf 20260914-213049) rather
    than of this leaf's own validation logic: this leaf's `Config.from_dict`
    does not raise it anywhere - out-of-range values for the surviving knob
    are recoverable (fall back + warn, see `warnings()`), and filter/parser
    shape validation belongs to leaf 20260914-213502, which constructs
    filters FROM `AllowedCommand`'s stored definitions. The class stays
    exported here because it is part of the entrypoint's public contract.
    """


class Config:
    def __init__(
        self,
        allowed_commands=(),
        blocked_commands=None,
        sensitive_variables=None,
        sensitive_paths=(),
        allowed_path_prefixes=None,
        path_config=None,
        command_substitution_response=DEFAULT_COMMAND_SUBSTITUTION_RESPONSE,
        command_substitution_response_explicit=False,
        warnings=(),
        source="config",
        layer_presence=None,
        path_resolution=None,
    ):
        self._allowed_commands = tuple(allowed_commands)
        self._blocked_commands = blocked_commands or BlockedCommands.from_entries(())
        self._sensitive_variables = sensitive_variables or SensitiveVariables.from_entries(())
        self._sensitive_paths = tuple(sensitive_paths)
        self._allowed_path_prefixes = allowed_path_prefixes or AllowedPathPrefixes.from_entries(())
        self._path_config = path_config or PathConfig.from_entries(())
        self._command_substitution_response = command_substitution_response
        self._command_substitution_response_explicit = command_substitution_response_explicit
        self._warnings = tuple(warnings)
        self._source = source
        self._layer_presence = layer_presence or LayerPresence.empty()
        self._path_resolution = path_resolution or PathResolutionContext.for_project()

    # -- construction ---------------------------------------------------

    @classmethod
    def defaults(cls, path_resolution=None):
        return cls(path_resolution=path_resolution)

    @classmethod
    def from_dict(cls, cfg, source="config", path_resolution=None):
        cfg = cfg or {}
        resolved_path_resolution = path_resolution or PathResolutionContext.for_project()

        response, response_explicit, response_warnings = _resolve_command_substitution_response(cfg, source)
        allowed_commands = tuple(
            AllowedCommand.from_entry(e, resolved_path_resolution, source) for e in cfg.get("allowedCommands") or ()
        )
        problem_warnings = _collect_allowed_command_problem_warnings(allowed_commands, source)

        return cls(
            allowed_commands=allowed_commands,
            blocked_commands=BlockedCommands.from_entries(cfg.get("blockedCommands")),
            sensitive_variables=SensitiveVariables.from_entries(cfg.get("sensitiveVariables")),
            sensitive_paths=tuple(SensitivePath.from_entry(e) for e in cfg.get("sensitivePaths") or ()),
            allowed_path_prefixes=AllowedPathPrefixes.from_entries(cfg.get("additionalAllowedPathPrefixes")),
            path_config=PathConfig.from_entries(cfg.get("allowedPaths")),
            command_substitution_response=response,
            command_substitution_response_explicit=response_explicit,
            warnings=response_warnings + problem_warnings,
            source=source,
            path_resolution=resolved_path_resolution,
        )

    # -- properties -------------------------------------------------------

    @property
    def allowed_commands(self):
        return self._allowed_commands

    @property
    def blocked_commands(self):
        return self._blocked_commands

    @property
    def sensitive_variables(self):
        return self._sensitive_variables

    @property
    def sensitive_paths(self):
        return self._sensitive_paths

    @property
    def allowed_path_prefixes(self):
        return self._allowed_path_prefixes

    @property
    def path_config(self):
        return self._path_config

    @property
    def command_substitution_response(self):
        return self._command_substitution_response

    # -- copy-on-write ----------------------------------------------------

    def _replace(self, **overrides):
        fields = dict(
            allowed_commands=self._allowed_commands,
            blocked_commands=self._blocked_commands,
            sensitive_variables=self._sensitive_variables,
            sensitive_paths=self._sensitive_paths,
            allowed_path_prefixes=self._allowed_path_prefixes,
            path_config=self._path_config,
            command_substitution_response=self._command_substitution_response,
            command_substitution_response_explicit=self._command_substitution_response_explicit,
            warnings=self._warnings,
            source=self._source,
            layer_presence=self._layer_presence,
            path_resolution=self._path_resolution,
        )
        fields.update(overrides)
        return Config(**fields)

    def with_allowed_commands(self, allowed_commands):
        return self._replace(allowed_commands=allowed_commands)

    def with_blocked_commands(self, blocked_commands):
        return self._replace(blocked_commands=blocked_commands)

    def with_sensitive_variables(self, sensitive_variables):
        return self._replace(sensitive_variables=sensitive_variables)

    def with_sensitive_paths(self, sensitive_paths):
        return self._replace(sensitive_paths=sensitive_paths)

    def with_allowed_path_prefixes(self, allowed_path_prefixes):
        return self._replace(allowed_path_prefixes=allowed_path_prefixes)

    def with_path_config(self, path_config):
        return self._replace(path_config=path_config)

    def with_command_substitution_response(self, response, explicit=True):
        return self._replace(
            command_substitution_response=response,
            command_substitution_response_explicit=explicit,
        )

    def with_layer_presence(self, layer_presence):
        return self._replace(layer_presence=layer_presence)

    def with_path_resolution(self, path_resolution):
        return self._replace(path_resolution=path_resolution)

    # -- merge --------------------------------------------------------------

    def merged_with(self, other):
        """Compose `other` on top of `self`, copy-on-write.

        Every collection unions; the surviving knob is overlay-wins, but only
        when the overlay actually configured it - an overlay that never
        mentions the knob must not silently reset an earlier layer's explicit
        choice back to the default.
        """
        response, response_explicit = self._merged_command_substitution_response(other)

        return self._replace(
            allowed_commands=self._allowed_commands + other._allowed_commands,
            blocked_commands=self._blocked_commands.union(other._blocked_commands),
            sensitive_variables=self._sensitive_variables.union(other._sensitive_variables),
            sensitive_paths=self._sensitive_paths + other._sensitive_paths,
            allowed_path_prefixes=self._allowed_path_prefixes.union(other._allowed_path_prefixes),
            path_config=self._path_config.union(other._path_config),
            command_substitution_response=response,
            command_substitution_response_explicit=response_explicit,
            warnings=self._warnings + other._warnings,
            layer_presence=self._layer_presence.union(other._layer_presence),
        )

    def _merged_command_substitution_response(self, other):
        if other._command_substitution_response_explicit:
            return other._command_substitution_response, True
        return self._command_substitution_response, self._command_substitution_response_explicit

    # -- reporting ------------------------------------------------------

    def warnings(self):
        return self._warnings

    def explain(self):
        sections = []
        layer_presence_section = self._layer_presence.explain()
        if layer_presence_section:
            sections.append(layer_presence_section)
        sections.append(self._explain_allowed_commands())
        sections.append(self._blocked_commands.explain())
        sections.append(self._sensitive_variables.explain())
        sections.append(self._explain_sensitive_paths())
        sections.append(self._allowed_path_prefixes.explain())
        sections.append(self._path_config.explain())
        sections.append(f"commandSubstitutionResponse: '{self._command_substitution_response}'")
        warnings_section = self._explain_warnings()
        if warnings_section:
            sections.append(warnings_section)
        sections.append(_DECOMPOSITION_ADVISORY)
        return "\n\n".join(sections)

    def _explain_allowed_commands(self):
        if not self._allowed_commands:
            return "No commands are auto-allowed; every command is denied with a hint."
        lines = ["AUTO-ALLOWED COMMANDS:"]
        lines.extend(entry.explain() for entry in self._allowed_commands)
        return "\n".join(lines)

    def _explain_sensitive_paths(self):
        if not self._sensitive_paths:
            return "sensitivePaths: (none configured)"
        lines = ["sensitivePaths:"]
        lines.extend(path.explain() for path in self._sensitive_paths)
        return "\n".join(lines)

    def _explain_warnings(self):
        if not self._warnings:
            return ""
        lines = ["WARNINGS:"]
        lines.extend(f"- {warning.message}" for warning in self._warnings)
        return "\n".join(lines)

    # -- decision pipeline (leaf 20260914-213652) ------------------------

    def decision_for(self, command, max_nested_depth=DEFAULT_MAX_NESTED_DEPTH):
        """The settled public entrypoint: `PermissionDecision` for `command`
        under this Config. Builds the Statement, applies the heredoc-as-
        literal normalisation ONCE up front (so it protects every pass, not
        only command-substitution detection - Flag List A4), then decides.

        `max_nested_depth` is the explicit, threaded depth guard for both
        recursion sources (the nestedCommand filter and the
        via-allowed-commands substitution check) - never hidden state, so a
        caller (a test) can pass a tiny value to trip the guard cheaply.

        The two escalation paths (leaf 20260915-010959) are RESULT
        TRANSFORMERS applied here, outside the pass pipeline itself - see
        escalation_policy.py's module docstring for why, and for the
        "sole invoked program" recognition rule that stops either wrapper
        from laundering a command merely sharing its line.
        """
        statement = _parse_and_normalize(command)
        if statement is None:
            return PermissionDecision.deny(f"could not parse command: {command!r}")

        add_allow = add_allow_policy_transform(statement)
        if add_allow is not None:
            return add_allow

        ordinary = self._decision_for_statement(statement, command, depth=0, max_nested_depth=max_nested_depth)

        bypass = bypass_transform(
            statement,
            ordinary,
            lambda text: self._decision_for_text(text, 0, max_nested_depth),
        )
        if bypass is not None:
            return bypass

        hinted = bypass_chain_hint(statement, ordinary)
        if hinted is not None:
            return hinted

        return ordinary

    def _decision_for_statement(self, statement, command_text, depth, max_nested_depth):
        """Every matching policy contributes its own reasons - not just the
        first by pass order - because a single command can legitimately
        carry more than one objection at once (a blocked command AND a
        sensitive path, say - see leaf 20260915-010959's Design Decisions,
        'The shape of a denial's reason'). Pass order still governs the
        reason list's ORDER (primary objection first); the decision itself
        is derived from whether the concatenated list is empty, never stored
        alongside it, so a decision/reason disagreement is unrepresentable.
        """
        policies = [policy.for_statement(statement) for policy in self._policies(command_text, depth, max_nested_depth)]
        objections = sorted((p for p in policies if p.matches()), key=lambda p: p.pass_)
        reasons = tuple(reason for policy in objections for reason in policy.decision().reason)
        if not reasons:
            return PermissionDecision.allow()
        return PermissionDecision.deny(reasons)

    def _policies(self, command_text, depth, max_nested_depth):
        from allowed_command_policy import AllowedCommandPolicy

        return [
            SensitivePathsPolicy(self._sensitive_paths, command_text),
            BlockedCommandsPolicy(self._blocked_commands),
            CommandSubstitutionPolicy(self._command_substitution_response == "deny"),
            SensitiveVariablesPolicy(self._sensitive_variables, command_text),
            RedirectPathValidationPolicy(self._path_resolution, self._allowed_path_prefixes.names),
            AllowedCommandPolicy(
                self._allowed_commands,
                self._path_resolution,
                self._allowed_path_prefixes.names,
                recurse_via_allowed_commands=(self._command_substitution_response == "via-allowed-commands"),
                evaluate_nested_text=lambda text, next_depth: self._decision_for_text(
                    text, next_depth, max_nested_depth
                ),
                depth=depth,
                default_max_depth=max_nested_depth,
            ),
        ]

    def _decision_for_text(self, text, depth, max_nested_depth):
        if depth >= max_nested_depth:
            return PermissionDecision.deny("nested-command recursion depth exceeded")
        statement = _parse_and_normalize(text)
        if statement is None:
            return PermissionDecision.deny(f"could not parse nested command: {text!r}")
        return self._decision_for_statement(statement, text, depth, max_nested_depth)

    def decision_for_path(self, tool_name, path):
        """The Read/Grep/Glob counterpart to `decision_for` (leaf
        20260914-213825's own addition - see path_config.py's module
        docstring): allowedPaths is its own decision domain, so this never
        denies, only allows or abstains (`passthrough`)."""
        return path_permission_decision_for(tool_name, path, self._path_config, self._path_resolution)


def _parse_and_normalize(command):
    """Statement.from_command(command), with the safe-heredoc-as-literal
    normalisation applied ONCE up front so every pass benefits (Flag List
    A4) - not only command-substitution detection. None on any shfmt
    failure (missing binary, non-zero exit, timeout, malformed JSON),
    mirroring Statement.from_command's own fail-open contract."""
    statement = Statement.from_command(command)
    if statement is None:
        return None
    return statement.with_heredoc_normalized_to_lit()


def _collect_allowed_command_problem_warnings(allowed_commands, source):
    """Every static PROBLEM each entry's own construction already found
    (`AllowedCommand.problems()` - an unrecognised filter/parser type, an
    uncompilable pattern, a retired StructuredParser key, an unresolved
    `provided` script, a malformed `programGlob`, or an
    `optionValue`/`nestedCommand` filter naming a capability its parser
    statically lacks), turned into layered `Warning`s so a config author
    sees them through `Config.warnings()`/`explain()`/SessionStart/the lint
    hook - replaces the old `_collect_allowed_command_filter_warnings`,
    which only re-derived the single uncompilable-pattern case by re-running
    `Filter.try_from_definition` here; every other defect surfaced only
    lazily, at decision time, for whichever program happened to be invoked.
    """
    return tuple(
        Warning.allowed_command_problem(layer=source, program=entry.program_label, problem=problem)
        for entry in allowed_commands
        for problem in entry.problems()
    )


def _resolve_command_substitution_response(cfg, source):
    explicit = COMMAND_SUBSTITUTION_RESPONSE_KNOB in cfg
    configured = cfg.get(COMMAND_SUBSTITUTION_RESPONSE_KNOB, DEFAULT_COMMAND_SUBSTITUTION_RESPONSE)

    if configured in VALID_COMMAND_SUBSTITUTION_RESPONSES:
        return configured, explicit, ()

    warning = Warning.invalid_knob_value(
        layer=source,
        knob=COMMAND_SUBSTITUTION_RESPONSE_KNOB,
        configured=configured,
        valid_values=VALID_COMMAND_SUBSTITUTION_RESPONSES,
        in_effect=DEFAULT_COMMAND_SUBSTITUTION_RESPONSE,
    )
    return DEFAULT_COMMAND_SUBSTITUTION_RESPONSE, explicit, (warning,)
