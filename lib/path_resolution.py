"""PathResolutionContext: an injected stand-in for the ambient
os.path.exists()/os.path.abspath()/os.path.expanduser()/os.path.realpath()
reads `DefaultParser`/`StructuredParser` path detection and `PathsFilter`
normalization perform today, so both are exercisable against declared state
instead of a real filesystem or the real process cwd.

`for_process()` is the one place this module reads real ambient state - the
same DI seam shape as `ExternalParserFactory` for subprocess execution.

`absolute_path_of` resolves symlinks (via the injected `realpath_predicate`,
non-strict `os.path.realpath` for `for_process()`) on top of the lexical
join/expansion - the sole seam every path-boundary consumer shares
(`Config._path_resolution()`), so redirect validation, `allowedCommands`
argument-path validation, `PathsFilter`, and `decision_for_path` all resolve
symlinks uniformly with no per-consumer change (improvement-20260918-185726).
`is_contained` resolves BOTH sides of every containment check - the
candidate (already realpath'd by `absolute_path_of`) and the boundary
(`_cwd`, realpath'd once at construction, plus every `allowed_prefixes`
entry, routed through `absolute_path_of` too) - so a symlinked project root
or a symlinked `additionalAllowedPathPrefixes` entry does not produce a
false denial.

TOCTOU: resolution happens once, at decision time, and the command executes
afterward as a separate step - this is NOT atomic with execution. A symlink
created, swapped, or removed in the window between the decision and the
command actually running is not caught by this or any check this engine
performs. This closes the STATIC symlink-escape gap (a symlink already in
place, unchanged, at decision time); it does not and cannot make the check
atomic with execution.

Non-strict `os.path.realpath` needs no special-casing for a not-yet-existing
leaf, a dangling symlink, a symlink loop, or a self-referencing symlink - it
resolves all of them with no exception (confirmed live; see the improvement
file's Assumptions section). Only `strict=True`, which this design never
uses, can raise `OSError`.
"""

from __future__ import annotations

import os


class PathResolutionContext:
    def __init__(
        self,
        cwd,
        home=None,
        exists_predicate=None,
        is_directory_predicate=None,
        realpath_predicate=None,
    ):
        self._realpath = realpath_predicate or (lambda path: path)
        self._cwd = self._realpath(cwd)
        self._home = home
        self._exists = exists_predicate or (lambda path: False)
        self._is_directory = is_directory_predicate or (lambda path: False)

    @classmethod
    def for_process(cls):
        return cls(
            cwd=os.getcwd(),
            home=os.path.expanduser("~"),
            exists_predicate=os.path.exists,
            is_directory_predicate=os.path.isdir,
            realpath_predicate=os.path.realpath,
        )

    def absolute_path_of(self, value):
        return self._realpath(self._lexical_absolute_path_of(value))

    def _lexical_absolute_path_of(self, value):
        if value.startswith("~"):
            expanded = self._expand_home(value)
            return os.path.normpath(expanded)
        if value.startswith("/"):
            return os.path.normpath(value)
        return os.path.normpath(os.path.join(self._cwd, value))

    def _expand_home(self, value):
        if self._home is None:
            return value
        return self._home + value[1:] if value == "~" or value.startswith("~/") else value

    def exists(self, value):
        return self._exists(value)

    def is_directory(self, value):
        return self._is_directory(value)

    def is_contained(self, absolute_path, allowed_prefixes=()):
        """Whether `absolute_path` sits inside this context's own root (its
        `cwd`, treated as the project boundary - see config.py's
        decision_for, which constructs this context rooted at
        CLAUDE_PROJECT_DIR) or one of `allowed_prefixes`.

        Guards against a near-miss sibling directory (`/home/user` must not
        admit `/home/username`) via the trailing-separator comparison.
        """
        candidates = (self._cwd,) + tuple(self.absolute_path_of(prefix) for prefix in allowed_prefixes)
        return any(_is_within(absolute_path, prefix) for prefix in candidates)


def _is_within(path, prefix):
    return path == prefix or path.startswith(prefix + os.sep)
