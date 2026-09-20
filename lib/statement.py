"""Statement: a recursive value object mirroring the shell's own AST nesting.

Replaces today's `walk_ast` (analyze-bash-command.py:874), a generator that
flattens the whole shfmt AST into a stream of every reachable dict node,
discarding nesting and sibling order. Because tree position is lost, callers
like `sole_command_call` and `redirect_targets_of` re-derive structural facts
from the flat stream. A recursive `Statement` owning its sub-statements is a
faithful mirror instead.

CONSTRUCTION: `Statement.from_command(command)` parses `command` via shfmt
and dispatches every raw `Stmt` node it finds to the `Statement` subclass
matching its `Cmd.Type` (`Command` for `CallExpr`, `BinaryCmd`, `Block`,
`Subshell`, `IfClause`, `WhileClause`, `CaseClause`, `ForClause`, `FuncDecl`,
`TimeClause`, `CoprocClause`) - everything else, including any future/unknown
`Cmd.Type`, collapses into `UnrecognizedCmd`, which retains its raw content
and still performs a generic recursive scan of its own attributes so it
cannot silently blind-spot despite lacking named accessors. `CmdSubst` and
`ProcSubst` (`$(...)`, `` `...` ``, `<(...)`, `>(...)`) are the same kind of
"interesting" node but live inside word content (a `CallExpr`'s `Args`, a
redirect's `Word`) rather than the `Stmt`/`Cmd` tree; the same generic scan
that backs `UnrecognizedCmd` also discovers them there, buried arbitrarily
deep in quoting/concatenation.

Generic consumers call `.sub_statements()` uniformly on any Statement,
including `UnrecognizedCmd`. Role-aware consumers use `isinstance()` (e.g.
`isinstance(x, BinaryCmd)`) rather than a parallel Type-string/enum field.

`.redirects`, `.is_backgrounded` and `.is_negated` sit on the base class:
they are properties of the raw `Stmt` node itself, independent of which
`Cmd.Type` (or absence of `Cmd`) occupies it.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess

from redirect_operator import RedirectOperator

_COMPOSITE_CMD_TYPES = frozenset({
    "BinaryCmd",
    "Block",
    "CaseClause",
    "CoprocClause",
    "ForClause",
    "FuncDecl",
    "IfClause",
    "Subshell",
    "TimeClause",
    "WhileClause",
})

_WORD_LEVEL_TYPES = frozenset({"CmdSubst", "ProcSubst"})


class Redirect:
    """One redirect entry of a Stmt's `Redirs` list.

    `target_text` mirrors today's `redirect_targets_of`: the redirect's
    Word recursively unwrapped to its real literal content (see
    `_recursive_text_of_parts`) - a heredoc's Word is its body delimiter,
    not a path, so `is_heredoc` lets consumers exclude it.
    """

    def __init__(self, operator, target_text, is_heredoc):
        self.operator = operator
        self.target_text = target_text
        self.is_heredoc = is_heredoc

    @classmethod
    def from_raw(cls, raw):
        parts = (raw.get("Word") or {}).get("Parts", [])
        target_text = _recursive_text_of_parts(parts)
        return cls(
            operator=RedirectOperator.from_op(raw.get("Op")),
            target_text=target_text,
            is_heredoc="Hdoc" in raw,
        )

    def __eq__(self, other):
        if not isinstance(other, Redirect):
            return NotImplemented
        return (
            self.operator == other.operator
            and self.target_text == other.target_text
            and self.is_heredoc == other.is_heredoc
        )

    def __repr__(self):
        return f"Redirect(operator={self.operator!r}, target_text={self.target_text!r})"


class Statement:
    """The lean base: a raw `Stmt` node's own properties, independent of
    which `Cmd.Type` (or absence of `Cmd`) occupies it. Directly instantiable
    for a commandless statement (`> /etc/passwd`, `Redirs` and no `Cmd`) and
    for a synthetic multi-statement container (a `;`-separated list, whether
    at the top level or as the body of a control-flow construct)."""

    def __init__(
        self,
        redirects=(),
        is_backgrounded=False,
        is_negated=False,
        sub_statements=(),
        raw=None,
        raw_kind=None,
        raw_redirects=(),
    ):
        self._redirects = tuple(redirects)
        self._is_backgrounded = bool(is_backgrounded)
        self._is_negated = bool(is_negated)
        self._sub_statements = tuple(sub_statements)
        self._raw = raw
        self._raw_kind = raw_kind
        self._raw_redirects = tuple(raw_redirects)

    # -- construction -----------------------------------------------------

    @classmethod
    def from_command(cls, command):
        """Parse `command` via shfmt and build its Statement tree, or None
        when shfmt cannot parse it at all (missing binary, non-zero exit,
        timeout, malformed JSON) - mirroring CommandAst's own fail-open
        contract."""
        ast = _parse(command)
        if ast is None:
            return None

        stmts = list(ast.get("Stmts") or ())
        result = _statement_from_stmt_list(stmts)
        if result is not None:
            return result
        return Statement(raw=tuple(stmts), raw_kind="stmt_list")

    # -- base-class surface -------------------------------------------------

    @property
    def redirects(self):
        return self._redirects

    @property
    def is_backgrounded(self):
        return self._is_backgrounded

    @property
    def is_negated(self):
        return self._is_negated

    def sub_statements(self):
        """Every sub-statement, uniform across every subclass: this node's
        own structural children, plus any CmdSubst/ProcSubst buried in a
        redirect's own word content - a redirect's target word (`> "$(...)"`)
        or a heredoc body (`<<EOF\n$(...)\nEOF`) can hide one exactly like a
        CallExpr's Args can, and every subclass carries `Redirs` on the base
        class, so this is handled once here rather than duplicated per
        subclass."""
        return self._own_sub_statements() + _find_embedded_statements(self._raw_redirects)

    def _own_sub_statements(self):
        return self._sub_statements

    # -- derived queries ----------------------------------------------------

    def as_sole_invoked_program(self):
        """The program name when this command line runs exactly one command
        and nothing else, else None.

        None covers every way a second command could be present or hidden: a
        `;`/newline list, `&&`/`||`, a pipeline, a subshell or group, control
        flow, command/process substitution anywhere in the arguments, and a
        backgrounded statement. `.is_negated` is deliberately NOT checked -
        `! some-program true` still counts as a sole invoked program today.
        """
        if not isinstance(self, Command):
            return None
        if self.is_backgrounded:
            return None
        if self.sub_statements():
            return None
        return self.command_word

    def all_redirect_targets(self):
        """The literal file targets of every redirect this statement or any
        sub-statement carries, at any nesting depth - including into
        CmdSubst/ProcSubst subtrees, matching today's `redirect_targets_of`.
        Heredoc redirects are excluded: their Word is the body delimiter, not
        a path."""
        own = tuple(r.target_text for r in self._redirects if not r.is_heredoc)
        nested = tuple(
            target
            for child in self.sub_statements()
            for target in child.all_redirect_targets()
        )
        return own + nested

    def with_heredoc_normalized_to_lit(self):
        """Return a new Statement tree with safe heredoc patterns
        (`$(cat <<'QUOTED_DELIM' ... QUOTED_DELIM)`) transformed to Lit
        nodes, so filter matching doesn't wrongly treat them as command
        substitution. Copy-on-write: deep-copies the raw fragment this
        Statement was built from, transforms it, and rebuilds."""
        if self._raw_kind == "stmt":
            new_raw = copy.deepcopy(self._raw)
            _transform_heredocs_recursive(new_raw)
            return _from_stmt_node(new_raw)
        if self._raw_kind == "word_part":
            new_raw = copy.deepcopy(self._raw)
            _transform_heredocs_recursive(new_raw)
            return _from_word_part(new_raw)
        if self._raw_kind == "stmt_list":
            new_raw = [copy.deepcopy(stmt) for stmt in self._raw]
            for stmt in new_raw:
                _transform_heredocs_recursive(stmt)
            return _statement_from_stmt_list(new_raw) or Statement(
                raw=tuple(new_raw), raw_kind="stmt_list"
            )
        return self


class Argument:
    """One argument a Command passes to the program it invokes (`Args[1:]` -
    `Args[0]` is the command word itself, see `command_word`).

    `text` recursively unwraps the word's Parts to its real literal content
    (see `_recursive_text_of_parts`) - a DblQuoted word carries no `Value` at
    its own top level (its literal content sits one level deeper, in that
    part's own nested Parts), so a naive one-level join would misread it as
    empty. `text` still contributes "" for a ParamExp/CmdSubst/ProcSubst,
    since neither can be statically known - `contains_substitution` is the
    SEPARATE flag a caller uses to detect that unknowable content was
    present at all (the policy pipeline's substitution-unknowability rules,
    leaf 20260914-213652, need this even though the expansion itself is
    invisible to `text`).

    `word_safe` (improvement-20260919-112214) answers a THIRD, independent
    question: is this word guaranteed to expand to exactly one word at
    runtime? A word with no expansion at all is trivially word-safe; an
    expansion stays word-safe only when a `DblQuoted` ancestor encloses THAT
    part - a literal neighbour in the same word confers nothing (`safe$HOME`
    is not word-safe even though `safe` itself is fully knowable). `"$@"` and
    `"${arr[@]}"` are the one exception: they split into multiple words
    despite being double-quoted.
    """

    def __init__(self, text, contains_substitution, referenced_variables=(), word_safe=True):
        self.text = text
        self.contains_substitution = contains_substitution
        self.referenced_variables = frozenset(referenced_variables)
        self.word_safe = word_safe

    @classmethod
    def from_word(cls, word):
        parts = word.get("Parts", [])
        text = _recursive_text_of_parts(parts)
        contains_substitution = any(_word_part_has_substitution(part) for part in parts)
        referenced_variables = [name for part in parts for name in _referenced_variable_names(part)]
        return cls(
            text=text,
            contains_substitution=contains_substitution,
            referenced_variables=referenced_variables,
            word_safe=_word_is_word_safe(parts),
        )

    def __repr__(self):
        return (
            f"Argument(text={self.text!r}, "
            f"contains_substitution={self.contains_substitution!r}, "
            f"referenced_variables={self.referenced_variables!r}, "
            f"word_safe={self.word_safe!r})"
        )


def _recursive_text_of_parts(parts):
    """Recovers a word's (or a redirect target's) real literal text from its
    Parts, unwrapping any part with no `Value` of its own (a DblQuoted word)
    via its own nested Parts - as deep as needed, since a DblQuoted's nested
    Parts can themselves nest further. Contributes "" for anything with
    neither a `Value` nor `Parts` of its own (ParamExp, CmdSubst, ProcSubst)
    - that content cannot be statically known, matching
    `contains_substitution`'s own separate detection of it. Shared by both
    `Argument.from_word` and `Redirect.from_raw`."""
    text = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if "Value" in part:
            text.append(part["Value"])
        else:
            text.append(_recursive_text_of_parts(part.get("Parts") or ()))
    return "".join(text)


def _word_part_has_substitution(part):
    if not isinstance(part, dict):
        return False
    if part.get("Type") in _WORD_LEVEL_TYPES:
        return True
    return any(_word_part_has_substitution(p) for p in part.get("Parts") or ())


def _referenced_variable_names(part):
    """Every `ParamExp` variable name (`$NAME`/`${NAME}`) reachable from
    `part`, recursing into a wrapping DblQuoted's own Parts the same way
    `_word_part_has_substitution` does for CmdSubst/ProcSubst."""
    if not isinstance(part, dict):
        return []
    names = []
    if part.get("Type") == "ParamExp":
        name = (part.get("Param") or {}).get("Value")
        if name:
            names.append(name)
    for nested in part.get("Parts") or ():
        names.extend(_referenced_variable_names(nested))
    return names


def _word_is_word_safe(parts):
    """True when this word is guaranteed to expand to exactly one word -
    see `Argument`'s own docstring for the invariant this backs."""
    return not _has_word_splitting_expansion(parts, inside_double_quotes=False)


def _has_word_splitting_expansion(parts, inside_double_quotes):
    for part in parts or ():
        if not isinstance(part, dict):
            continue
        part_type = part.get("Type")
        if part_type == "DblQuoted":
            if _has_word_splitting_expansion(part.get("Parts") or (), True):
                return True
        elif part_type in _WORD_LEVEL_TYPES:  # CmdSubst / ProcSubst
            if not inside_double_quotes:
                return True
        elif part_type == "ParamExp":
            if _param_exp_always_splits(part) or not inside_double_quotes:
                return True
        elif _has_word_splitting_expansion(part.get("Parts") or (), inside_double_quotes):
            return True
    return False


def _param_exp_always_splits(part):
    """`$@` and `${arr[@]}` split into multiple words even double-quoted -
    the one exception to "a double-quoted expansion is exactly one word"."""
    if (part.get("Param") or {}).get("Value") == "@":
        return True
    index = part.get("Index")
    if isinstance(index, dict) and _recursive_text_of_parts(index.get("Parts") or ()) == "@":
        return True
    return False


class Command(Statement):
    """A `CallExpr`: the leaf that actually invokes a program - or, with an
    empty `Args`, a bare variable assignment (`x=1`, `arr=($(cmd))`).
    `Assigns` is a distinct field from `Args` and can bury a CmdSubst/
    ProcSubst arbitrarily deep (through an array literal, an arithmetic
    expansion, ...), so both are scanned."""

    def __init__(self, args, assigns, **base_kwargs):
        super().__init__(**base_kwargs)
        self._args = tuple(args)
        self._assigns = tuple(assigns)

    @classmethod
    def _build(cls, cmd, base_kwargs):
        return cls(args=cmd.get("Args") or (), assigns=cmd.get("Assigns") or (), **base_kwargs)

    @property
    def command_word(self):
        """The literal program name this CallExpr invokes, or None when the
        command word is not a single plain literal (`$CMD`, `foo$X`, a
        quoted composite)."""
        if not self._args:
            return None
        parts = self._args[0].get("Parts", [])
        if len(parts) != 1 or parts[0].get("Type") != "Lit":
            return None
        return parts[0].get("Value")

    def arguments(self):
        """Every argument passed to the invoked program (excludes the
        command word itself, `Args[0]`) as `Argument` value objects - the
        raw material the policy pipeline's parsers and substitution-
        unknowability rules work from (leaf 20260914-213652)."""
        return tuple(Argument.from_word(word) for word in self._args[1:])

    def _own_sub_statements(self):
        return _find_embedded_statements(self._args) + _find_embedded_statements(self._assigns)


class BinaryCmd(Statement):
    """`a && b`, `a || b`, `a | b`."""

    def __init__(self, left, right, **base_kwargs):
        super().__init__(**base_kwargs)
        self.left = left
        self.right = right

    @classmethod
    def _build(cls, cmd, base_kwargs):
        return cls(
            left=_from_stmt_node(cmd["X"]),
            right=_from_stmt_node(cmd["Y"]),
            **base_kwargs,
        )

    def _own_sub_statements(self):
        return (self.left, self.right)


class _StatementSequence(Statement):
    """Shared shape for `Block` and `Subshell`: a flat list of Stmts."""

    def __init__(self, children, **base_kwargs):
        super().__init__(**base_kwargs)
        self._children = tuple(children)

    @classmethod
    def _build(cls, cmd, base_kwargs):
        children = tuple(_from_stmt_node(s) for s in cmd.get("Stmts") or ())
        return cls(children=children, **base_kwargs)

    def _own_sub_statements(self):
        return self._children


class Block(_StatementSequence):
    """`{ a; b; }`."""


class Subshell(_StatementSequence):
    """`(a; b)`."""


class IfClause(Statement):
    """`if cond; then ...; elif cond; then ...; else ...; fi`.

    shfmt represents `elif`/`else` as a nested Cond/Then/Else-shaped dict
    with no `Type` field of its own - `IfClause` builds itself from that
    same shape recursively, so `.else_branch` is either None or another
    `IfClause` (a bare trailing `else` has no `Cond`, which collapses to
    `.condition is None`)."""

    def __init__(self, condition, then_branch, else_branch, **base_kwargs):
        super().__init__(**base_kwargs)
        self.condition = condition
        self.then_branch = then_branch
        self.else_branch = else_branch

    @classmethod
    def _build(cls, cmd, base_kwargs):
        return cls(**cls._fields_from_node(cmd), **base_kwargs)

    @classmethod
    def _from_node(cls, node):
        """Build an IfClause from a Cond/Then/Else-shaped dict that may lack
        its own `Type` field - the shape shfmt uses for a nested `elif`/`else`
        clause."""
        return cls(**cls._fields_from_node(node))

    @classmethod
    def _fields_from_node(cls, node):
        else_node = node.get("Else")
        return dict(
            condition=_statement_from_stmt_list(node.get("Cond") or ()),
            then_branch=_statement_from_stmt_list(node.get("Then") or ()),
            else_branch=cls._from_node(else_node) if else_node is not None else None,
        )

    def _own_sub_statements(self):
        return tuple(
            s for s in (self.condition, self.then_branch, self.else_branch) if s is not None
        )


class WhileClause(Statement):
    """`while cond; do ...; done`."""

    def __init__(self, loop_condition, loop_body, **base_kwargs):
        super().__init__(**base_kwargs)
        self.loop_condition = loop_condition
        self.loop_body = loop_body

    @classmethod
    def _build(cls, cmd, base_kwargs):
        return cls(
            loop_condition=_statement_from_stmt_list(cmd.get("Cond") or ()),
            loop_body=_statement_from_stmt_list(cmd.get("Do") or ()),
            **base_kwargs,
        )

    def _own_sub_statements(self):
        return tuple(s for s in (self.loop_condition, self.loop_body) if s is not None)


class CaseClause(Statement):
    """`case $word in pattern) ...;; esac`."""

    def __init__(self, word, item_bodies, patterns, **base_kwargs):
        super().__init__(**base_kwargs)
        self._word = word
        self._item_bodies = tuple(item_bodies)
        self._patterns = tuple(patterns)

    @classmethod
    def _build(cls, cmd, base_kwargs):
        items = cmd.get("Items") or ()
        return cls(
            word=cmd.get("Word"),
            item_bodies=tuple(
                _statement_from_stmt_list(item.get("Stmts") or ()) for item in items
            ),
            patterns=tuple(pattern for item in items for pattern in item.get("Patterns") or ()),
            **base_kwargs,
        )

    def _own_sub_statements(self):
        bodies = tuple(s for s in self._item_bodies if s is not None)
        embedded = _find_embedded_statements(self._word) + _find_embedded_statements(
            self._patterns
        )
        return bodies + embedded


class ForClause(Statement):
    """`for x in ...; do ...; done` / `for ((...)); do ...; done`."""

    def __init__(self, loop_body, loop, **base_kwargs):
        super().__init__(**base_kwargs)
        self.loop_body = loop_body
        self._loop = loop

    @classmethod
    def _build(cls, cmd, base_kwargs):
        return cls(
            loop_body=_statement_from_stmt_list(cmd.get("Do") or ()),
            loop=cmd.get("Loop"),
            **base_kwargs,
        )

    def _own_sub_statements(self):
        body = (self.loop_body,) if self.loop_body is not None else ()
        return body + _find_embedded_statements(self._loop)


class _SingleChildStatement(Statement):
    """Shared shape for a construct wrapping exactly one optional
    Statement: `FuncDecl.Body`, `TimeClause.Stmt`, `CoprocClause.Stmt`,
    and `CmdSubst`/`ProcSubst`'s own nested statement."""

    _CHILD_ATTR = "wrapped_statement"

    def __init__(self, child, **base_kwargs):
        super().__init__(**base_kwargs)
        setattr(self, self._CHILD_ATTR, child)

    def _own_sub_statements(self):
        child = getattr(self, self._CHILD_ATTR)
        return (child,) if child is not None else ()


class FuncDecl(_SingleChildStatement):
    """`name() { ...; }`."""

    _CHILD_ATTR = "body"

    @classmethod
    def _build(cls, cmd, base_kwargs):
        body = cmd.get("Body")
        return cls(child=_from_stmt_node(body) if body is not None else None, **base_kwargs)


class TimeClause(_SingleChildStatement):
    """`time [-p] pipeline` - bare `time` has no wrapped statement."""

    @classmethod
    def _build(cls, cmd, base_kwargs):
        stmt = cmd.get("Stmt")
        return cls(child=_from_stmt_node(stmt) if stmt is not None else None, **base_kwargs)


class CoprocClause(_SingleChildStatement):
    """`coproc [NAME] command`."""

    @classmethod
    def _build(cls, cmd, base_kwargs):
        stmt = cmd.get("Stmt")
        return cls(child=_from_stmt_node(stmt) if stmt is not None else None, **base_kwargs)


class CmdSubst(_SingleChildStatement):
    """`$(...)` / `` `...` `` - lives inside word content, not the Stmt/Cmd
    tree, so it is built via `_from_word_part`, never `_from_stmt_node`."""

    @classmethod
    def _from_raw_word_part(cls, raw):
        return cls(child=_statement_from_stmt_list(raw.get("Stmts") or ()), raw=raw, raw_kind="word_part")


class ProcSubst(_SingleChildStatement):
    """`<(...)` / `>(...)`."""

    @classmethod
    def _from_raw_word_part(cls, raw):
        return cls(child=_statement_from_stmt_list(raw.get("Stmts") or ()), raw=raw, raw_kind="word_part")


class UnrecognizedCmd(Statement):
    """The catch-all for a `Cmd.Type` this leaf does not model individually
    (today: `ArithmCmd`, `DeclClause`, `LetClause`, `TestClause` - none nest
    a Stmt). Retains its raw Type and raw content for diagnostics, and its
    `sub_statements()` is a blind, key-agnostic recursive scan of its own
    attributes - structurally identical to today's `walk_ast` - so a future
    shfmt release introducing a new nesting shape cannot silently blind-spot
    it."""

    def __init__(self, cmd_type, raw_cmd, **base_kwargs):
        super().__init__(**base_kwargs)
        self.cmd_type = cmd_type
        self.raw_cmd = raw_cmd

    @classmethod
    def _build(cls, cmd, base_kwargs):
        return cls(cmd_type=cmd.get("Type"), raw_cmd=cmd, **base_kwargs)

    def _own_sub_statements(self):
        return _find_embedded_statements(self.raw_cmd)


_BUILDER_BY_CMD_TYPE = {
    "CallExpr": Command._build,
    "BinaryCmd": BinaryCmd._build,
    "Block": Block._build,
    "Subshell": Subshell._build,
    "IfClause": IfClause._build,
    "WhileClause": WhileClause._build,
    "CaseClause": CaseClause._build,
    "ForClause": ForClause._build,
    "FuncDecl": FuncDecl._build,
    "TimeClause": TimeClause._build,
    "CoprocClause": CoprocClause._build,
}

_WORD_PART_BUILDER_BY_TYPE = {
    "CmdSubst": CmdSubst._from_raw_word_part,
    "ProcSubst": ProcSubst._from_raw_word_part,
}


def _from_stmt_node(raw_stmt):
    """Build the Statement for ONE raw `Stmt` node - the single dispatch
    point used everywhere a raw Stmt dict is encountered, whether from the
    top-level File, a composite subclass's own nested Stmts, or the generic
    scan's shim for a bare (non-Stmt-wrapped) Cmd node."""
    raw_redirects = raw_stmt.get("Redirs") or ()
    base_kwargs = dict(
        redirects=tuple(Redirect.from_raw(r) for r in raw_redirects),
        is_backgrounded=bool(raw_stmt.get("Background")),
        is_negated=bool(raw_stmt.get("Negated")),
        raw=raw_stmt,
        raw_kind="stmt",
        raw_redirects=raw_redirects,
    )

    cmd = raw_stmt.get("Cmd")
    if cmd is None:
        return Statement(**base_kwargs)

    builder = _BUILDER_BY_CMD_TYPE.get(cmd.get("Type"), UnrecognizedCmd._build)
    return builder(cmd, base_kwargs)


def _from_word_part(raw):
    """Build the CmdSubst/ProcSubst Statement for one raw word-part dict."""
    return _WORD_PART_BUILDER_BY_TYPE[raw.get("Type")](raw)


def _statement_from_stmt_list(stmts):
    """Turn a raw list of `Stmt` nodes into ONE Statement: None for an empty
    list, the single element unwrapped for one, or a synthetic multi-item
    `Statement` container otherwise. The canonical way any `;`-separated
    list becomes a Statement - the top-level File.Stmts, an IfClause's own
    Cond/Then, a WhileClause's Cond/Do, and so on."""
    stmts = list(stmts or ())
    if not stmts:
        return None
    if len(stmts) == 1:
        return _from_stmt_node(stmts[0])
    return Statement(
        sub_statements=tuple(_from_stmt_node(s) for s in stmts),
        raw=tuple(stmts),
        raw_kind="stmt_list",
    )


def _find_embedded_statements(value):
    """Blind, key-agnostic recursive scan for Statement-shaped content buried
    anywhere in `value` - the fixed 'interesting type' set (the ten composite
    Cmd.Types, `CallExpr`, `CmdSubst`, `ProcSubst`). Structurally identical to
    today's `walk_ast`; used both as UnrecognizedCmd's generic fallback and as
    the way any node with free-form word content (a CallExpr's Args, a
    CaseClause's Word/Patterns, a ForClause's Loop) discovers CmdSubst/
    ProcSubst embedded arbitrarily deep in quoting/concatenation.

    Stops descending the instant it matches, handing reconstruction off to
    the match's own Statement construction rather than continuing to walk
    past it into the matched node's own children - the constructed
    Statement's own `.sub_statements()` covers anything nested further
    inside it.
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            node_type = node.get("Type")
            if node_type in _WORD_LEVEL_TYPES:
                found.append(_from_word_part(node))
                return
            if node_type in _BUILDER_BY_CMD_TYPE:
                found.append(_from_stmt_node({"Cmd": node}))
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(value)
    return tuple(found)


def _parse(command):
    """Parse a bash command string to its shfmt JSON AST, or None on any
    failure - binary missing, non-zero exit, timeout, malformed JSON."""
    if not shutil.which("shfmt"):
        return None
    try:
        result = subprocess.run(
            ["shfmt", "-tojson"],
            input=command,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


# =============================================================================
# Heredoc-as-string-literal normalization
# =============================================================================
#
# Ported from CommandAst.with_heredoc_normalized_to_lit (analyze-bash-command.py:1160),
# operating on a raw AST fragment in place. Recognizes exactly one shape:
# $(cat <<'QUOTED_DELIM' ... QUOTED_DELIM) - a quoted delimiter prevents variable
# expansion, and `cat` with no other args and no pipe means the CmdSubst is
# semantically just a string literal, not real command substitution.


def _transform_heredocs_recursive(node):
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, dict) and _is_safe_cat_heredoc_pattern(value):
                node[key] = _create_lit_from_heredoc(value)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict) and _is_safe_cat_heredoc_pattern(item):
                        value[i] = _create_lit_from_heredoc(item)
                    else:
                        _transform_heredocs_recursive(item)
            else:
                _transform_heredocs_recursive(value)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            if isinstance(item, dict) and _is_safe_cat_heredoc_pattern(item):
                node[i] = _create_lit_from_heredoc(item)
            else:
                _transform_heredocs_recursive(item)


def _is_safe_cat_heredoc_pattern(node):
    if node.get("Type") != "CmdSubst":
        return False

    stmts = node.get("Stmts", [])
    if len(stmts) != 1:
        return False

    stmt = stmts[0]
    cmd = stmt.get("Cmd", {})
    if cmd.get("Type") != "CallExpr":
        return False

    args = cmd.get("Args", [])
    if not args:
        return False
    first_parts = args[0].get("Parts", [])
    if not first_parts or first_parts[0].get("Type") != "Lit" or first_parts[0].get("Value") != "cat":
        return False
    if len(args) != 1:
        return False

    redirs = stmt.get("Redirs", [])
    if len(redirs) != 1:
        return False
    redir = redirs[0]
    hdoc = redir.get("Hdoc")
    if hdoc is None:
        return False

    word_parts = redir.get("Word", {}).get("Parts", [])
    if not word_parts or word_parts[0].get("Type") not in ("SglQuoted", "DblQuoted"):
        return False

    for part in hdoc.get("Parts", []):
        if not isinstance(part, dict) or part.get("Type") != "Lit":
            return False

    return True


def _create_lit_from_heredoc(cmd_subst):
    stmt = cmd_subst["Stmts"][0]
    hdoc = stmt["Redirs"][0]["Hdoc"]
    content = "".join(part.get("Value", "") for part in hdoc.get("Parts", []))
    return {
        "Type": "Lit",
        "Pos": cmd_subst.get("Pos", {}),
        "End": cmd_subst.get("End", {}),
        "ValuePos": cmd_subst.get("Pos", {}),
        "ValueEnd": cmd_subst.get("End", {}),
        "Value": content,
    }
