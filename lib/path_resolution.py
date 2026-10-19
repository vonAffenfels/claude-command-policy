"""PathResolutionContext: an injected stand-in for the ambient
os.path.exists()/os.path.abspath()/os.path.expanduser()/os.path.realpath()
reads `DefaultParser`/`StructuredParser` path detection and `PathsFilter`
normalization perform today, so both are exercisable against declared state
instead of a real filesystem or the real process cwd.

`for_process()` is the one place this module reads real ambient state - the
same DI seam shape as `ExternalParserFactory` for subprocess execution. The
production context comes from `Workspace.path_resolution()` (workspace.py),
which knows the session's boundary and working directory.

Two anchors for a relative path, named by WHOSE path it is (improvement-
20261019-095449): `absolute_path_of_command_argument` resolves against the
working directory (where the command runs - it follows Bash `cd`), and
`absolute_path_of_config_entry` against the boundary root (a config entry's
meaning must not depend on where the session happens to stand). Containment
is always checked against the boundary.

Both resolve symlinks (via the injected `realpath_predicate`, non-strict
`os.path.realpath` in production) on top of the lexical join/expansion - the
sole seam every path-boundary consumer shares, so redirect validation,
`allowedCommands` argument-path validation, `PathsFilter`, and
`decision_for_path` all resolve symlinks uniformly with no per-consumer
change (improvement-20260918-185726). `is_contained` resolves BOTH sides of
every containment check - the candidate (already realpath'd) and the
boundary (realpath'd once at construction, plus every `allowed_prefixes`
entry, routed through `absolute_path_of_config_entry`) - so a symlinked
project root or a symlinked `additionalAllowedPathPrefixes` entry does not
produce a false denial.

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
        boundary,
        working_directory=None,
        home=None,
        exists_predicate=None,
        is_directory_predicate=None,
        realpath_predicate=None,
    ):
        self._realpath = realpath_predicate or (lambda path: path)
        self._boundary = self._realpath(str(boundary))
        self._working_directory = (
            self._boundary if working_directory is None else self._realpath(str(working_directory))
        )
        self._home = home
        self._exists = exists_predicate or (lambda path: False)
        self._is_directory = is_directory_predicate or (lambda path: False)

    @classmethod
    def for_process(cls):
        return cls(
            boundary=os.getcwd(),
            home=os.path.expanduser("~"),
            exists_predicate=os.path.exists,
            is_directory_predicate=os.path.isdir,
            realpath_predicate=os.path.realpath,
        )

    def absolute_path_of_command_argument(self, value):
        """A path written in a COMMAND (argument, redirect target, a
        Read/Grep/Glob target) - relative to where the command runs."""
        return self._realpath(self._lexical_absolute_path_of(value, anchor=self._working_directory))

    def absolute_path_of_config_entry(self, value):
        """A path written in the CONFIG (`paths` `exactly`, an allowedPaths
        rule, an `additionalAllowedPathPrefixes` entry) - relative to the
        boundary root, so its meaning does not drift with `cd`."""
        return self._realpath(self._lexical_absolute_path_of(value, anchor=self._boundary))

    def _lexical_absolute_path_of(self, value, anchor):
        if value.startswith("~"):
            expanded = self._expand_home(value)
            return os.path.normpath(expanded)
        if value.startswith("/"):
            return os.path.normpath(value)
        return os.path.normpath(os.path.join(anchor, value))

    def _expand_home(self, value):
        if self._home is None:
            return value
        return self._home + value[1:] if value == "~" or value.startswith("~/") else value

    def exists(self, value):
        return self._exists(value)

    def is_directory(self, value):
        return self._is_directory(value)

    def is_contained(self, absolute_path, allowed_prefixes=()):
        """Whether `absolute_path` sits inside this context's boundary (the
        working tree the session is in - see workspace.py) or one of
        `allowed_prefixes`. Never the working directory: a `cd` into a
        subdirectory does not shrink the boundary.

        Guards against a near-miss sibling directory (`/home/user` must not
        admit `/home/username`) via the trailing-separator comparison.
        """
        candidates = (self._boundary,) + tuple(self.absolute_path_of_config_entry(prefix) for prefix in allowed_prefixes)
        return any(_is_within(absolute_path, prefix) for prefix in candidates)


def _is_within(path, prefix):
    return path == prefix or path.startswith(prefix + os.sep)
