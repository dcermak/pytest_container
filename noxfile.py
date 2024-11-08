from subprocess import check_output

import nox
from nox_poetry import Session
from nox_poetry import session


@session(python=["3.13", "3.12", "3.11", "3.10", "3.9", "3.8", "3.7", "3.6"])
@nox.parametrize(
    "container_runtime",
    [nox.param(runtime, id=runtime) for runtime in ("podman", "docker")],
)
def test(session: Session, container_runtime: str):
    session.install("-r", "test-requirements.txt")
    session.run(
        "coverage",
        "run",
        "-m",
        "pytest",
        "-vv",
        "tests",
        "-p",
        "pytest_container",
        *session.posargs,
        env={"CONTAINER_RUNTIME": container_runtime}
    )


@session()
def coverage(session: Session):
    session.install("-r", "test-requirements.txt")
    session.run("coverage", "combine")
    session.run("coverage", "report", "-m")
    session.run("coverage", "html")
    session.run("coverage", "xml")


@session()
def lint(session: Session):
    session.install("-r", "test-requirements.txt")
    session.run("mypy", "pytest_container")
    session.run("pylint", "pytest_container", "tests/")
    session.run("twine", "check", "dist/*.whl")


@session()
def doc(session: Session):
    session.install("-r", "test-requirements.txt")
    session.run("sphinx-build", "-M", "html", "source", "build", "-W")


@session()
def format(session: Session):
    session.install("-r", "test-requirements.txt")

    args = ["--check", "--diff"] if "--check" in session.posargs else []
    session.run("black", ".", *args)
    files = check_output(["git", "ls-files"]).decode().strip().splitlines()
    for f in files:
        if f.endswith(".py"):
            success_codes = [0] if args else [0, 1]
            session.run(
                "reorder-python-imports", f, success_codes=success_codes
            )
