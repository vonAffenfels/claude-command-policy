"""Pure I/O loader composing the command-policy config's three layers.

Reads and JSON-parses the user and project config files and composes them via
`Config.defaults().merged_with(user).merged_with(project)` - it carries NO
merge semantics of its own (see config.py's module docstring for where that
lives). A present-but-unparseable file becomes a warning naming that file; an
absent file is the normal case and produces no warning at all.

Each layer also records whether its file was found at all, via
`LayerPresence` (attached with `Config.with_layer_presence`) - this is the
one fact `Config.from_dict` cannot know on its own, since a raw dict looks
identical whether it came from an absent file (`Config.defaults()`) or a
present-but-empty one (`{}`). See layer_presence.py's module docstring.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from config import Config
from layer_presence import LayerPresence
from warning_value import Warning
from workspace import Workspace

USER_CONFIG_RELATIVE_PATH = Path(".claude") / "command-policy.json"


def load_config(user_config_path, project_config_path, path_resolution=None):
    context = path_resolution or Workspace.of_this_session().path_resolution()
    return (
        Config.defaults(path_resolution=context)
        .merged_with(_load_layer(user_config_path, layer="user", path_resolution=context))
        .merged_with(_load_layer(project_config_path, layer="project", path_resolution=context))
    )


def load_config_from_environment():
    """The project layer is `Workspace`'s project config file - the MAIN
    repository's, whichever worktree the session runs in (workspace.py)."""
    home = Path(os.environ.get("HOME", ""))
    workspace = Workspace.of_this_session()

    return load_config(
        home / USER_CONFIG_RELATIVE_PATH,
        workspace.project_config_file(),
        path_resolution=workspace.path_resolution(),
    )


def _load_layer(path, layer, path_resolution):
    path = Path(path)
    found = path.exists()
    presence = LayerPresence.of(layer, str(path), found=found)

    if not found:
        return Config.defaults(path_resolution=path_resolution).with_layer_presence(presence)

    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Config(
            warnings=(Warning.unparseable_config_file(layer=layer, path=str(path)),),
            layer_presence=presence,
            path_resolution=path_resolution,
        )

    return Config.from_dict(raw, source=layer, path_resolution=path_resolution).with_layer_presence(presence)
