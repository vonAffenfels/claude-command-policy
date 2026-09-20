"""Unit tests for the three plain-name veto/allow collections.

blockedCommands, sensitiveVariables and additionalAllowedPathPrefixes share
one shape (an ordered set of literal names with union merge) but differ in
what they mean, so each gets its own domain name over a shared
NameCollection base.
"""

from name_collection import AllowedPathPrefixes, BlockedCommands, SensitiveVariables


def test_blocked_commands_carries_its_configured_names():
    blocked = BlockedCommands.from_entries(["rm", "curl"])

    assert blocked.names == ("rm", "curl")


def test_blocked_commands_unions_with_another_layer():
    base = BlockedCommands.from_entries(["rm"])
    overlay = BlockedCommands.from_entries(["curl"])

    assert base.union(overlay).names == ("rm", "curl")


def test_blocked_commands_explains_its_veto():
    blocked = BlockedCommands.from_entries(["rm"])

    assert "rm" in blocked.explain()


def test_sensitive_variables_carries_its_configured_names():
    variables = SensitiveVariables.from_entries(["AWS_SECRET_ACCESS_KEY"])

    assert variables.names == ("AWS_SECRET_ACCESS_KEY",)


def test_allowed_path_prefixes_carries_its_configured_paths():
    prefixes = AllowedPathPrefixes.from_entries(["/shared"])

    assert prefixes.names == ("/shared",)


def test_an_empty_name_collection_unions_to_the_other_side_unchanged():
    empty = BlockedCommands.from_entries([])
    populated = BlockedCommands.from_entries(["rm"])

    assert empty.union(populated).names == ("rm",)
    assert populated.union(empty).names == ("rm",)
