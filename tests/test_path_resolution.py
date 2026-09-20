"""Unit tests for PathResolutionContext: an injected stand-in for the
ambient os.path.exists()/os.path.abspath() reads DefaultParser and
PathsFilter perform today, so both are exercisable without a real
filesystem or a pinned process cwd.
"""

import os

from path_resolution import PathResolutionContext


def test_an_absolute_value_is_returned_normalized_but_otherwise_unchanged():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.absolute_path_of("/etc/passwd") == "/etc/passwd"


def test_a_home_relative_value_expands_against_a_fixed_home_not_the_real_one():
    context = PathResolutionContext(cwd="/home/user/project", home="/home/user")

    assert context.absolute_path_of("~/notes.txt") == "/home/user/notes.txt"


def test_a_relative_value_resolves_against_the_injected_cwd_not_the_process_cwd():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.absolute_path_of("file.txt") == "/home/user/project/file.txt"


def test_a_dotted_relative_value_resolves_against_the_injected_cwd():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.absolute_path_of("./sub/file.txt") == "/home/user/project/sub/file.txt"


def test_absolute_path_of_routes_its_result_through_the_injected_realpath_predicate():
    context = PathResolutionContext(
        cwd="/home/user/project",
        realpath_predicate=lambda path: path.replace("/project/", "/resolved/"),
    )

    assert context.absolute_path_of("escape/pwned.txt") == "/home/user/resolved/escape/pwned.txt"


def test_absolute_path_of_defaults_to_a_no_op_realpath_predicate_when_none_is_injected():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.absolute_path_of("file.txt") == "/home/user/project/file.txt"


def test_exists_delegates_to_the_injected_predicate_not_the_real_filesystem():
    context = PathResolutionContext(cwd="/home/user/project", exists_predicate=lambda path: path == "known")

    assert context.exists("known") is True
    assert context.exists("unknown") is False


def test_exists_defaults_to_false_when_no_predicate_is_injected():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.exists("anything") is False


def test_is_contained_admits_a_path_equal_to_the_root():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.is_contained("/home/user/project") is True


def test_is_contained_admits_a_path_under_the_root():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.is_contained("/home/user/project/sub/file.txt") is True


def test_is_contained_rejects_a_path_outside_the_root():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.is_contained("/etc/passwd") is False


def test_is_contained_rejects_a_longer_sibling_directory():
    """Flag List E8: `/home/user` must not admit `/home/username`."""
    context = PathResolutionContext(cwd="/home/user")

    assert context.is_contained("/home/username/secret.txt") is False


def test_is_contained_admits_a_path_under_an_allowed_prefix():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.is_contained("/shared/notes.txt", allowed_prefixes=["/shared"]) is True


def test_is_contained_rejects_a_path_outside_both_the_root_and_every_prefix():
    context = PathResolutionContext(cwd="/home/user/project")

    assert context.is_contained("/etc/passwd", allowed_prefixes=["/shared"]) is False


def test_is_contained_expands_home_on_an_allowed_prefix():
    context = PathResolutionContext(cwd="/home/user/project", home="/home/user")

    assert context.is_contained("/home/user/.config/notes.txt", allowed_prefixes=["~/.config"]) is True


def test_is_contained_resolves_an_allowed_prefix_through_the_injected_realpath_predicate():
    context = PathResolutionContext(
        cwd="/home/user/project",
        realpath_predicate=lambda path: path.replace("/link", "/real"),
    )

    assert context.is_contained("/real/target/file.txt", allowed_prefixes=["/link/target"]) is True


def test_absolute_path_of_resolves_a_real_symlink_to_its_actual_target(tmp_path):
    """The one deliberate real-filesystem exception in this suite (see the
    improvement file's Implementation Notes): the thing under test is
    whether `os.path.realpath`, the real default `for_process()` injects,
    actually resolves a real symlinked join the way the fix assumes -
    mirrors the reported false-ALLOW's exact shape (`escape -> ../outside`
    then `escape/pwned.txt`).
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "escape").symlink_to(outside)

    context = PathResolutionContext(cwd=str(project), realpath_predicate=os.path.realpath)

    assert context.absolute_path_of("escape/pwned.txt") == str(outside / "pwned.txt")
