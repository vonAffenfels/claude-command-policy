"""ParsedOption, ParsedPositional, ParsedResult: the Parser output shape.

Dissolves the old shared `paths` bag - one list feeding two unrelated
consumers, `_check_path_validation` and `PathsFilter` - into two
independently-named fields, so a future divergence in path-detection logic
for one consumer is a visible one-line change rather than a silent
cross-effect on the other.
"""

from __future__ import annotations


class ParsedOption:
    def __init__(self, name, arguments=()):
        self.name = name
        self.arguments = tuple(arguments)

    def __repr__(self):
        return f"ParsedOption(name={self.name!r}, arguments={self.arguments!r})"


class ParsedPositional:
    def __init__(self, index, value):
        self.index = index
        self.value = value

    def __repr__(self):
        return f"ParsedPositional(index={self.index!r}, value={self.value!r})"


class NestedCommand:
    """One entry of a parser's `nestedCommands` channel: a sub-command the
    wrapper (xargs, nix-shell, timeout, ...) will itself invoke, published as
    text plus a declared SHAPE so the engine - never the parser - performs
    the shfmt parse (leaf 20260914-213652's 'Parsers publish sub-commands on
    a dedicated channel' design decision). `shape` is "argv" (a list of
    already-split words, safe to shlex.join) or "shell" (a shell-syntax
    string, parsed as-is) - getting this backwards is asymmetric and unsafe
    in one direction (see that decision's rationale), so it is carried
    explicitly rather than inferred from the value's Python type.
    """

    def __init__(self, text, shape):
        self.text = text
        self.shape = shape

    def __repr__(self):
        return f"NestedCommand(text={self.text!r}, shape={self.shape!r})"


class ParsedResult:
    def __init__(
        self,
        options=(),
        positionals=(),
        subcommand=None,
        named=None,
        paths_for_validation=(),
        paths_for_filtering=(),
        nested_commands=(),
    ):
        self.options = tuple(options)
        self.positionals = tuple(positionals)
        self.subcommand = subcommand
        self.named = dict(named or {})
        self.paths_for_validation = tuple(paths_for_validation)
        self.paths_for_filtering = tuple(paths_for_filtering)
        self.nested_commands = tuple(nested_commands)

    def all_argument_texts(self):
        texts = []
        for option in self.options:
            texts.append(option.name)
            texts.extend(option.arguments)
        for positional in self.positionals:
            texts.append(positional.value)
        return texts

    def positional_values(self):
        return [positional.value for positional in self.positionals]

    def __repr__(self):
        return (
            f"ParsedResult(options={self.options!r}, positionals={self.positionals!r}, "
            f"named={self.named!r})"
        )
