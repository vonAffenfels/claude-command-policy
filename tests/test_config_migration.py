"""Unit tests for the pure shfmt-permissions -> command-policy translation.

No filesystem access here - `bin/migrate-config` (tested via
test_consumer_entrypoints.py) is the only I/O layer. `assert_config_is_reachable`
guards every produced `new_config` so a test never asserts a shape the real
`Config.from_dict` would itself warn about or reject.
"""

from config_migration import migrate_shfmt_permissions_config


def test_an_empty_source_config_still_warns_about_all_four_dead_knobs(assert_migration_warns_about):
    result = migrate_shfmt_permissions_config({})

    for knob in (
        "defaultDecision",
        "sensitiveVariableResponse",
        "pathValidationResponse",
        "filterRejectionResponse",
    ):
        assert_migration_warns_about(result, knob)


def test_dead_knobs_still_warn_even_when_the_source_config_sets_them(assert_migration_warns_about):
    result = migrate_shfmt_permissions_config(
        {
            "defaultDecision": "ask",
            "sensitiveVariableResponse": "block",
            "pathValidationResponse": "deny",
            "filterRejectionResponse": "deny",
        }
    )

    for knob in (
        "defaultDecision",
        "sensitiveVariableResponse",
        "pathValidationResponse",
        "filterRejectionResponse",
    ):
        assert_migration_warns_about(result, knob)


def test_the_four_dead_knobs_never_appear_in_the_migrated_config():
    result = migrate_shfmt_permissions_config(
        {
            "defaultDecision": "ask",
            "sensitiveVariableResponse": "block",
            "pathValidationResponse": "deny",
            "filterRejectionResponse": "deny",
        }
    )

    for knob in (
        "defaultDecision",
        "sensitiveVariableResponse",
        "pathValidationResponse",
        "filterRejectionResponse",
    ):
        assert knob not in result.new_config


def test_via_allowed_commands_command_substitution_response_survives_unchanged(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config({"commandSubstitutionResponse": "via-allowed-commands"})

    assert result.new_config["commandSubstitutionResponse"] == "via-allowed-commands"
    assert_config_is_reachable(result.new_config)


def test_ask_command_substitution_response_collapses_to_deny(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config({"commandSubstitutionResponse": "ask"})

    assert result.new_config["commandSubstitutionResponse"] == "deny"
    assert_config_is_reachable(result.new_config)


def test_block_command_substitution_response_collapses_to_deny(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config({"commandSubstitutionResponse": "block"})

    assert result.new_config["commandSubstitutionResponse"] == "deny"
    assert_config_is_reachable(result.new_config)


def test_an_unconfigured_command_substitution_response_is_omitted_from_the_migrated_config():
    result = migrate_shfmt_permissions_config({})

    assert "commandSubstitutionResponse" not in result.new_config


def test_allowed_variables_renames_to_only_these_variables(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {"allowedCommands": [{"program": "touch", "allowedVariables": ["SESSION_ID"]}]}
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["onlyTheseVariables"] == ["SESSION_ID"]
    assert "allowedVariables" not in entry
    assert_config_is_reachable(result.new_config)


def test_additional_allowed_prefixes_renames_to_additional_allowed_path_prefixes(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config({"additionalAllowedPrefixes": ["/shared"]})

    assert result.new_config["additionalAllowedPathPrefixes"] == ["/shared"]
    assert "additionalAllowedPrefixes" not in result.new_config
    assert_config_is_reachable(result.new_config)


def test_plugin_program_renames_to_program_glob(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {
            "allowedCommands": [
                {
                    "pluginProgram": {"marketplace": "m", "plugin": "p", "path": "bin/foo"},
                }
            ]
        }
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["programGlob"] == {"marketplace": "m", "plugin": "p", "path": "bin/foo"}
    assert "pluginProgram" not in entry
    assert_config_is_reachable(result.new_config)


def test_a_bare_string_allowed_command_is_unchanged():
    result = migrate_shfmt_permissions_config({"allowedCommands": ["echo"]})

    assert result.new_config["allowedCommands"] == ["echo"]


def test_path_validation_false_migrates_to_has_no_path_parameters_true(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {"allowedCommands": [{"program": "curl", "pathValidation": False}]}
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["hasNoPathParameters"] is True
    assert "pathValidation" not in entry
    assert_config_is_reachable(result.new_config)


def test_path_validation_true_is_dropped_rather_than_migrated(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {"allowedCommands": [{"program": "curl", "pathValidation": True}]}
    )

    [entry] = result.new_config["allowedCommands"]
    assert "hasNoPathParameters" not in entry
    assert "pathValidation" not in entry
    assert_config_is_reachable(result.new_config)


def test_propagate_string_form_becomes_an_appended_nested_command_filter(
    assert_config_is_reachable, assert_migration_warns_about
):
    result = migrate_shfmt_permissions_config(
        {
            "allowedCommands": [
                {
                    "program": "nix-shell",
                    "commandParser": {"type": "provided", "name": "nix-shell"},
                    "propagate": "command",
                }
            ]
        }
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["filters"] == [{"type": "nestedCommand"}]
    assert "propagate" not in entry
    assert_migration_warns_about(result, "propagate")
    assert_config_is_reachable(result.new_config)


def test_propagate_object_form_carries_its_max_depth_and_drops_named_value(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {
            "allowedCommands": [
                {
                    "program": "nix-shell",
                    "commandParser": {"type": "provided", "name": "nix-shell"},
                    "propagate": {"namedValue": "command", "maxDepth": 3},
                }
            ]
        }
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["filters"] == [{"type": "nestedCommand", "maxDepth": 3}]
    assert_config_is_reachable(result.new_config)


def test_propagate_composes_after_the_entrys_own_ordinary_filters(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {
            "allowedCommands": [
                {
                    "program": "nix-shell",
                    "commandParser": {"type": "provided", "name": "nix-shell"},
                    "filters": [{"type": "namedValue", "name": "pure", "pattern": "^true$", "action": "required"}],
                    "propagate": "command",
                }
            ]
        }
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["filters"] == [
        {"type": "namedValue", "name": "pure", "pattern": "^true$", "action": "required"},
        {"type": "nestedCommand"},
    ]
    assert_config_is_reachable(result.new_config)


def test_allowed_read_paths_migrates_into_equivalent_allowed_paths_entries(
    assert_config_is_reachable, assert_migration_warns_about
):
    result = migrate_shfmt_permissions_config({"allowedReadPaths": ["/path/a", "/path/b"]})

    assert result.new_config["allowedPaths"] == [
        {"path": "/path/a", "tools": "read"},
        {"path": "/path/b", "tools": "read"},
    ]
    assert "allowedReadPaths" not in result.new_config
    assert_migration_warns_about(result, "allowedReadPaths")
    assert_config_is_reachable(result.new_config)


def test_allowed_read_paths_merges_with_pre_existing_allowed_paths(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {
            "allowedReadPaths": ["/path/a"],
            "allowedPaths": [{"path": "/path/b", "tools": "all"}],
        }
    )

    assert result.new_config["allowedPaths"] == [
        {"path": "/path/b", "tools": "all"},
        {"path": "/path/a", "tools": "read"},
    ]
    assert_config_is_reachable(result.new_config)


def test_blocked_commands_sensitive_variables_and_sensitive_paths_copy_across_unchanged(
    assert_config_is_reachable,
):
    result = migrate_shfmt_permissions_config(
        {
            "blockedCommands": ["rm"],
            "sensitiveVariables": ["AWS_SECRET_ACCESS_KEY"],
            "sensitivePaths": ["/etc/passwd"],
        }
    )

    assert result.new_config["blockedCommands"] == ["rm"]
    assert result.new_config["sensitiveVariables"] == ["AWS_SECRET_ACCESS_KEY"]
    assert result.new_config["sensitivePaths"] == ["/etc/passwd"]
    assert_config_is_reachable(result.new_config)


def test_structured_command_parser_reshapes_into_the_new_per_slot_schema(assert_config_is_reachable):
    """improvement-20260920-131722: the old parallel keys collapse into one
    per-slot declaration. `--range` sits in `options_with_arguments` but not
    in `pathOptions`, so it migrates with no explicit `path` field - its
    path-ness now defaults to `true` under the new engine, which is exactly
    the widening `structured_parser_defaults_to_path_active` warns about.
    `-c` sits in BOTH lists, so its own former assertion survives as an
    explicit `path: true` rather than dissolving into that same default.
    """
    result = migrate_shfmt_permissions_config(
        {
            "allowedCommands": [
                {
                    "program": "vim",
                    "commandParser": {
                        "type": "structured",
                        "options_with_arguments": ["-c", {"option": "--range", "arguments": 2}],
                        "double_dash_stops": True,
                        "pathOptions": ["-c"],
                        "pathPositionals": [0],
                    },
                }
            ]
        }
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["commandParser"] == {
        "type": "structured",
        "options": [
            {"option": "-c", "arguments": 1, "path": True},
            {"option": "--range", "arguments": 2},
        ],
        "doubleDashStops": True,
        "positionals": [{"index": 0, "path": True}],
    }
    assert_config_is_reachable(result.new_config)


def test_structured_command_parser_migration_warns_unconditionally_about_the_path_active_default(
    assert_migration_warns_about,
):
    """Fired for every migrated structured parser regardless of its content -
    the same posture `dead_decision_knob_removed` takes, and for the same
    reason: the user is materially affected either way (a slot the old
    engine guessed as non-path is now a candidate)."""
    result = migrate_shfmt_permissions_config(
        {
            "allowedCommands": [
                {"program": "vim", "commandParser": {"type": "structured", "options_with_arguments": ["-c"]}}
            ]
        }
    )

    assert_migration_warns_about(result, "commandParser")


def test_structured_command_parser_migration_warns_about_an_inert_path_option(assert_migration_warns_about):
    """`pathOptions` naming an option absent from `options_with_arguments`
    contributed NOTHING under the old engine (the value parsed as a stray
    positional, and the option's own `arguments` list stayed empty) - a
    declaration the old author believed in and never got."""
    result = migrate_shfmt_permissions_config(
        {"allowedCommands": [{"program": "vim", "commandParser": {"type": "structured", "pathOptions": ["-o"]}}]}
    )

    assert_migration_warns_about(result, "pathOptions")


def test_structured_command_parser_migration_does_not_warn_about_a_populated_path_option(
    assert_migration_warns_about,
):
    result = migrate_shfmt_permissions_config(
        {
            "allowedCommands": [
                {
                    "program": "vim",
                    "commandParser": {
                        "type": "structured",
                        "options_with_arguments": ["-o"],
                        "pathOptions": ["-o"],
                    },
                }
            ]
        }
    )

    assert not any(w.kind == "structured_parser_inert_path_option" for w in result.warnings)


def test_a_provided_command_parser_copies_across_unchanged(assert_config_is_reachable):
    result = migrate_shfmt_permissions_config(
        {"allowedCommands": [{"program": "git", "commandParser": {"type": "provided", "name": "git"}}]}
    )

    [entry] = result.new_config["allowedCommands"]
    assert entry["commandParser"] == {"type": "provided", "name": "git"}
    assert_config_is_reachable(result.new_config)
