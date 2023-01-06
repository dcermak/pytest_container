# pylint: disable=missing-function-docstring,missing-module-docstring
from pytest_container import GitRepositoryBuild


def test_repo_name() -> None:
    for url in ("foobar.com/repo.git", "foobar.com/repo/", "foobar.com/repo"):
        assert GitRepositoryBuild(repository_url=url).repo_name == "repo"
