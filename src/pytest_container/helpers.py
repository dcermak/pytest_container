from typing import List

from _pytest.config import Config
from _pytest.config.argparsing import Parser
from _pytest.python import Metafunc


def auto_container_parametrize(metafunc: Metafunc) -> None:
    container_images = getattr(metafunc.module, "CONTAINER_IMAGES", None)
    if container_images is not None:
        for fixture_name in ("auto_container", "auto_container_per_test"):
            if fixture_name in metafunc.fixturenames:
                metafunc.parametrize(
                    fixture_name, container_images, indirect=True
                )


def add_extra_run_and_build_args_options(parser: Parser) -> None:
    """Add the command line flags '--extra-run-args' and '--extra-build-args' to
    the pytest parser.

    The parameters of these flags are used by the ``*_container`` fixtures and
    can be retrieved via :py:func:`get_extra_run_args` and
    :py:func:`get_extra_build_args` respectively.
    """
    parser.addoption(
        "--extra-run-args",
        type=str,
        nargs="*",
        default=[],
        help="Specify additional CLI arguments to be passed to 'podman run' or 'docker run'. Each argument must be passed as an individual argument itself.",
    )
    parser.addoption(
        "--extra-build-args",
        type=str,
        nargs="*",
        default=[],
        help="Specify additional CLI arguments to be passed to 'buildah bud' or 'docker build'. Each argument must be passed as an individual argument itself",
    )


def get_extra_run_args(pytestconfig: Config) -> List[str]:
    """Get any extra arguments for :command:`podman run` or :command:`docker run`
    that were passed via the CLI flag ``--extra-run-args``.

    This requires that :py:func:`add_extra_run_and_build_args_options` was
    called in :file:`conftest.py`.

    """
    return pytestconfig.getoption("extra_run_args") or []


def get_extra_build_args(pytestconfig: Config) -> List[str]:
    """Get any extra arguments for :command:`buildah bud` or :command:`docker
    build` that were passed via the CLI flag ``--extra-build-args``.

    This requires that :py:func:`add_extra_run_and_build_args_options` was
    called in :file:`conftest.py`.

    """
    return pytestconfig.getoption("extra_build_args") or []
