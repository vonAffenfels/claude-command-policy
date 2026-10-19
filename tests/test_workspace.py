"""`Workspace` priority rules, exercised against an in-memory
`RepositoryLayout` - no `git`, no filesystem, no ambient cwd.

Project config file: `{main repository root of the LAUNCH dir}/.claude/
command-policy.json`, else `{launch dir}/.claude/command-policy.json`.
Boundary: the working tree root of the WORKING dir, else the launch dir.
"""

from pathlib import Path

from workspace import Workspace


class InMemoryRepository:
    def __init__(self, main, linked_worktrees=()):
        self.main = Path(main)
        self.working_trees = (self.main,) + tuple(Path(worktree) for worktree in linked_worktrees)


class InMemoryRepositoryLayout:
    """Answers like git does: the innermost working tree containing a
    directory wins (a nested independent repository answers for itself)."""

    def __init__(self, *repositories):
        self._repositories = repositories

    def main_repository_root(self, directory):
        repository, _ = self._innermost(directory) or (None, None)
        return repository.main if repository else None

    def working_tree_root(self, directory):
        _, working_tree = self._innermost(directory) or (None, None)
        return working_tree

    def _innermost(self, directory):
        directory = Path(directory)
        containing = [
            (repository, working_tree)
            for repository in self._repositories
            for working_tree in repository.working_trees
            if directory == working_tree or working_tree in directory.parents
        ]
        return max(containing, key=lambda pair: len(pair[1].parts), default=None)


REPOSITORY = InMemoryRepository("/repo", linked_worktrees=("/repo/.claude/worktrees/wt",))
NESTED_REPOSITORY = InMemoryRepository("/repo/vendor/nested")
LAYOUT = InMemoryRepositoryLayout(REPOSITORY, NESTED_REPOSITORY)


def workspace(launch_directory, working_directory):
    return Workspace(
        launch_directory=launch_directory,
        working_directory=working_directory,
        repository_layout=LAYOUT,
    )


def test_launched_and_working_in_the_main_checkout_uses_its_config_and_boundary():
    session = workspace("/repo", "/repo")

    assert session.project_config_file() == Path("/repo/.claude/command-policy.json")
    assert session.boundary() == Path("/repo")


def test_after_entering_a_worktree_the_config_stays_main_and_the_boundary_is_the_worktree():
    session = workspace("/repo", "/repo/.claude/worktrees/wt")

    assert session.project_config_file() == Path("/repo/.claude/command-policy.json")
    assert session.boundary() == Path("/repo/.claude/worktrees/wt")


def test_launched_directly_in_a_worktree_uses_the_main_checkouts_config():
    session = workspace("/repo/.claude/worktrees/wt", "/repo/.claude/worktrees/wt")

    assert session.project_config_file() == Path("/repo/.claude/command-policy.json")
    assert session.boundary() == Path("/repo/.claude/worktrees/wt")


def test_working_in_a_worktree_subdirectory_keeps_the_boundary_at_the_worktree_root():
    session = workspace("/repo/.claude/worktrees/wt", "/repo/.claude/worktrees/wt/docs")

    assert session.boundary() == Path("/repo/.claude/worktrees/wt")
    assert session.working_directory() == Path("/repo/.claude/worktrees/wt/docs")


def test_launched_in_a_subdirectory_of_the_main_checkout_uses_the_config_at_the_main_root():
    session = workspace("/repo/src", "/repo/src")

    assert session.project_config_file() == Path("/repo/.claude/command-policy.json")
    assert session.boundary() == Path("/repo")


def test_working_in_a_nested_independent_repository_moves_only_the_boundary():
    session = workspace("/repo", "/repo/vendor/nested/lib")

    assert session.project_config_file() == Path("/repo/.claude/command-policy.json")
    assert session.boundary() == Path("/repo/vendor/nested")


def test_outside_any_repository_both_fall_back_to_the_launch_directory():
    session = workspace("/plain", "/plain/sub")

    assert session.project_config_file() == Path("/plain/.claude/command-policy.json")
    assert session.boundary() == Path("/plain")


def test_launched_in_a_repository_but_working_outside_any_falls_back_to_the_launch_directory_as_boundary():
    session = workspace("/repo/.claude/worktrees/wt", "/elsewhere")

    assert session.project_config_file() == Path("/repo/.claude/command-policy.json")
    assert session.boundary() == Path("/repo/.claude/worktrees/wt")


def test_the_project_root_is_the_directory_holding_the_project_config():
    session = workspace("/repo/.claude/worktrees/wt", "/repo/.claude/worktrees/wt")

    assert session.project_root() == Path("/repo")


def test_its_path_resolution_resolves_command_arguments_against_the_working_directory():
    session = workspace("/repo/.claude/worktrees/wt", "/repo/.claude/worktrees/wt/docs")

    resolution = session.path_resolution(realpath_predicate=lambda path: path)

    assert resolution.absolute_path_of_command_argument("../x") == "/repo/.claude/worktrees/wt/x"
    assert resolution.absolute_path_of_config_entry("notes.txt") == "/repo/.claude/worktrees/wt/notes.txt"


def test_of_this_session_reads_the_launch_directory_from_claude_project_dir(monkeypatch, repository_with_linked_worktree):
    layout = repository_with_linked_worktree
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(layout.worktree))
    monkeypatch.chdir(layout.worktree / "docs")

    session = Workspace.of_this_session()

    assert session.project_config_file() == layout.main / ".claude" / "command-policy.json"
    assert session.boundary() == layout.worktree
    assert session.working_directory() == layout.worktree / "docs"


def test_of_this_session_falls_back_to_the_process_cwd_without_claude_project_dir(monkeypatch, repository_with_linked_worktree):
    layout = repository_with_linked_worktree
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(layout.worktree)

    assert Workspace.of_this_session().project_config_file() == layout.main / ".claude" / "command-policy.json"
