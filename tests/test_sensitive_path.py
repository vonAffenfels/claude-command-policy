"""Unit tests for SensitivePath construction.

Matching (substring, deliberately over-matching) is the pipeline leaf's job;
this leaf only constructs the value object and lets it explain itself.
"""

from sensitive_path import SensitivePath


def test_a_sensitive_path_carries_its_literal_text():
    path = SensitivePath.from_entry("/etc/passwd")

    assert path.literal == "/etc/passwd"


def test_two_sensitive_paths_for_the_same_literal_are_equal():
    assert SensitivePath.from_entry("/etc/passwd") == SensitivePath.from_entry("/etc/passwd")


def test_a_sensitive_path_explains_itself_naming_its_literal():
    path = SensitivePath.from_entry("/etc/passwd")

    assert "/etc/passwd" in path.explain()
