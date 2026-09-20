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

USER_CONFIG_RELATIVE_PATH = Path(".claude") / "command-policy.json"
PROJECT_CONFIG_RELATIVE_PATH = Path(".claude") / "command-policy.json"


def load_config(user_config_path, project_config_path):
    return (
        Config.defaults()
        .merged_with(_load_layer(user_config_path, layer="user"))
        .merged_with(_load_layer(project_config_path, layer="project"))
    )


def load_config_from_environment():
    home = Path(os.environ.get("HOME", ""))
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))

    return load_config(
        home / USER_CONFIG_RELATIVE_PATH,
        project_dir / PROJECT_CONFIG_RELATIVE_PATH,
    )


def _load_layer(path, layer):
    path = Path(path)
    found = path.exists()
    presence = LayerPresence.of(layer, str(path), found=found)

    if not found:
        return Config.defaults().with_layer_presence(presence)

    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Config(
            warnings=(Warning.unparseable_config_file(layer=layer, path=str(path)),),
            layer_presence=presence,
        )

    return Config.from_dict(raw, source=layer).with_layer_presence(presence)
