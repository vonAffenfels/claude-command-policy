"""Unit tests for RedirectPathValidationPolicy: Pass 4, independent of any
allowedCommands entry's own hasNoPathParameters flag."""

from pass_ import Pass
from path_resolution import PathResolutionContext
from reason import RedirectOutsideAllowedPaths
from redirect_path_validation_policy import RedirectPathValidationPolicy
from statement import Statement


def _policy(command, project_dir="/project", allowed_prefixes=()):
    path_resolution = PathResolutionContext(cwd=project_dir, home="/home/user", exists_predicate=lambda p: False)
    policy = RedirectPathValidationPolicy(path_resolution, allowed_prefixes)
    return policy.for_statement(Statement.from_command(command))


def test_pass_is_four_independent_of_which_entry_vouches():
    path_resolution = PathResolutionContext(cwd="/project")
    assert RedirectPathValidationPolicy(path_resolution, ()).pass_ == Pass.REDIRECT_PATH_VALIDATION


def test_does_not_match_a_redirect_target_inside_the_project():
    policy = _policy("cat ./README.md > /project/out.txt")

    assert policy.matches() is False


def test_matches_a_redirect_target_outside_the_project():
    policy = _policy("cat ./README.md > /etc/passwd")

    assert policy.matches() is True
    assert RedirectOutsideAllowedPaths("/etc/passwd") in policy.decision().reason


def test_an_additional_allowed_prefix_permits_a_redirect_outside_the_project():
    policy = _policy("cat ./README.md > /shared/out.txt", allowed_prefixes=["/shared"])

    assert policy.matches() is False


def test_an_empty_redirect_target_never_resolves_to_cwd():
    policy = _policy('cat ./README.md > ""')

    assert policy.matches() is True


def test_a_redirect_outside_the_project_in_a_later_statement_still_matches():
    policy = _policy("cat a > /project/ok.txt; echo x > /etc/passwd")

    assert policy.matches() is True
