"""Unit tests for Pass: the strict, total ordering the pipeline sorts
objections by."""

from pass_ import Pass


def test_passes_are_totally_ordered_lowest_first():
    ordered = sorted(Pass)

    assert ordered == [
        Pass.SENSITIVE_PATHS,
        Pass.BLOCKED_COMMANDS,
        Pass.COMMAND_SUBSTITUTION,
        Pass.SENSITIVE_VARIABLES,
        Pass.REDIRECT_PATH_VALIDATION,
        Pass.ALLOWED_COMMAND,
    ]


def test_sensitive_paths_outranks_every_other_pass():
    assert all(Pass.SENSITIVE_PATHS < other for other in Pass if other != Pass.SENSITIVE_PATHS)


def test_allowed_command_is_the_last_pass():
    assert all(Pass.ALLOWED_COMMAND > other for other in Pass if other != Pass.ALLOWED_COMMAND)


def test_pass_is_an_int_enum_so_it_compares_and_sorts_like_a_plain_int():
    assert Pass.BLOCKED_COMMANDS < Pass.ALLOWED_COMMAND
    assert int(Pass.SENSITIVE_PATHS) == 0
