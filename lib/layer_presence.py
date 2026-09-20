"""LayerPresence: per-layer record of which config path was searched and
whether a file actually existed there.

config_loader.py's `_load_layer` used to test `path.exists()` and discard
the answer, returning `Config.defaults()` either way - byte-identical for
"no file at this scope" and "a file exists here but is empty". This value
object carries the fact `_load_layer` already computes so `Config.explain()`
can tell the two states apart, following the package's existing style
(name_collection.py/path_config.py): a plain, pure record threaded through
`Config` via a wither, unioned on merge like every other collection - never
read from the filesystem at explain() time, since that would make explain()
untestable without real files on disk and would put I/O back in config.py,
which the package deliberately keeps free of it (see config.py's module
docstring).
"""

from __future__ import annotations

MIGRATE_CONFIG_POINTER = (
    "if you are migrating from shfmt-permissions, see command-policy:migrate-config"
)


class LayerSearch:
    def __init__(self, layer, path, found):
        self.layer = layer
        self.path = path
        self.found = found

    def __eq__(self, other):
        if not isinstance(other, LayerSearch):
            return NotImplemented
        return (self.layer, self.path, self.found) == (other.layer, other.path, other.found)

    def __hash__(self):
        return hash((self.layer, self.path, self.found))

    def __repr__(self):
        return f"LayerSearch(layer={self.layer!r}, path={self.path!r}, found={self.found!r})"


class LayerPresence:
    def __init__(self, searches=()):
        self._searches = tuple(searches)

    @classmethod
    def empty(cls):
        return cls()

    @classmethod
    def of(cls, layer, path, found):
        return cls((LayerSearch(layer, path, found),))

    def union(self, other):
        return LayerPresence(self._searches + other._searches)

    def any_found(self):
        return any(search.found for search in self._searches)

    def explain(self):
        """Silent (empty string) unless there is at least one recorded
        search AND none of them found a file - the ordinary case (nothing
        recorded, or at least one layer present) gains no noise, matching
        this improvement's success criteria."""
        if not self._searches or self.any_found():
            return ""
        paths = ", ".join(search.path for search in self._searches)
        return (
            f"No command-policy.json config file found at either scope (searched: {paths}). "
            f"Deny-by-default is in effect with an empty config - {MIGRATE_CONFIG_POINTER}, or "
            "add-allow-policy to start allow-listing commands."
        )

    def __eq__(self, other):
        if not isinstance(other, LayerPresence):
            return NotImplemented
        return self._searches == other._searches

    def __hash__(self):
        return hash(self._searches)

    def __repr__(self):
        return f"LayerPresence({self._searches!r})"
