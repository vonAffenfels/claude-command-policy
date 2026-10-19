"""Workspace: where this session is - which project config file applies,
which directory is the path-containment boundary, and which directory
relative command arguments resolve against.

Inside a git repository, the MAIN repository wins over `CLAUDE_PROJECT_DIR`
(improvement-20261019-095449). A session launched in the main checkout,
launched directly in a linked worktree, or moved into one by
`EnterWorktree` - all read and write the same
`{main repository root}/.claude/command-policy.json`:

- **Project root** - the main repository root of the LAUNCH directory, else
  the launch directory itself. Asked of the launch directory, never the
  working directory: the working directory follows Bash `cd`, and a `cd`
  into a nested independent repository must not switch the session to that
  repository's policy. Always the ROOT - a launch from a subdirectory does
  not carry the subpath over.
- **Boundary** - the working tree root of the WORKING directory (whichever
  worktree or main checkout the session is in; its root, so a `cd` into a
  subdirectory does not shrink it), else the launch directory. Matches what
  Claude Code itself enforces inside a worktree.
- **Working directory** - where commands run; relative command arguments
  resolve against it (see path_resolution.py).

Outside a git repository (or with `git` missing or failing) both fall back
to the launch directory - the pre-worktree `CLAUDE_PROJECT_DIR` behaviour.

The rules receive everything at construction - plain directories plus a
`RepositoryLayout` port - so they run against an in-memory layout with no
`git` (tests/test_workspace.py). `of_this_session()` is the ONE place that
reads `CLAUDE_PROJECT_DIR` / the process cwd and wires the real `git`
adapter; every production reader and writer of the project config goes
through it.

Cost: production asks `git` once per question (two subprocesses for a hook
that needs both the config file and the boundary). Accepted per the
improvement's design decision "How the main repository is found" - the
answer is not inferred from `.git` files to save the subprocess.
"""

from __future__ import annotations

import os
from pathlib import Path

from path_resolution import PathResolutionContext
from repository_layout import GitRepositoryLayout

PROJECT_CONFIG_RELATIVE_PATH = Path(".claude") / "command-policy.json"


class Workspace:
    def __init__(self, launch_directory, working_directory, repository_layout):
        self._launch_directory = Path(launch_directory)
        self._working_directory = Path(working_directory)
        self._repository_layout = repository_layout

    @classmethod
    def of_this_session(cls):
        """Launch directory = `CLAUDE_PROJECT_DIR`, else the process cwd -
        the Bash-tool helpers (`add-allow-policy`, `migrate-config`) run
        without `CLAUDE_PROJECT_DIR`, but inside the session's worktree."""
        working_directory = os.getcwd()
        return cls(
            launch_directory=os.environ.get("CLAUDE_PROJECT_DIR") or working_directory,
            working_directory=working_directory,
            repository_layout=GitRepositoryLayout(),
        )

    def project_root(self):
        return self._repository_layout.main_repository_root(self._launch_directory) or self._launch_directory

    def project_config_file(self):
        return self.project_root() / PROJECT_CONFIG_RELATIVE_PATH

    def boundary(self):
        return self._repository_layout.working_tree_root(self._working_directory) or self._launch_directory

    def working_directory(self):
        return self._working_directory

    def path_resolution(self, realpath_predicate=os.path.realpath):
        return PathResolutionContext(
            boundary=self.boundary(),
            working_directory=self._working_directory,
            home=os.path.expanduser("~"),
            exists_predicate=os.path.exists,
            is_directory_predicate=os.path.isdir,
            realpath_predicate=realpath_predicate,
        )
