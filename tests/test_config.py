"""Unit tests for Config construction, merge, warnings and explain.

decision_for is NOT this leaf's job (leaf 20260914-213652 wires it) - these
tests exercise only defaults()/from_dict()/merged_with()/warnings()/explain().
"""

import pytest

from allowed_command import AllowedCommand
from config import Config
from layer_presence import LayerPresence
from sensitive_path import SensitivePath


def test_defaults_has_no_allowed_commands():
    assert Config.defaults().allowed_commands == ()


def test_defaults_uses_via_allowed_commands_as_the_surviving_knob():
    assert Config.defaults().command_substitution_response == "via-allowed-commands"


def test_defaults_has_no_warnings():
    assert Config.defaults().warnings() == ()


def test_decision_for_denies_by_default_with_no_allowed_commands_configured():
    """`decision_for` is wired by leaf 20260914-213652 - the exhaustive
    behavioural specification lives in test_permission_decisions.py; this is
    just a smoke test confirming the stub no longer raises."""
    result = Config.defaults().decision_for("echo hi")

    assert result.decision == "deny"


def test_decision_for_path_is_passthrough_with_no_allowed_paths_configured():
    """`decision_for_path` (leaf 20260914-213825's own addition, see
    path_config.py's module docstring): the exhaustive behavioural
    specification lives in test_path_permission.py; this is a smoke test
    confirming a real Config wires it end to end."""
    result = Config.defaults().decision_for_path("Read", "/etc/passwd")

    assert result.decision == "passthrough"


def test_decision_for_path_allows_a_configured_path():
    config = Config.from_dict({"allowedPaths": [{"tools": "read", "path": "/shared/doc.txt"}]})

    result = config.decision_for_path("Read", "/shared/doc.txt")

    assert result.decision == "allow"


def test_decision_for_path_resolves_a_symlinked_target_before_matching(tmp_path):
    """Proves `decision_for_path` (the Read/Grep/Glob domain) inherits the
    same symlink-resolution fix as the bash pipeline, through the shared
    `absolute_path_of` seam - improvement-20260918-185726. A rule declared
    against the REAL path must still match a request that reaches it only
    through a symlink.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "doc.txt").write_text("hi")
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "escape").symlink_to(outside)

    config = Config.from_dict({"allowedPaths": [{"tools": "read", "path": str(outside / "doc.txt")}]})

    result = config.decision_for_path("Read", str(project_dir / "escape" / "doc.txt"))

    assert result.decision == "allow"


def test_from_dict_builds_allowed_commands_from_entries():
    config = Config.from_dict({"allowedCommands": ["echo", {"program": "cat"}]})

    assert config.allowed_commands == (
        AllowedCommand.from_entry("echo"),
        AllowedCommand.from_entry({"program": "cat"}),
    )


def test_from_dict_builds_blocked_commands():
    config = Config.from_dict({"blockedCommands": ["rm"]})

    assert config.blocked_commands.names == ("rm",)


def test_from_dict_builds_sensitive_variables():
    config = Config.from_dict({"sensitiveVariables": ["AWS_SECRET_ACCESS_KEY"]})

    assert config.sensitive_variables.names == ("AWS_SECRET_ACCESS_KEY",)


def test_from_dict_builds_sensitive_paths():
    config = Config.from_dict({"sensitivePaths": ["/etc/passwd"]})

    assert config.sensitive_paths == (SensitivePath.from_entry("/etc/passwd"),)


def test_from_dict_builds_allowed_path_prefixes():
    config = Config.from_dict({"additionalAllowedPathPrefixes": ["/shared"]})

    assert config.allowed_path_prefixes.names == ("/shared",)


def test_from_dict_builds_path_config():
    config = Config.from_dict({"allowedPaths": [{"tools": "read", "path": "/shared/docs"}]})

    assert len(config.path_config.rules) == 1
    assert config.path_config.rules[0].path == "/shared/docs"


def test_from_dict_defaults_command_substitution_response_to_via_allowed_commands():
    assert Config.from_dict({}).command_substitution_response == "via-allowed-commands"


def test_from_dict_accepts_deny_as_command_substitution_response():
    assert Config.from_dict({"commandSubstitutionResponse": "deny"}).command_substitution_response == "deny"


def test_from_dict_falls_back_an_invalid_command_substitution_response():
    config = Config.from_dict({"commandSubstitutionResponse": "ask"})

    assert config.command_substitution_response == "via-allowed-commands"


def test_from_dict_warns_about_an_invalid_command_substitution_response():
    config = Config.from_dict({"commandSubstitutionResponse": "ask"})

    [warning] = config.warnings()
    assert warning.kind == "invalid_knob_value"
    assert warning.knob == "commandSubstitutionResponse"
    assert warning.configured == "ask"
    assert warning.in_effect == "via-allowed-commands"


def test_the_warning_for_an_invalid_knob_names_the_layer_it_came_from():
    config = Config.from_dict({"commandSubstitutionResponse": "ask"}, source="user")

    [warning] = config.warnings()
    assert warning.layer == "user"


def test_from_dict_warns_about_an_uncompilable_allowed_command_filter_pattern_without_raising():
    """Leaf 20260915-010959's carried-forward finding, now generalised
    (improvement 20260925-120037): every static defect `AllowedCommand.
    from_entry` finds - an uncompilable pattern included - becomes a
    `problem`, surfaced through `Config.warnings()` via the generic
    `allowed_command_problem` kind rather than a construction-time raise.
    """
    config = Config.from_dict(
        {
            "allowedCommands": [
                {
                    "program": "echo",
                    "filters": [{"type": "parameterRegex", "pattern": "[unclosed", "action": "block"}],
                }
            ]
        },
        source="project",
    )

    [warning] = config.warnings()
    assert warning.kind == "allowed_command_problem"
    assert warning.layer == "project"
    assert warning.program == "echo"
    assert "parameterRegex" in warning.problem
    assert "[unclosed" in warning.problem


def test_merged_with_unions_allowed_commands():
    base = Config.from_dict({"allowedCommands": ["echo"]})
    overlay = Config.from_dict({"allowedCommands": ["cat"]})

    merged = base.merged_with(overlay)

    assert merged.allowed_commands == (
        AllowedCommand.from_entry("echo"),
        AllowedCommand.from_entry("cat"),
    )


def test_merged_with_unions_blocked_commands():
    base = Config.from_dict({"blockedCommands": ["rm"]})
    overlay = Config.from_dict({"blockedCommands": ["curl"]})

    assert base.merged_with(overlay).blocked_commands.names == ("rm", "curl")


def test_merged_with_unions_sensitive_paths():
    base = Config.from_dict({"sensitivePaths": ["/etc/passwd"]})
    overlay = Config.from_dict({"sensitivePaths": ["/etc/shadow"]})

    assert base.merged_with(overlay).sensitive_paths == (
        SensitivePath.from_entry("/etc/passwd"),
        SensitivePath.from_entry("/etc/shadow"),
    )


def test_merged_with_unions_path_config():
    base = Config.from_dict({"allowedPaths": [{"tools": "read", "path": "/a"}]})
    overlay = Config.from_dict({"allowedPaths": [{"tools": "read", "path": "/b"}]})

    assert len(base.merged_with(overlay).path_config.rules) == 2


def test_merged_with_keeps_the_base_knob_value_when_the_overlay_does_not_configure_it():
    base = Config.from_dict({"commandSubstitutionResponse": "deny"})
    overlay = Config.from_dict({"allowedCommands": ["echo"]})

    assert base.merged_with(overlay).command_substitution_response == "deny"


def test_merged_with_lets_an_explicit_overlay_knob_value_win():
    base = Config.from_dict({"commandSubstitutionResponse": "deny"})
    overlay = Config.from_dict({"commandSubstitutionResponse": "via-allowed-commands"})

    assert base.merged_with(overlay).command_substitution_response == "via-allowed-commands"


def test_merged_with_concatenates_warnings_from_both_layers():
    base = Config.from_dict({"commandSubstitutionResponse": "ask"}, source="user")
    overlay = Config.from_dict({"commandSubstitutionResponse": "block"}, source="project")

    warnings = base.merged_with(overlay).warnings()

    assert [w.layer for w in warnings] == ["user", "project"]


def test_an_invalid_value_validly_overridden_by_a_later_layer_still_warns_but_the_final_value_is_valid():
    base = Config.from_dict({"commandSubstitutionResponse": "ask"}, source="user")
    overlay = Config.from_dict({"commandSubstitutionResponse": "deny"}, source="project")

    merged = base.merged_with(overlay)

    assert merged.command_substitution_response == "deny"
    assert len(merged.warnings()) == 1
    assert merged.warnings()[0].layer == "user"


def test_with_allowed_commands_returns_a_new_config_with_unchanged_siblings_the_same_object():
    original = Config.from_dict({"allowedCommands": ["echo"], "blockedCommands": ["rm"]})

    updated = original.with_allowed_commands((AllowedCommand.from_entry("cat"),))

    assert updated is not original
    assert updated.allowed_commands == (AllowedCommand.from_entry("cat"),)
    assert updated.blocked_commands is original.blocked_commands


def test_explain_states_when_nothing_is_auto_allowed():
    assert "no commands are auto-allowed" in Config.defaults().explain().lower()


def test_explain_lists_each_auto_allowed_command():
    config = Config.from_dict({"allowedCommands": ["echo"]})

    assert "echo" in config.explain()


def test_warnings_returns_every_warning_collected_during_construction(assert_config_is_reachable):
    assert_config_is_reachable({"allowedCommands": ["echo"]})


def test_a_config_with_no_layer_presence_recorded_explains_no_missing_config_line():
    """The ordinary case (no loader involved, e.g. a test's own
    `Config.from_dict`) must gain no noise - the searched-path/presence
    record is opt-in, carried only by whoever actually knows what was
    searched (config_loader.py)."""
    assert "No command-policy.json" not in Config.defaults().explain()


def test_with_layer_presence_renders_the_no_config_line_first_when_nothing_was_found():
    presence = LayerPresence.of("user", "/home/x/.claude/command-policy.json", found=False).union(
        LayerPresence.of("project", "/proj/.claude/command-policy.json", found=False)
    )
    config = Config.defaults().with_layer_presence(presence)

    explanation = config.explain()
    assert explanation.startswith("No command-policy.json config file found at either scope")
    assert "/home/x/.claude/command-policy.json" in explanation
    assert "/proj/.claude/command-policy.json" in explanation
    assert "migrate-config" in explanation


def test_with_layer_presence_stays_silent_when_one_layer_was_found():
    presence = LayerPresence.of("user", "/home/x/.claude/command-policy.json", found=True).union(
        LayerPresence.of("project", "/proj/.claude/command-policy.json", found=False)
    )
    config = Config.defaults().with_layer_presence(presence)

    assert "No command-policy.json config file found" not in config.explain()


def test_explain_carries_the_decomposition_advisory_even_for_an_empty_config():
    """improvement-20260919-230721: the advisory is static guidance, never
    config-derived - it must render for Config.defaults() so the user facing
    the most denials (an absent/empty config) sees the hint too."""
    explanation = Config.defaults().explain()

    assert "find-auto-allowed-command" in explanation
    assert "decompos" in explanation.lower()


def test_explain_renders_the_decomposition_advisory_after_command_substitution_response():
    config = Config.from_dict({"allowedCommands": ["echo"]})

    explanation = config.explain()
    substitution_index = explanation.index("commandSubstitutionResponse:")
    advisory_index = explanation.index("find-auto-allowed-command")

    assert advisory_index > substitution_index


def test_explain_keeps_the_no_config_line_first_and_the_decomposition_advisory_last_together():
    """The two additions land at opposite ends of explain() and must not
    collide: 081655's 'no config file found' line explains the empty
    sections beneath it, so it stays FIRST; this advisory is unconditional
    guidance meant to be the last thing read, so it stays LAST."""
    presence = LayerPresence.of("user", "/home/x/.claude/command-policy.json", found=False).union(
        LayerPresence.of("project", "/proj/.claude/command-policy.json", found=False)
    )
    config = Config.defaults().with_layer_presence(presence)

    explanation = config.explain()

    assert explanation.startswith("No command-policy.json config file found at either scope")
    assert explanation.rstrip().endswith("how to recognise when this applies.")


def test_merged_with_unions_layer_presence_from_both_layers():
    base = Config.defaults().with_layer_presence(LayerPresence.of("user", "/a", found=False))
    overlay = Config.defaults().with_layer_presence(LayerPresence.of("project", "/b", found=False))

    explanation = base.merged_with(overlay).explain()

    assert explanation.startswith("No command-policy.json config file found at either scope")
    assert "/a" in explanation
    assert "/b" in explanation
