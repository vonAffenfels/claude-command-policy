"""RepositoryLayout: the two questions `Workspace` asks about where a
directory sits in git - which main repository it belongs to, and which
working tree (main checkout or linked worktree) contains it.

`RepositoryLayout` is the port; `GitRepositoryLayout` is the ONLY place in
command-policy that runs `git`, the same DI seam shape as
`ExternalParserFactory` for parser subprocesses. Rules that need these
answers receive a layout instead of shelling out, so they are exercised with
an in-memory layout and no `git` at all (tests/test_workspace.py).

Both questions answer `None` outside a repository AND on any `git` failure
(missing executable, a directory that does not exist): every caller treats
`None` as "not a repository" and falls back to the `CLAUDE_PROJECT_DIR`-based
behaviour, so an absent `git` degrades instead of erroring.

The main repository is asked of `git` rather than inferred from a linked
worktree's `.git` file (`gitdir: ...`) - see the improvement-20261019-095449
design decision "How the main repository is found".
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Protocol

# Set by git itself while running a git hook; they would answer for THAT
# repository instead of for the directory actually asked about.
_REPOSITORY_OVERRIDING_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")


class RepositoryLayout(Protocol):
    def main_repository_root(self, directory) -> Optional[Path]: ...

    def working_tree_root(self, directory) -> Optional[Path]: ...


class GitRepositoryLayout:
    def __init__(self, git_executable="git"):
        self._git_executable = git_executable

    def main_repository_root(self, directory):
        """First `worktree` entry of the porcelain worktree listing - git
        always lists the main working tree first."""
        listing = self._git_output(directory, "worktree", "list", "--porcelain")
        if listing is None:
            return None
        for line in listing.splitlines():
            if line.startswith("worktree "):
                return Path(line[len("worktree "):])
        return None

    def working_tree_root(self, directory):
        toplevel = self._git_output(directory, "rev-parse", "--show-toplevel")
        if not toplevel:
            return None
        return Path(toplevel.strip())

    def _git_output(self, directory, *args):
        environment = {
            name: value for name, value in os.environ.items() if name not in _REPOSITORY_OVERRIDING_VARIABLES
        }
        try:
            result = subprocess.run(
                [self._git_executable, "-C", str(directory), *args],
                capture_output=True,
                text=True,
                env=environment,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout
