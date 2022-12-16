from subprocess import check_output

import nox
from nox_poetry import Session
from nox_poetry import session


@session(python=["3.10", "3.9", "3.8", "3.7", "3.6"])
@nox.parametrize(
    "container_runtime",
    [nox.param(runtime, id=runtime) for runtime in ("podman", "docker")],
)
def test(session, container_runtime):
    session.install(
        "pytest",
        "pytest-xdist",
        "pytest-cov",
        "pytest-rerunfailures",
        "typeguard",
        ".",
    )
    session.run(
        "pytest",
        "--cov=pytest_container",
        "--cov-report",
        "term",
        "--cov-report",
        "html",
        "--cov-report",
        "xml",
        "-vv",
        "tests/base/",
        *session.posargs,
        env={"CONTAINER_RUNTIME": container_runtime}
    )


@session()
def lint(session: Session):
    session.install("mypy", "pytest", "filelock", "pylint", "typeguard", ".")
    session.run("mypy", "src/pytest_container")
    session.run(
        "pylint", "--fail-under", "9.0", "src/pytest_container", "tests/"
    )


@session()
def doc(session: Session):
    session.install("sphinx", ".")
    session.run("sphinx-build", "-M", "html", "source", "build", "-W")


@session()
def format(session: Session):
    session.install("black", "reorder-python-imports")

    args = ["--check", "--diff"] if "--check" in session.posargs else []
    session.run("black", ".", *args)
    files = check_output(["git", "ls-files"]).decode().strip().splitlines()
    for f in files:
        if f.endswith(".py"):
            success_codes = [0] if args else [0, 1]
            session.run(
                "reorder-python-imports", f, success_codes=success_codes
            )
