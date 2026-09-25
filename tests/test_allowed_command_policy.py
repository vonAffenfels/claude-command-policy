"""Unit tests for AllowedCommandPolicy: Pass 5, the deny-by-default
backbone - vouching, filter dispatch/construction, and the nested-command
filter's recursion, independent of the black-box spec suite
(test_permission_decisions.py covers the end-to-end behavioural contract).
"""

from pathlib import Path

from allowed_command import AllowedCommand
from allowed_command_policy import AllowedCommandPolicy
from config import Config
from pass_ import Pass
from path_resolution import PathResolutionContext
from reason import ParserCouldNotInterpretInvocation, ProgramNotAllowListed
from statement import Statement

FIXTURES = Path(__file__).parent / "fixtures" / "fake_parsers"


def _policy(allowed_commands, command, path_resolution=None, allowed_prefixes=(), recurse=False):
    resolution = path_resolution or PathResolutionContext(cwd="/project")
    policy = AllowedCommandPolicy(
        [AllowedCommand.from_entry(e, resolution) for e in allowed_commands],
        resolution,
        allowed_prefixes,
        recurse_via_allowed_commands=recurse,
        evaluate_nested_text=lambda text, depth: (_ for _ in ()).throw(
            AssertionError("evaluate_nested_text should not be called by this test")
        ),
        depth=0,
        default_max_depth=10,
    )
    return policy.for_statement(Statement.from_command(command))


def test_pass_is_the_last_pass():
    assert AllowedCommandPolicy([], PathResolutionContext(cwd="/project"), (), False, None, 0, 10).pass_ == (
        Pass.ALLOWED_COMMAND
    )


def test_does_not_match_matching_a_bare_entry_with_no_constraints():
    policy = _policy(["echo"], "echo hi")

    assert policy.matches() is False


def test_matches_when_no_entry_names_the_invoked_program():
    policy = _policy(["echo"], "rm -rf /")

    assert policy.matches() is True
    assert ProgramNotAllowListed("rm") in policy.decision().reason


def test_a_later_entry_can_vouch_for_what_an_earlier_entry_rejects():
    policy = _policy(
        [
            {"program": "echo", "filters": [{"type": "optionPresent", "option": "--x", "action": "required"}]},
            {"program": "echo"},
        ],
        "echo hi",
    )

    assert policy.matches() is False


def test_every_rejecting_entry_contributes_its_own_reason_when_none_vouches():
    """The direct fix for the old engine's defect: `rejecting_filter_def` was
    a single variable overwritten per entry, so only the LAST entry visited
    survived into the reason even though the text claimed to speak for the
    whole candidate set. Here TWO entries both fail to vouch, for TWO
    DIFFERENT causes (a filter mismatch, an undeclared variable) - both must
    appear, not just whichever was matched last.

    `hasNoPathParameters` states a true fact about `echo` (it takes no path
    operands) and is load-bearing here: without it the first entry would
    drop out on argument-path containment instead, and the case would no
    longer demonstrate two DIFFERENT causes at all.
    """
    from reason import DisallowedVariableReferenced, FilterRejected

    policy = _policy(
        [
            {
                "program": "echo",
                "onlyTheseVariables": ["HOME"],
                "hasNoPathParameters": True,
                "filters": [{"type": "optionPresent", "option": "--x", "action": "required"}],
            },
            {"program": "echo"},
        ],
        "echo $HOME",
    )

    assert policy.matches() is True
    reason = policy.decision().reason
    assert FilterRejected("echo", "optionPresent") in reason
    assert DisallowedVariableReferenced("echo", "HOME") in reason


# -- onlyTheseVariables vouching -------------------------------------------


def test_an_entry_does_not_vouch_for_an_undeclared_variable_reference():
    policy = _policy([{"program": "echo"}], "echo $HOME")

    assert policy.matches() is True


def test_an_entry_vouches_for_a_declared_variable_reference():
    """`onlyTheseVariables` vouches for WHICH names may be referenced;
    `hasNoPathParameters` answers the separate question of whether an
    unknowable value may sit in an argument slot at all. Both are needed,
    and both are true of `echo` - it takes no path operands
    (improvement-20260919-112214, second fix round, where an argument the
    parser cannot rule out counts as a path candidate). The flag is a
    factual claim that earns the variable, not a waiver that dodges it."""
    policy = _policy(
        [{"program": "echo", "onlyTheseVariables": ["HOME"], "hasNoPathParameters": True}], "echo $HOME"
    )

    assert policy.matches() is False


# -- hasNoPathParameters ---------------------------------------------------


def test_argument_path_outside_the_project_is_rejected_by_default():
    policy = _policy(["cat"], "cat /outside/the/project.txt")

    assert policy.matches() is True


def test_has_no_path_parameters_disables_only_the_argument_path_check():
    policy = _policy([{"program": "cat", "hasNoPathParameters": True}], "cat /outside/the/project.txt")

    assert policy.matches() is False


# -- parser dispatch / construction-time problems -------------------------


def test_a_commandparser_with_no_type_key_never_vouches():
    """A commandParser missing its 'type' key is a construction-time
    PROBLEM (AllowedCommand.problems()), not a raise - the entry becomes an
    InvalidParser stand-in that never interprets any invocation."""
    policy = _policy([{"program": "cat", "commandParser": {"name": "cat"}}], "cat x")

    assert policy.matches() is True
    assert ParserCouldNotInterpretInvocation("cat") in policy.decision().reason


def test_a_commandparser_with_an_unrecognised_type_never_vouches():
    policy = _policy([{"program": "cat", "commandParser": {"type": "made-up"}}], "cat x")

    assert policy.matches() is True
    assert ParserCouldNotInterpretInvocation("cat") in policy.decision().reason


def test_optionvalue_filter_naming_an_option_the_default_parser_never_populates_never_vouches():
    from reason import FilterRejected

    policy = _policy(
        [
            {
                "program": "git",
                "filters": [{"type": "optionValue", "option": "-m", "pattern": "^wip$", "action": "block"}],
            }
        ],
        "git commit -m wip",
    )

    assert policy.matches() is True
    assert FilterRejected("git", "optionValue") in policy.decision().reason


# -- programGlob matching (leaf 20260914-213652's cross-leaf hand-back,
#    completed by leaf 20260915-011123 since 213652 had already shipped) ---


def test_a_program_glob_entry_vouches_for_a_command_matching_the_wildcarded_version_segment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(tmp_path))
    invoked = str(tmp_path / "vonaffenfels-dev-tools" / "improvement" / "1.26.3" / "bin" / "foo")

    policy = _policy(
        [{"programGlob": {"marketplace": "vonaffenfels-dev-tools", "plugin": "improvement", "path": "bin/foo"}}],
        f"{invoked} clear",
    )

    assert policy.matches() is False


def test_a_program_glob_entry_does_not_vouch_for_a_different_version_path_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(tmp_path))
    invoked = str(tmp_path / "vonaffenfels-dev-tools" / "improvement" / "1.26.3" / "bin" / "other-script")

    policy = _policy(
        [{"programGlob": {"marketplace": "vonaffenfels-dev-tools", "plugin": "improvement", "path": "bin/foo"}}],
        invoked,
    )

    assert policy.matches() is True
    assert ProgramNotAllowListed(invoked) in policy.decision().reason


def test_a_program_glob_entry_defaults_the_cache_root_when_the_env_var_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", raising=False)
    monkeypatch.setattr("os.path.expanduser", lambda path: path.replace("~", str(tmp_path)))
    invoked = str(tmp_path / ".claude" / "plugins" / "cache" / "m" / "p" / "9.9.9" / "bin" / "foo")

    policy = _policy([{"programGlob": {"marketplace": "m", "plugin": "p", "path": "bin/foo"}}], invoked)

    assert policy.matches() is False


def test_a_program_glob_entry_that_does_not_vouch_reports_a_readable_label_instead_of_none(tmp_path, monkeypatch):
    from reason import FilterRejected

    monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(tmp_path))
    invoked = str(tmp_path / "m" / "p" / "1.0.0" / "bin" / "foo")

    policy = _policy(
        [
            {
                "programGlob": {"marketplace": "m", "plugin": "p", "path": "bin/foo"},
                "filters": [{"type": "optionPresent", "option": "--x", "action": "required"}],
            }
        ],
        invoked,
    )

    assert policy.matches() is True
    [reason] = policy.decision().reason
    assert isinstance(reason, FilterRejected)
    assert reason.program == "programGlob(m/p/.../bin/foo)"


def test_a_program_glob_entry_does_not_vouch_for_an_unresolvable_command_word():
    """An unresolvable command word (`Command.command_word is None`, e.g. a
    variable-invoked program) must not crash `fnmatch.fnmatch` when a
    `programGlob` entry is configured - it simply does not match, the same
    "unresolvable never matches any entry" rule a plain `program` entry
    already gets for free from `entry.program == command_word` (`None ==
    "foo"` is just `False`). Migrated from shfmt-permissions'
    `TestVariableInvokedCommands` (old test_quoted_plugin_root_word_is_never_
    allowed_by_suffix, :4887) - this is Bug B's failure shape, one layer
    deeper: not just "must not silently allow", but "must not crash either".
    """
    policy = _policy(
        [{"programGlob": {"marketplace": "m", "plugin": "p", "path": "bin/foo"}}],
        '"$CLAUDE_PLUGIN_ROOT/bin/foo" clear',
    )

    assert policy.matches() is True
    assert ProgramNotAllowListed("<unresolved>") in policy.decision().reason


# -- multi-statement walking ------------------------------------------------


def test_walks_every_sub_statement_not_just_the_top_level_one():
    policy = _policy(["cat"], "cat a; rm b")

    assert policy.matches() is True
    assert ProgramNotAllowListed("rm") in policy.decision().reason


def test_allows_a_multi_statement_command_when_every_invocation_vouches():
    policy = _policy(["cat"], "cat a; cat b")

    assert policy.matches() is False


# -- substitution unknowability (isolated from the black-box suite) --------


def test_a_block_filter_is_defeated_by_any_substitution_present():
    """`hasNoPathParameters` is true of `echo` and is what keeps this case
    about its named subject. Without it the invocation would still deny, but
    on argument-path containment rather than on the block rule - green for
    the wrong reason, which is worse than red."""
    policy = _policy(
        [
            {
                "program": "echo",
                "hasNoPathParameters": True,
                "filters": [{"type": "optionPresent", "option": "--forbidden", "action": "block"}],
            }
        ],
        "echo $(echo safe)",
    )

    assert policy.matches() is True


def test_a_non_index_required_filter_is_not_defeated_by_a_substitution():
    """`hasNoPathParameters` is true of `echo` - it takes no path operands -
    and is what lets `$(echo safe)` reach the filter at all under
    improvement-20260919-112214's second fix round. It isolates the filter
    behaviour this test is named after; it does not weaken it."""
    policy = _policy(
        [
            {
                "program": "echo",
                "hasNoPathParameters": True,
                "filters": [{"type": "optionPresent", "option": "--required", "action": "required"}],
            }
        ],
        "echo --required $(echo safe)",
    )

    assert policy.matches() is False


def test_an_external_parser_is_not_re_invoked_for_a_knowable_only_reparse(monkeypatch):
    """Design decision ('Unknowable content under an external parser'):
    external-parser-backed entries get no knowable-only re-parse attempt -
    unknowable content simply defeats a `required` filter for those
    entries, at the cost of one subprocess invocation, not two."""
    import external_parser_factory

    call_count = {"n": 0}
    original_raw_output_for = external_parser_factory.ExternalParserFactory.raw_output_for

    def counting_raw_output_for(self, parser, arguments):
        call_count["n"] += 1
        return original_raw_output_for(self, parser, arguments)

    monkeypatch.setattr(
        external_parser_factory.ExternalParserFactory, "raw_output_for", counting_raw_output_for
    )

    policy = _policy(
        [
            {
                "program": "my-tool",
                "onlyTheseVariables": ["HOME"],
                "hasNoPathParameters": True,
                "commandParser": {"type": "command", "command": str(FIXTURES / "echoes_named_value.py")},
                "filters": [{"type": "namedValue", "name": "echoed", "pattern": "^safe$", "action": "required"}],
            }
        ],
        "my-tool safe$HOME",
    )

    assert policy.matches() is True  # denied: fragment cannot prove presence
    assert call_count["n"] == 1


# -- nested-command filter (own fixture; the shared suite's xargs.py -------
# -- bundled parser artifact does not exist yet - see Implementation Notes) -


def _nested_config(filters, blocked=()):
    return {
        "allowedCommands": [
            {
                "program": "xargs",
                "commandParser": {"type": "command", "command": str(FIXTURES / "wrapper_publishing_nested_command.py")},
                "filters": filters,
            }
        ],
        "blockedCommands": list(blocked),
    }


def test_nested_command_filter_requires_the_published_sub_command_to_be_allowed():
    config = Config.from_dict(_nested_config([{"type": "nestedCommand"}], blocked=["rm"]))

    assert config.decision_for("xargs rm ./build").decision == "deny"


def test_nested_command_filter_passes_when_the_sub_command_is_allowed():
    config_dict = _nested_config([{"type": "nestedCommand"}])
    config_dict["allowedCommands"].append("echo")
    config = Config.from_dict(config_dict)

    assert config.decision_for("xargs echo hi").decision == "allow"


def test_nested_command_filter_fails_closed_when_nothing_was_published():
    config = Config.from_dict(_nested_config([{"type": "nestedCommand"}]))

    assert config.decision_for("xargs").decision == "deny"


def test_nested_command_filter_composes_with_a_sibling_entrys_ordinary_filter():
    config = Config.from_dict(
        {
            "allowedCommands": [
                {
                    "program": "xargs",
                    "commandParser": {
                        "type": "command",
                        "command": str(FIXTURES / "wrapper_publishing_nested_command.py"),
                    },
                    "filters": [{"type": "optionPresent", "option": "--dry-run", "action": "required"}],
                },
                {
                    "program": "xargs",
                    "commandParser": {
                        "type": "command",
                        "command": str(FIXTURES / "wrapper_publishing_nested_command.py"),
                    },
                    "filters": [{"type": "nestedCommand"}],
                },
            ],
            "blockedCommands": ["rm"],
        }
    )

    assert config.decision_for("xargs --dry-run rm ./build").decision == "allow"
    assert config.decision_for("xargs rm ./build").decision == "deny"


def test_nested_command_filter_max_depth_denies_on_exceed():
    config = Config.from_dict(_nested_config([{"type": "nestedCommand", "maxDepth": 1}]))

    assert config.decision_for("xargs xargs rm -rf ./build").decision == "deny"


def test_via_allowed_commands_recursion_is_depth_guarded():
    """Separately from the nested-command filter's own maxDepth, the
    via-allowed-commands substitution recursion is depth-guarded on the
    same explicit, threaded (depth, default_max_depth) terms - trip it
    directly (depth already at the limit) without needing real nesting."""
    allowed_commands = [AllowedCommand.from_entry("echo")]

    at_limit = AllowedCommandPolicy(
        allowed_commands,
        PathResolutionContext(cwd="/project"),
        (),
        recurse_via_allowed_commands=True,
        evaluate_nested_text=lambda text, depth: (_ for _ in ()).throw(AssertionError("unused")),
        depth=5,
        default_max_depth=5,
    ).for_statement(Statement.from_command("echo $(echo safe)"))

    assert at_limit.matches() is True


def test_nested_command_filter_needs_a_parser_that_can_publish_sub_commands():
    from reason import FilterRejected

    policy = _policy(
        [{"program": "xargs", "filters": [{"type": "nestedCommand"}]}],
        "xargs rm ./build",
    )

    assert policy.matches() is True
    assert FilterRejected("xargs", "nestedCommand") in policy.decision().reason
