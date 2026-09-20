"""Pure translation from a shfmt-permissions.json dict to a command-policy.json
dict - no filesystem access; `bin/migrate-config` is the only I/O layer.

SEMANTIC, not textual: the four dead decision knobs are stripped and always
warned about, `commandSubstitutionResponse`'s two removed values collapse to
`deny`, and `propagate`/`allowedReadPaths` are structurally reshaped rather
than renamed. See improvement 20260915-011123's Proposed Approach for the
full translation table this module implements.
"""

from __future__ import annotations

from warning_value import Warning

DEAD_DECISION_KNOBS = (
    "defaultDecision",
    "sensitiveVariableResponse",
    "pathValidationResponse",
    "filterRejectionResponse",
)

_COMMAND_SUBSTITUTION_RESPONSE_MIGRATION = {
    "via-allowed-commands": "via-allowed-commands",
    "deny": "deny",
    "ask": "deny",
    "block": "deny",
}

_COPIED_UNCHANGED_TOP_LEVEL_KEYS = ("blockedCommands", "sensitiveVariables", "sensitivePaths")


class ConfigMigration:
    def __init__(self, new_config, warnings):
        self.new_config = new_config
        self.warnings = tuple(warnings)


def migrate_shfmt_permissions_config(old_cfg, source="config"):
    old_cfg = old_cfg or {}
    warnings = [Warning.dead_decision_knob_removed(source, knob) for knob in DEAD_DECISION_KNOBS]
    new_config = {}

    if "commandSubstitutionResponse" in old_cfg:
        new_config["commandSubstitutionResponse"] = _COMMAND_SUBSTITUTION_RESPONSE_MIGRATION.get(
            old_cfg["commandSubstitutionResponse"], "deny"
        )

    for key in _COPIED_UNCHANGED_TOP_LEVEL_KEYS:
        if key in old_cfg:
            new_config[key] = list(old_cfg[key])

    if "additionalAllowedPrefixes" in old_cfg:
        new_config["additionalAllowedPathPrefixes"] = list(old_cfg["additionalAllowedPrefixes"])

    allowed_commands, entry_warnings = _migrate_allowed_commands(old_cfg.get("allowedCommands") or (), source)
    warnings.extend(entry_warnings)
    if allowed_commands:
        new_config["allowedCommands"] = allowed_commands

    allowed_paths, read_paths_warning = _migrate_allowed_paths(old_cfg, source)
    if allowed_paths:
        new_config["allowedPaths"] = allowed_paths
    if read_paths_warning is not None:
        warnings.append(read_paths_warning)

    return ConfigMigration(new_config, warnings)


def _migrate_allowed_commands(entries, source):
    migrated = []
    warnings = []
    for entry in entries:
        if isinstance(entry, str):
            migrated.append(entry)
            continue
        new_entry, entry_warnings = _migrate_entry(entry, source)
        migrated.append(new_entry)
        warnings.extend(entry_warnings)
    return migrated, warnings


def _migrate_entry(entry, source):
    warnings = []
    new_entry = {}

    program = entry.get("program")
    if program is not None:
        new_entry["program"] = program

    plugin_program = entry.get("pluginProgram")
    if plugin_program is not None:
        new_entry["programGlob"] = dict(plugin_program)

    only_these_variables = entry.get("allowedVariables")
    if only_these_variables:
        new_entry["onlyTheseVariables"] = list(only_these_variables)

    if entry.get("pathValidation") is False:
        new_entry["hasNoPathParameters"] = True

    command_parser = entry.get("commandParser")
    if command_parser is not None:
        program_name = program or (plugin_program or {}).get("path") or "<unnamed entry>"
        new_entry["commandParser"], parser_warnings = _migrate_command_parser(command_parser, source, program_name)
        warnings.extend(parser_warnings)

    filters = list(entry.get("filters") or ())

    propagate = entry.get("propagate")
    if propagate is not None:
        filters.append(_nested_command_filter_for(propagate))
        program_name = program or (plugin_program or {}).get("path") or "<unnamed entry>"
        warnings.append(Warning.propagate_reshaped_to_nested_command(source, program_name))

    if filters:
        new_entry["filters"] = filters

    return new_entry, warnings


def _nested_command_filter_for(propagate):
    nested_filter = {"type": "nestedCommand"}
    max_depth = propagate.get("maxDepth") if isinstance(propagate, dict) else None
    if max_depth is not None:
        nested_filter["maxDepth"] = max_depth
    return nested_filter


def _migrate_command_parser(command_parser, source, program_name):
    if command_parser.get("type") != "structured":
        return dict(command_parser), []

    old_options_with_arguments = command_parser.get("options_with_arguments", [])
    old_path_options = set(command_parser.get("pathOptions", []))
    old_path_positionals = command_parser.get("pathPositionals", [])

    consuming_option_names, options = _reshaped_options(old_options_with_arguments, old_path_options)

    warnings = [Warning.structured_parser_defaults_to_path_active(source, program_name)]
    for option in sorted(old_path_options - consuming_option_names):
        warnings.append(Warning.structured_parser_inert_path_option(source, program_name, option))
        options.append({"option": option, "path": True})

    migrated = {"type": "structured"}
    if options:
        migrated["options"] = options
    if "double_dash_stops" in command_parser:
        migrated["doubleDashStops"] = command_parser["double_dash_stops"]
    if old_path_positionals:
        migrated["positionals"] = [{"index": index, "path": True} for index in old_path_positionals]

    return migrated, warnings


def _reshaped_options(old_options_with_arguments, old_path_options):
    """Reshapes `options_with_arguments` items into the new per-slot
    `options` schema, writing `path: true` EXPLICITLY for any option also
    named in the old `pathOptions` - preserving that author's original
    assertion as an assertion rather than dissolving it into the new
    default. Returns the reshaped list alongside the set of option names it
    covers, so the caller can detect a `pathOptions` member that names
    nothing here (see `Warning.structured_parser_inert_path_option`)."""
    options = []
    consuming_option_names = set()
    for item in old_options_with_arguments:
        if isinstance(item, str):
            option, arguments = item, 1
        else:
            option, arguments = item["option"], item.get("arguments", 1)
        consuming_option_names.add(option)
        declaration = {"option": option, "arguments": arguments}
        if option in old_path_options:
            declaration["path"] = True
        options.append(declaration)
    return consuming_option_names, options


def _migrate_allowed_paths(old_cfg, source):
    allowed_paths = list(old_cfg.get("allowedPaths") or ())
    read_paths = old_cfg.get("allowedReadPaths")
    warning = None
    if read_paths:
        allowed_paths = allowed_paths + [{"path": path, "tools": "read"} for path in read_paths]
        warning = Warning.allowed_read_paths_migrated(source)
    return allowed_paths, warning
