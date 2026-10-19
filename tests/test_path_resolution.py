"""Unit tests for PathResolutionContext: an injected stand-in for the
ambient os.path.exists()/os.path.abspath() reads DefaultParser and
PathsFilter perform today, so both are exercisable without a real
filesystem or a pinned process cwd.

Two anchors, named by WHOSE relative path it is: a command argument resolves
against the working directory (where the command runs), a config entry
against the boundary root (so its meaning does not drift with `cd`).
"""

import os

from path_resolution import PathResolutionContext


def test_an_absolute_value_is_returned_normalized_but_otherwise_unchanged():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.absolute_path_of_command_argument("/etc/passwd") == "/etc/passwd"
    assert context.absolute_path_of_config_entry("/etc/passwd") == "/etc/passwd"


def test_a_home_relative_value_expands_against_a_fixed_home_not_the_real_one():
    context = PathResolutionContext(boundary="/home/user/project", home="/home/user")

    assert context.absolute_path_of_command_argument("~/notes.txt") == "/home/user/notes.txt"
    assert context.absolute_path_of_config_entry("~/notes.txt") == "/home/user/notes.txt"


def test_a_relative_command_argument_resolves_against_the_working_directory():
    context = PathResolutionContext(boundary="/wt", working_directory="/wt/docs")

    assert context.absolute_path_of_command_argument("../x") == "/wt/x"


def test_a_relative_config_entry_resolves_against_the_boundary_not_the_working_directory():
    context = PathResolutionContext(boundary="/wt", working_directory="/wt/docs")

    assert context.absolute_path_of_config_entry("notes.txt") == "/wt/notes.txt"


def test_the_working_directory_defaults_to_the_boundary():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.absolute_path_of_command_argument("file.txt") == "/home/user/project/file.txt"


def test_a_dotted_relative_value_resolves_against_its_anchor():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.absolute_path_of_command_argument("./sub/file.txt") == "/home/user/project/sub/file.txt"


def test_resolution_routes_its_result_through_the_injected_realpath_predicate():
    context = PathResolutionContext(
        boundary="/home/user/project",
        realpath_predicate=lambda path: path.replace("/project/", "/resolved/"),
    )

    assert context.absolute_path_of_command_argument("escape/pwned.txt") == "/home/user/resolved/escape/pwned.txt"
    assert context.absolute_path_of_config_entry("escape/pwned.txt") == "/home/user/resolved/escape/pwned.txt"


def test_exists_delegates_to_the_injected_predicate_not_the_real_filesystem():
    context = PathResolutionContext(boundary="/home/user/project", exists_predicate=lambda path: path == "known")

    assert context.exists("known") is True
    assert context.exists("unknown") is False


def test_exists_defaults_to_false_when_no_predicate_is_injected():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.exists("anything") is False


def test_is_contained_admits_a_path_equal_to_the_boundary():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.is_contained("/home/user/project") is True


def test_is_contained_admits_a_path_under_the_boundary():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.is_contained("/home/user/project/sub/file.txt") is True


def test_is_contained_rejects_a_path_outside_the_boundary():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.is_contained("/etc/passwd") is False


def test_is_contained_checks_the_boundary_not_the_working_directory():
    context = PathResolutionContext(boundary="/wt", working_directory="/wt/docs")

    assert context.is_contained("/wt/other/file.txt") is True


def test_is_contained_rejects_a_longer_sibling_directory():
    """Flag List E8: `/home/user` must not admit `/home/username`."""
    context = PathResolutionContext(boundary="/home/user")

    assert context.is_contained("/home/username/secret.txt") is False


def test_is_contained_admits_a_path_under_an_allowed_prefix():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.is_contained("/shared/notes.txt", allowed_prefixes=["/shared"]) is True


def test_is_contained_rejects_a_path_outside_both_the_boundary_and_every_prefix():
    context = PathResolutionContext(boundary="/home/user/project")

    assert context.is_contained("/etc/passwd", allowed_prefixes=["/shared"]) is False


def test_is_contained_expands_home_on_an_allowed_prefix():
    context = PathResolutionContext(boundary="/home/user/project", home="/home/user")

    assert context.is_contained("/home/user/.config/notes.txt", allowed_prefixes=["~/.config"]) is True


def test_is_contained_resolves_a_relative_allowed_prefix_against_the_boundary():
    context = PathResolutionContext(boundary="/wt", working_directory="/wt/docs")

    assert context.is_contained("/wt/shared/notes.txt", allowed_prefixes=["shared"]) is True


def test_is_contained_resolves_an_allowed_prefix_through_the_injected_realpath_predicate():
    context = PathResolutionContext(
        boundary="/home/user/project",
        realpath_predicate=lambda path: path.replace("/link", "/real"),
    )

    assert context.is_contained("/real/target/file.txt", allowed_prefixes=["/link/target"]) is True


def test_for_process_anchors_both_at_the_process_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    context = PathResolutionContext.for_process()

    assert context.absolute_path_of_command_argument("file.txt") == os.path.join(os.getcwd(), "file.txt")
    assert context.is_contained(os.path.join(os.getcwd(), "file.txt")) is True


def test_resolution_resolves_a_real_symlink_to_its_actual_target(tmp_path):
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

    context = PathResolutionContext(boundary=str(project), realpath_predicate=os.path.realpath)

    assert context.absolute_path_of_command_argument("escape/pwned.txt") == str(outside / "pwned.txt")
