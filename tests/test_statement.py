"""Unit tests for the Statement value-object hierarchy.

Statement.from_command(command) parses `command` via shfmt and dispatches
every raw Stmt node to the subclass matching its Cmd.Type. These tests pin
the dispatch table, the uniform sub_statements() surface (including the
UnrecognizedCmd/generic-scan safety net), the base-class Redirs/Background/
Negated surface, and the derived queries (as_sole_invoked_program,
all_redirect_targets, with_heredoc_normalized_to_lit) against the exact
behaviour analyze-bash-command.py's walk_ast-based free functions establish
today.
"""

import pytest

from statement import (
    BinaryCmd,
    Block,
    CaseClause,
    CmdSubst,
    Command,
    CoprocClause,
    ForClause,
    FuncDecl,
    IfClause,
    ProcSubst,
    Statement,
    Subshell,
    TimeClause,
    UnrecognizedCmd,
    WhileClause,
)


def _all_nested(statement):
    """Every Statement in the tree rooted at `statement`, depth-first."""
    yield statement
    for child in statement.sub_statements():
        yield from _all_nested(child)


class TestDispatchToSubclass:
    """Statement.from_command() dispatches to the subclass matching the raw
    Cmd.Type - equivalent to REDIRECT_NESTING_SHAPES for construction."""

    DISPATCH_TABLE = [
        ("echo hello", Command),
        ("a && b", BinaryCmd),
        ("a | b", BinaryCmd),
        ("{ cat a; }", Block),
        ("(cat a)", Subshell),
        ("if true; then cat a; fi", IfClause),
        ("while read l; do cat a; done", WhileClause),
        ("case $x in a) cat a;; esac", CaseClause),
        ("for i in a b; do cat $i; done", ForClause),
        ("func_name() { cat a; }", FuncDecl),
        ("time cat a", TimeClause),
        ("coproc cat a", CoprocClause),
        ("((1+1))", UnrecognizedCmd),
        ("declare x=1", UnrecognizedCmd),
        ("let x=1", UnrecognizedCmd),
        ("[[ -f a ]]", UnrecognizedCmd),
    ]

    @pytest.mark.parametrize("command, expected_class", DISPATCH_TABLE, ids=[c for c, _ in DISPATCH_TABLE])
    def test_dispatches_to_the_correct_subclass(self, command, expected_class):
        statement = Statement.from_command(command)

        assert type(statement) is expected_class

    def test_a_bare_variable_assignment_is_a_command_with_no_command_word(self):
        statement = Statement.from_command("x=1")

        assert type(statement) is Command
        assert statement.command_word is None

    def test_parse_failure_returns_none(self):
        assert Statement.from_command("if then else fi (broken") is None


class TestUnrecognizedCmdGenericScan:
    """UnrecognizedCmd is the catch-all for a Cmd.Type this leaf does not
    model individually. It must retain diagnostic info and never silently
    blind-spot a nested Statement, even for a type that does not exist
    today."""

    @pytest.mark.parametrize(
        "command, cmd_type",
        [
            ("((1+1))", "ArithmCmd"),
            ("declare x=1", "DeclClause"),
            ("let x=1", "LetClause"),
            ("[[ -f a ]]", "TestClause"),
        ],
    )
    def test_todays_four_inhabitants_report_zero_sub_statements(self, command, cmd_type):
        statement = Statement.from_command(command)

        assert isinstance(statement, UnrecognizedCmd)
        assert statement.cmd_type == cmd_type
        assert statement.sub_statements() == ()

    def test_a_synthetic_unrecognized_type_that_nests_a_stmt_is_still_found(self):
        """Proves the generic scan isn't just accidentally correct for
        today's four Stmt-less cases: a hand-built raw Cmd dict for a
        Cmd.Type that does not exist in shfmt today, nesting a real Stmt
        under a novel field name, must still surface that Stmt."""
        raw_cmd = {
            "Type": "FutureClause",
            "Body": [
                {
                    "Cmd": {
                        "Type": "CallExpr",
                        "Args": [{"Parts": [{"Type": "Lit", "Value": "echo"}]}],
                    }
                }
            ],
        }
        from statement import _from_stmt_node

        statement = _from_stmt_node({"Cmd": raw_cmd})

        assert isinstance(statement, UnrecognizedCmd)
        sub = statement.sub_statements()
        assert len(sub) == 1
        assert isinstance(sub[0], Command)
        assert sub[0].command_word == "echo"


class TestEmbeddedSubstitutionDiscovery:
    """The generic word-scan finds CmdSubst/ProcSubst buried arbitrarily
    deep in word construction - the 9 shapes verified live against shfmt
    3.13.1 during planning."""

    def test_backtick_substitution_in_call_expr_args(self):
        statement = Statement.from_command("echo `cat a`")

        sub = statement.sub_statements()
        assert len(sub) == 1
        assert isinstance(sub[0], CmdSubst)

    def test_dollar_paren_substitution_in_call_expr_args(self):
        statement = Statement.from_command("echo $(cat a)")

        assert len(statement.sub_statements()) == 1
        assert isinstance(statement.sub_statements()[0], CmdSubst)

    def test_process_substitution_in_call_expr_args(self):
        statement = Statement.from_command("diff <(cat a) <(cat b)")

        sub = statement.sub_statements()
        assert len(sub) == 2
        assert all(isinstance(s, ProcSubst) for s in sub)

    def test_array_assignment_hides_a_substitution(self):
        statement = Statement.from_command("arr=($(echo a) b)")

        assert isinstance(statement, Command)
        assert len(statement.sub_statements()) == 1
        assert isinstance(statement.sub_statements()[0], CmdSubst)

    def test_arithmetic_expansion_hides_a_substitution(self):
        statement = Statement.from_command("x=$((1+$(echo 2)))")

        assert len(statement.sub_statements()) == 1
        assert isinstance(statement.sub_statements()[0], CmdSubst)

    def test_array_index_hides_a_substitution(self):
        statement = Statement.from_command("x=${arr[$(echo 0)]}")

        assert len(statement.sub_statements()) == 1
        assert isinstance(statement.sub_statements()[0], CmdSubst)

    def test_single_quoting_correctly_excludes_a_look_alike(self):
        statement = Statement.from_command("echo '$(cat a)'")

        assert statement.sub_statements() == ()

    def test_case_pattern_hides_a_substitution(self):
        statement = Statement.from_command("case $x in ($(echo a)) foo;; esac")

        assert isinstance(statement, CaseClause)
        embedded = [s for s in statement.sub_statements() if isinstance(s, CmdSubst)]
        assert len(embedded) == 1

    def test_heredoc_body_hides_a_substitution(self):
        command = "cat <<EOF\n$(rm -rf /)\nEOF\n"
        statement = Statement.from_command(command)

        found = [s for s in _all_nested(statement) if isinstance(s, CmdSubst)]
        assert len(found) == 1

    def test_triple_nested_substitution_is_found_at_every_level(self):
        statement = Statement.from_command("echo $(echo $(echo $(rm -rf /)))")

        found = [s for s in _all_nested(statement) if isinstance(s, CmdSubst)]
        assert len(found) == 3

    def test_extglob_pattern_content_is_an_expected_blind_spot(self):
        """DOCUMENTED, EXPECTED LIMITATION - not a silently-passing gap.

        shfmt's own parser stores ExtGlob pattern content (`!(...)`, `@(...)`)
        as a single OPAQUE STRING (`Pattern.Value`), never decomposed into
        `Parts`/`CmdSubst` nodes at all - so no AST-based approach, old
        (`walk_ast`) or new (this scan), can see a `$(...)` hidden inside an
        extglob pattern. Verified live against shfmt 3.13.1: this is parity
        with today's behaviour, not a regression this leaf introduces.
        """
        statement = Statement.from_command("echo !(a|$(rm -rf /))")

        assert statement.sub_statements() == ()

    def test_stop_at_match_does_not_double_process_the_triple_nested_case(self):
        """The scan must stop descending the instant it matches the outer
        CmdSubst, handing the inner two off to that match's own
        sub_statements() rather than finding all three at the top level."""
        statement = Statement.from_command("echo $(echo $(echo $(rm -rf /)))")

        assert len(statement.sub_statements()) == 1
        outer = statement.sub_statements()[0]
        assert isinstance(outer, CmdSubst)


class TestBinaryCmdLeftRight:
    def test_left_and_right_are_the_two_sides(self):
        statement = Statement.from_command("cat a | tee b")

        assert isinstance(statement, BinaryCmd)
        assert statement.left.command_word == "cat"
        assert statement.right.command_word == "tee"

    def test_sub_statements_is_left_then_right(self):
        statement = Statement.from_command("cat a | tee b")

        assert statement.sub_statements() == (statement.left, statement.right)


class TestBlockAndSubshellUniformity:
    @pytest.mark.parametrize("command, cls", [("{ cat a; cat b; }", Block), ("(cat a; cat b)", Subshell)])
    def test_sub_statements_lists_every_child_in_order(self, command, cls):
        statement = Statement.from_command(command)

        assert isinstance(statement, cls)
        words = [s.command_word for s in statement.sub_statements()]
        assert words == ["cat", "cat"]


class TestIfClauseBranches:
    def test_condition_and_then_branch(self):
        statement = Statement.from_command("if true; then cat a; fi")

        assert statement.condition.command_word == "true"
        assert statement.then_branch.command_word == "cat"
        assert statement.else_branch is None

    def test_else_branch_is_an_ifclause_with_no_condition(self):
        statement = Statement.from_command("if true; then cat a; else cat b; fi")

        assert isinstance(statement.else_branch, IfClause)
        assert statement.else_branch.condition is None
        assert statement.else_branch.then_branch.command_word == "cat"

    def test_elif_chain_nests_else_branches(self):
        statement = Statement.from_command(
            "if false; then cat a; elif true; then cat b; else cat c; fi"
        )

        elif_branch = statement.else_branch
        assert elif_branch.condition.command_word == "true"
        assert elif_branch.then_branch.command_word == "cat"
        assert elif_branch.else_branch.then_branch.command_word == "cat"

    def test_sub_statements_omits_the_absent_else(self):
        statement = Statement.from_command("if true; then cat a; fi")

        assert statement.sub_statements() == (statement.condition, statement.then_branch)


class TestWhileClauseConditionAndBody:
    def test_loop_condition_and_loop_body(self):
        statement = Statement.from_command("while read l; do cat a; done")

        assert statement.loop_condition.command_word == "read"
        assert statement.loop_body.command_word == "cat"
        assert statement.sub_statements() == (statement.loop_condition, statement.loop_body)


class TestCaseClauseItemIndirection:
    def test_every_items_stmts_indirection_is_reachable(self):
        statement = Statement.from_command("case $x in a) cat a;; b) cat b; cat c;; esac")

        assert isinstance(statement, CaseClause)
        bodies = statement.sub_statements()
        # First item has exactly one statement, unwrapped to a bare Command.
        assert bodies[0].command_word == "cat"
        # Second item has two statements, wrapped in a synthetic container.
        assert [s.command_word for s in bodies[1].sub_statements()] == ["cat", "cat"]


class TestForClauseFuncDeclTimeCoproc:
    def test_for_clause_loop_body(self):
        statement = Statement.from_command("for i in a b; do cat $i; done")

        assert statement.loop_body.command_word == "cat"

    def test_func_decl_body(self):
        statement = Statement.from_command("func_name() { cat a; }")

        assert isinstance(statement, FuncDecl)
        assert isinstance(statement.body, Block)
        assert statement.body.sub_statements()[0].command_word == "cat"

    def test_time_clause_wraps_its_statement(self):
        statement = Statement.from_command("time cat a")

        assert statement.wrapped_statement.command_word == "cat"

    def test_bare_time_has_no_wrapped_statement(self):
        statement = Statement.from_command("time")

        assert statement.wrapped_statement is None
        assert statement.sub_statements() == ()

    def test_coproc_clause_wraps_its_statement(self):
        statement = Statement.from_command("coproc cat a")

        assert statement.wrapped_statement.command_word == "cat"


class TestBaseClassSurface:
    """.redirects, .is_backgrounded, .is_negated are correct across
    multiple subclasses - properties of the raw Stmt node itself,
    independent of Cmd.Type."""

    def test_redirects_on_a_plain_command(self):
        statement = Statement.from_command("cat a > out.txt")

        assert len(statement.redirects) == 1
        assert statement.redirects[0].operator.symbol == ">"
        assert statement.redirects[0].target_text == "out.txt"

    def test_redirects_on_a_block(self):
        statement = Statement.from_command("{ cat a; } > out.txt")

        assert isinstance(statement, Block)
        assert statement.redirects[0].target_text == "out.txt"

    def test_is_backgrounded_true_for_trailing_ampersand(self):
        statement = Statement.from_command("sleep 1 &")

        assert statement.is_backgrounded is True

    def test_is_backgrounded_false_by_default(self):
        statement = Statement.from_command("sleep 1")

        assert statement.is_backgrounded is False

    def test_is_negated_true_for_leading_bang(self):
        statement = Statement.from_command("! true")

        assert statement.is_negated is True

    def test_is_negated_false_by_default(self):
        statement = Statement.from_command("true")

        assert statement.is_negated is False

    def test_backgrounded_and_negated_can_co_occur(self):
        statement = Statement.from_command("! sleep 1 &")

        assert statement.is_backgrounded is True
        assert statement.is_negated is True


class TestAsSoleInvokedProgram:
    def test_a_bare_command_is_its_own_sole_invoked_program(self):
        statement = Statement.from_command("cat a")

        assert statement.as_sole_invoked_program() == "cat"

    def test_backgrounded_excludes(self):
        statement = Statement.from_command("cat a &")

        assert statement.as_sole_invoked_program() is None

    def test_negated_does_not_exclude(self):
        """Preserves today's behaviour: `! some-program true` still counts
        as a sole invoked program - the negation isn't checked."""
        statement = Statement.from_command("! cat a")

        assert statement.as_sole_invoked_program() == "cat"

    def test_a_hidden_command_shape_excludes(self):
        statement = Statement.from_command("cat a; cat b")

        assert statement.as_sole_invoked_program() is None

    def test_a_pipeline_excludes(self):
        statement = Statement.from_command("cat a | tee b")

        assert statement.as_sole_invoked_program() is None

    def test_an_embedded_substitution_excludes(self):
        statement = Statement.from_command("echo $(cat a)")

        assert statement.as_sole_invoked_program() is None

    def test_a_bare_assignment_has_no_sole_invoked_program(self):
        statement = Statement.from_command("x=1")

        assert statement.as_sole_invoked_program() is None


REDIRECT_NESTING_SHAPES = [
    ("simple_command", "cat a > out.txt", ("out.txt",)),
    ("compound_block", "{ cat a; cat b; } > blk.txt", ("blk.txt",)),
    ("command_less", "> /etc/passwd ; cat a", ("/etc/passwd",)),
    ("heredoc_delimiter_excluded", "cat <<EOF > here.txt\nbody\nEOF\n", ("here.txt",)),
    ("pipeline", "cat a | tee b > out.txt", ("out.txt",)),
    ("subshell", "(cat a > sub.txt)", ("sub.txt",)),
    ("if_body", "if true; then cat a > if.txt; fi", ("if.txt",)),
    ("loop_body", "while read l; do cat a > wh.txt; done", ("wh.txt",)),
]


class TestAllRedirectTargets:
    @pytest.mark.parametrize(
        "shape_name, command, expected_targets",
        REDIRECT_NESTING_SHAPES,
        ids=[shape[0] for shape in REDIRECT_NESTING_SHAPES],
    )
    def test_finds_the_redirect_target_at_every_nesting_shape(self, shape_name, command, expected_targets):
        statement = Statement.from_command(command)

        assert statement.all_redirect_targets() == expected_targets

    def test_recurses_into_a_cmdsubst_subtree(self):
        statement = Statement.from_command("echo $(cat < /etc/shadow)")

        assert statement.all_redirect_targets() == ("/etc/shadow",)

    def test_recurses_into_a_procsubst_subtree(self):
        statement = Statement.from_command("diff <(cat < /etc/shadow) b")

        assert statement.all_redirect_targets() == ("/etc/shadow",)


class TestWithHeredocNormalizedToLit:
    """Migrated from analyze-bash-command.py's CommandAst test matrix
    (TestCommandAstImmutability/SafePatternDetection/TransformationOutput/
    EdgeCases) - preserving the exact safe-pattern semantics CommandAst
    documents: a bare `cat`, a quoted delimiter, no other args, no pipe."""

    SAFE_COMMAND = "echo \"$(cat <<'EOF'\nhello world\nEOF\n)\""

    def _lit_values(self, statement):
        values = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("Type") == "Lit":
                    values.append(node.get("Value"))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(statement._raw)
        return values

    def test_returns_a_new_statement_without_the_cmdsubst(self):
        statement = Statement.from_command(self.SAFE_COMMAND)
        assert any(isinstance(s, CmdSubst) for s in _all_nested(statement))

        normalized = statement.with_heredoc_normalized_to_lit()

        assert not any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_original_is_unchanged(self):
        statement = Statement.from_command(self.SAFE_COMMAND)

        statement.with_heredoc_normalized_to_lit()

        assert any(isinstance(s, CmdSubst) for s in _all_nested(statement))

    def test_returns_a_new_instance_not_the_same_object(self):
        statement = Statement.from_command(self.SAFE_COMMAND)

        assert statement.with_heredoc_normalized_to_lit() is not statement

    def test_safe_pattern_double_quoted_delimiter(self):
        command = 'echo "$(cat <<"EOF"\ncontent\nEOF\n)"'
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert not any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_unsafe_pattern_unquoted_delimiter_allows_variable_expansion(self):
        command = "echo \"$(cat <<EOF\ncontent $variable\nEOF\n)\""
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_unsafe_pattern_with_pipe_is_not_transformed(self):
        command = "echo \"$(cat <<'EOF' | grep test\ncontent\nEOF\n)\""
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_unsafe_pattern_cat_with_extra_args_is_not_transformed(self):
        command = "echo \"$(cat -n <<'EOF'\ncontent\nEOF\n)\""
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_unsafe_pattern_not_cat_command_is_not_transformed(self):
        command = "echo \"$(head <<'EOF'\ncontent\nEOF\n)\""
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_transformation_preserves_the_heredoc_content(self):
        statement = Statement.from_command(self.SAFE_COMMAND)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert "hello world\n" in self._lit_values(normalized)

    def test_an_unsafe_pattern_is_not_transformed(self):
        command = "echo \"$(cat <<EOF\ncontent $variable\nEOF\n)\""
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_a_command_with_no_heredoc_round_trips_unchanged(self):
        statement = Statement.from_command("cat a > out.txt")

        normalized = statement.with_heredoc_normalized_to_lit()

        assert normalized.all_redirect_targets() == ("out.txt",)

    def test_multiple_safe_heredocs_are_all_transformed(self):
        """Migrated from shfmt-permissions' `TestCommandAstEdgeCases` (old
        test_multiple_heredocs_in_command, :2948) - breadth beyond the one
        heredoc `SAFE_COMMAND` exercises above."""
        command = (
            "echo \"$(cat <<'EOF1'\ncontent1\nEOF1\n)\" \"$(cat <<'EOF2'\ncontent2\nEOF2\n)\""
        )
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert not any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_a_safe_heredoc_is_transformed_while_a_sibling_unsafe_one_is_not(self):
        """Migrated from shfmt-permissions' `TestCommandAstEdgeCases` (old
        test_mixed_safe_and_unsafe_heredocs, :2962) - proves the transform
        is per-heredoc, not all-or-nothing for the whole command."""
        command = (
            "echo \"$(cat <<'SAFE'\nsafe content\nSAFE\n)\" \"$(cat <<UNSAFE\n$variable\nUNSAFE\n)\""
        )
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        remaining = [s for s in _all_nested(normalized) if isinstance(s, CmdSubst)]
        assert len(remaining) == 1

    def test_a_heredoc_inside_an_and_list_is_still_transformed(self):
        """Migrated from shfmt-permissions' `TestCommandAstEdgeCases` (old
        test_nested_command_structure, :2981) - the safe pattern is
        recognized regardless of which sub-statement embeds it."""
        command = 'git add . && git commit -m "$(cat <<\'EOF\'\nfeat: x\nEOF\n)"'
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert not any(isinstance(s, CmdSubst) for s in _all_nested(normalized))

    def test_an_empty_heredoc_is_not_transformed(self):
        """Migrated from shfmt-permissions' `TestCommandAstEdgeCases` (old
        test_empty_heredoc_not_transformed, :2930) - shfmt omits the `Hdoc`
        field entirely for an empty heredoc body, which fails the safe-
        pattern check (no content to normalize into a `Lit`), so the
        `CmdSubst` survives. Acceptable, not a gap: an empty heredoc has
        nothing worth optimizing away."""
        command = "echo \"$(cat <<'EOF'\nEOF\n)\""
        statement = Statement.from_command(command)

        normalized = statement.with_heredoc_normalized_to_lit()

        assert any(isinstance(s, CmdSubst) for s in _all_nested(normalized))


class TestCommandArguments:
    """`Command.arguments()`: the raw material leaf 20260914-213652's
    policy pipeline feeds to a Parser and its substitution-unknowability
    rules - excludes the command word itself (`Args[0]`)."""

    def test_excludes_the_command_word_itself(self):
        statement = Statement.from_command("echo hi there")

        arguments = statement.arguments()

        assert [a.text for a in arguments] == ["hi", "there"]

    def test_a_command_with_no_arguments_has_none(self):
        statement = Statement.from_command("echo")

        assert statement.arguments() == ()

    def test_an_argument_with_no_substitution_or_variable_is_plain(self):
        statement = Statement.from_command("echo hi")

        (argument,) = statement.arguments()

        assert argument.contains_substitution is False
        assert argument.referenced_variables == frozenset()

    def test_a_command_substitution_argument_has_empty_text(self):
        """A CmdSubst part carries no `Value` and no nested `Parts` either -
        its expansion cannot be statically known, so `text` contributes ""
        for it exactly like it does for a bare `ParamExp` (see
        test_a_variable_reference_is_captured_even_though_the_text_drops_it)
        - `contains_substitution` is the separate flag a caller uses to
        detect that unknowable content was present at all."""
        statement = Statement.from_command("echo $(echo safe)")

        (argument,) = statement.arguments()

        assert argument.text == ""
        assert argument.contains_substitution is True

    def test_a_process_substitution_argument_is_flagged_too(self):
        statement = Statement.from_command("cat <(echo safe)")

        (argument,) = statement.arguments()

        assert argument.contains_substitution is True

    def test_a_variable_reference_is_captured_even_though_the_text_drops_it(self):
        statement = Statement.from_command("echo $HOME")

        (argument,) = statement.arguments()

        assert argument.text == ""
        assert argument.referenced_variables == frozenset({"HOME"})

    def test_a_braced_variable_reference_next_to_literal_content_is_recovered(self):
        """`text` recovers the literal suffix ("/.bashrc") that follows the
        variable, even though both sit inside ONE top-level DblQuoted part
        with no `Value` of its own - `text` recurses into that part's own
        nested Parts to find it. The `ParamExp` itself still contributes ""
        (unknowable, matching `Argument`'s own class docstring), so the
        recovered text is a partial, still-conservative read. `referenced_
        variables` is unaffected, since it already recursed into DblQuoted
        independently."""
        statement = Statement.from_command('echo "${HOME}/.bashrc"')

        (argument,) = statement.arguments()

        assert argument.referenced_variables == frozenset({"HOME"})
        assert argument.text == "/.bashrc"

    def test_a_substitution_does_not_get_mistaken_for_a_variable_reference(self):
        statement = Statement.from_command("echo $(echo safe)")

        (argument,) = statement.arguments()

        assert argument.referenced_variables == frozenset()

    def test_a_double_quoted_word_with_no_substitution_reads_its_real_content(self):
        """A DblQuoted word with no variable or substitution inside it is
        FULLY statically knowable - `text` must read its real content, not
        the empty string a naive one-level Parts join would produce (a
        DblQuoted word carries no `Value` at its own top level; its literal
        content sits one level deeper, in that part's own nested Parts)."""
        statement = Statement.from_command('echo "plain value"')

        (argument,) = statement.arguments()

        assert argument.text == "plain value"

    def test_double_quoting_does_not_change_an_otherwise_plain_words_text(self):
        statement = Statement.from_command("echo hi 'there now'")

        first, second = statement.arguments()

        assert first.text == "hi"
        assert second.text == "there now"

    def test_single_quoting_excludes_a_variable_look_alike_from_referenced_variables(self):
        """Migrated from shfmt-permissions' TestExtractArgTextWithVars
        (old test_extract_single_quoted_no_expansion) - single quotes
        prevent expansion, so a look-alike `$VAR` inside them is not a
        variable reference at all."""
        statement = Statement.from_command("touch '$VAR'")

        (argument,) = statement.arguments()

        assert argument.referenced_variables == frozenset()
        assert argument.text == "$VAR"

    def test_two_variables_in_one_argument_are_both_captured(self):
        """Migrated from shfmt-permissions' TestExtractArgTextWithVars (old
        test_extract_multiple_variables) - referenced_variables recurses
        into every part, not just the first ParamExp found."""
        statement = Statement.from_command('touch "${DIR}/${FILE}"')

        (argument,) = statement.arguments()

        assert argument.referenced_variables == frozenset({"DIR", "FILE"})


class TestArgumentWordSafety:
    """`Argument.word_safe`: true only when this word is GUARANTEED to expand
    to exactly one word at runtime - the precision the index-shift rule needs
    (improvement-20260919-112214). A literal has nothing to split, so it is
    trivially word-safe; an expansion only stays word-safe when a `DblQuoted`
    ancestor encloses THAT part - a literal prefix/suffix on the same word
    does not confer safety on its neighbour. `"$@"`/`"${arr[@]}"` are the
    exception: they split into multiple words despite being double-quoted."""

    WORD_SAFE_CASES = [
        ("echo hi", True),  # plain literal, nothing to split
        ("echo 'literal$X'", True),  # single-quoted: no expansion at all
        ('echo "$X"', True),  # whole expansion enclosed in DblQuoted
        ("echo ${X}", False),  # bare, unquoted
        ('echo "${X}"', True),
        ("echo safe$X", False),  # literal prefix does not confer safety
        ('echo safe"$X"', True),  # the expansion itself IS enclosed
        ('echo "a b"$X', False),  # the $X sits OUTSIDE the DblQuoted part
        ('echo "safe$X"', True),  # literal and expansion share one DblQuoted part
        ("echo $(echo x)", False),
        ('echo "$(echo x)"', True),
        ("echo safe$(echo x)", False),
        ('echo "$@"', False),  # the multi-word exception
        ('echo "${arr[@]}"', False),  # the multi-word exception, indexed form
        ('echo "$*"', True),  # genuinely one word despite the sibling syntax
        ('echo "${arr[0]}"', True),  # an ordinary (non-@) index stays one word
    ]

    @pytest.mark.parametrize("command, expected_word_safe", WORD_SAFE_CASES, ids=[c for c, _ in WORD_SAFE_CASES])
    def test_word_safe_matches_the_quoting_and_expansion_shape(self, command, expected_word_safe):
        statement = Statement.from_command(command)

        (argument,) = statement.arguments()

        assert argument.word_safe is expected_word_safe

    def test_a_command_with_no_expansion_at_all_is_word_safe_by_default(self):
        statement = Statement.from_command("echo hi there")

        first, second = statement.arguments()

        assert first.word_safe is True
        assert second.word_safe is True


class TestRedirectTargetText:
    """`Redirect.target_text` applies the identical recursive-Parts fix as
    `Argument.text` (see TestCommandArguments above) - both go through the
    same shared helper, so a double-quoted redirect target recovers its
    real literal content instead of reading as the empty string."""

    def test_a_double_quoted_redirect_target_recovers_its_real_content(self):
        statement = Statement.from_command('echo x > "/etc/passwd"')

        assert statement.redirects[0].target_text == "/etc/passwd"

    def test_a_variable_next_to_literal_content_in_a_redirect_target_is_partially_recovered(self):
        """Mirrors test_a_braced_variable_reference_next_to_literal_content_is_recovered:
        the `ParamExp` itself still contributes "" (unknowable), but the
        literal suffix following it ("/.bashrc") is recovered."""
        statement = Statement.from_command('echo x > "$HOME/.bashrc"')

        assert statement.redirects[0].target_text == "/.bashrc"
