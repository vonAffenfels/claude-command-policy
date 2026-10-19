"""Contract tests of `GitRepositoryLayout` against REAL temp repositories -
the one adapter that runs `git`. Mirrors the planning probe
(experiments/git-commands/probe.sh): the first `worktree` line of
`git worktree list --porcelain` is the main repository root, and
`git rev-parse --show-toplevel` is the containing working tree root.
"""

from repository_layout import GitRepositoryLayout


def test_the_main_checkout_is_its_own_main_repository_root(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().main_repository_root(layout.main) == layout.main


def test_a_subdirectory_of_the_main_checkout_answers_with_the_main_checkout_root(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().main_repository_root(layout.main / "src") == layout.main


def test_a_linked_worktree_inside_the_main_checkout_answers_with_the_main_checkout(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().main_repository_root(layout.worktree) == layout.main


def test_a_linked_worktree_outside_the_main_checkout_answers_with_the_main_checkout(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().main_repository_root(layout.worktree_outside_main) == layout.main


def test_a_nested_independent_repository_is_its_own_main_repository_root(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().main_repository_root(layout.nested_repository) == layout.nested_repository


def test_a_directory_outside_any_repository_has_no_main_repository_root(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().main_repository_root(layout.not_a_repository) is None


def test_the_working_tree_root_of_the_main_checkout_is_the_main_checkout(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().working_tree_root(layout.main / "src") == layout.main


def test_the_working_tree_root_of_a_worktree_subdirectory_is_the_worktree_root(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().working_tree_root(layout.worktree / "docs") == layout.worktree


def test_the_working_tree_root_of_a_nested_independent_repository_is_that_repository(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().working_tree_root(layout.nested_repository) == layout.nested_repository


def test_a_directory_outside_any_repository_has_no_working_tree_root(repository_with_linked_worktree):
    layout = repository_with_linked_worktree

    assert GitRepositoryLayout().working_tree_root(layout.not_a_repository) is None


def test_a_directory_that_does_not_exist_has_no_roots_at_all(tmp_path):
    missing = tmp_path / "does-not-exist"

    assert GitRepositoryLayout().main_repository_root(missing) is None
    assert GitRepositoryLayout().working_tree_root(missing) is None


def test_a_missing_git_executable_degrades_to_no_roots(repository_with_linked_worktree):
    layout = repository_with_linked_worktree
    without_git = GitRepositoryLayout(git_executable="git-that-does-not-exist")

    assert without_git.main_repository_root(layout.main) is None
    assert without_git.working_tree_root(layout.main) is None
