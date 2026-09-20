"""RedirectPathValidationPolicy: Pass 4 (formerly enumerated as Pass 3 in
the plan; see pass_.py for the sixth-pass renumbering).

Independent of which allowedCommands entry vouches - `hasNoPathParameters`
on an entry does NOT disable this (Flag List B4 part 2): a redirect is
performed by the calling SHELL before the wrapped program ever starts, so no
entry can legitimately vouch for it. Every redirect target anywhere in the
statement (`Statement.all_redirect_targets()` already walks every sub-
statement) must resolve inside the project or an `additionalAllowedPathPrefixes`
entry; an empty or otherwise-unresolvable target NEVER falls back to cwd
(Flag List F2) - it denies directly, without being resolved at all.
"""

from __future__ import annotations

from pass_ import Pass
from permission_decision import PermissionDecision
from policy import Policy
from reason import RedirectOutsideAllowedPaths


class RedirectPathValidationPolicy(Policy):
    pass_ = Pass.REDIRECT_PATH_VALIDATION

    def __init__(self, path_resolution, allowed_prefixes):
        super().__init__()
        self._path_resolution = path_resolution
        self._allowed_prefixes = allowed_prefixes

    def _offending_targets(self):
        offending = []
        for target in self.statement.all_redirect_targets():
            if not target:
                offending.append(target)
                continue
            absolute = self._path_resolution.absolute_path_of(target)
            if not self._path_resolution.is_contained(absolute, self._allowed_prefixes):
                offending.append(target)
        return offending

    def matches(self):
        return bool(self._offending_targets())

    def decision(self):
        return PermissionDecision.deny(
            tuple(RedirectOutsideAllowedPaths(target) for target in self._offending_targets())
        )
