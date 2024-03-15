"""The helpers module contains various functions for adding & retrieving command
line flags from pytest and for automatically parametrizing tests using the
``auto_container*`` fixtures.

"""
import logging
import os
from typing import List

from _pytest.config import Config
from _pytest.config.argparsing import Parser
from _pytest.python import Metafunc
from pytest_container.logging import set_internal_logging_level


def auto_container_parametrize(metafunc: Metafunc) -> None:
    """Helper function to automatically parametrize the ``auto_container_*``
    fixtures.

    Use it by adding the following code snippet to :file:`conftest.py`:

    .. code-block:: python

       from pytest_container import auto_container_parametrize

       def pytest_generate_tests(metafunc):
           auto_container_parametrize(metafunc)


    """
    container_images = getattr(metafunc.module, "CONTAINER_IMAGES", None)

    for fixture_name in ("auto_container", "auto_container_per_test"):
        if fixture_name in metafunc.fixturenames:
            if container_images is None:
                raise ValueError(
                    f"The test function {metafunc.function.__name__} is using "
                    f"the {fixture_name} fixture but the parent module is not "
                    "setting the 'CONTAINER_IMAGES' variable"
                )
            metafunc.parametrize(fixture_name, container_images, indirect=True)


def add_extra_run_and_build_args_options(parser: Parser) -> None:
    """Add the command line flags ``--extra-run-args``, ``--extra-build-args``
    and ``--extra-pod-create-args`` to the pytest parser.

    The parameters of these flags are used by the ``*container*`` and ``pod*``
    fixtures and can be retrieved via :py:func:`get_extra_run_args`,
    :py:func:`get_extra_build_args` and :py:func:`get_extra_pod_create_args`
    respectively.

    """
    parser.addoption(
        "--extra-run-args",
        type=str,
        nargs="*",
        default=[],
        help="""Specify additional CLI arguments to be passed to 'podman run' or
 'docker run'. Each argument must be passed as an individual argument itself.""",
    )
    parser.addoption(
        "--extra-build-args",
        type=str,
        nargs="*",
        default=[],
        help="""Specify additional CLI arguments to be passed to 'buildah bud'
 or 'docker build'. Each argument must be passed as an individual argument itself""",
    )
    parser.addoption(
        "--extra-pod-create-args",
        type=str,
        nargs="*",
        default=[],
        help="""Specify additional CLI arguments that will be passed to 'podman
pod create'. Each argument must be passed individually.""",
    )


def add_logging_level_options(parser: Parser) -> None:
    """Add the command line parameter ``--pytest-container-log-level`` to the pytest
    parser. The user can then configure the log level of this pytest plugin.

    This function needs to be called in your :file:`conftest.py` in
    ``pytest_addoption``. To actually set the log level, you need to call
    :py:func:`set_logging_level_from_cli_args` as well.
    """
    log_level_upcase = list(logging._levelToName.values())
    parser.addoption(
        "--pytest-container-log-level",
        type=str,
        nargs=1,
        default=["INFO"],
        choices=log_level_upcase
        + [level.lower() for level in log_level_upcase],
        help="Set the internal logging level of the pytest_container library",
    )


def set_logging_level_from_cli_args(config: Config) -> None:
    """Sets the internal logging level of this plugin to the value supplied by the
    cli argument ``--pytest-container-log-level``.

    This function has to be called before all tests get executed, but after the
    parser option has been added. A good place is for example the
    `pytest_configure
    <https://docs.pytest.org/en/latest/reference/reference.html#_pytest.hookspec.pytest_configure>`_
    hook which has to be added to :file:`conftest.py`.

    """
    set_internal_logging_level(
        config.getoption("pytest_container_log_level")[0].upper()
    )


def get_extra_run_args(pytestconfig: Config) -> List[str]:
    """Get any extra arguments for :command:`podman run` or :command:`docker run`
    that were passed via the CLI flag ``--extra-run-args``.

    This requires that :py:func:`add_extra_run_and_build_args_options` was
    called in :file:`conftest.py`.

    """
    return pytestconfig.getoption("extra_run_args", default=[]) or []


def get_extra_build_args(pytestconfig: Config) -> List[str]:
    """Get any extra arguments for :command:`buildah bud` or :command:`docker
    build` that were passed via the CLI flag ``--extra-build-args``.

    This requires that :py:func:`add_extra_run_and_build_args_options` was
    called in :file:`conftest.py`.

    """
    return pytestconfig.getoption("extra_build_args", default=[]) or []


def get_extra_pod_create_args(pytestconfig: Config) -> List[str]:
    """Get all extra arguments for :command:`podman pod create` that were passed
    via the CLI flag ``--extra-pod-create-args``.

    This requires that :py:func:`add_extra_run_and_build_args_options` was
    called in :file:`conftest.py`.

    """
    return pytestconfig.getoption("extra_pod_create_args", default=[]) or []


def get_always_pull_option() -> bool:
    """Returns whether images should be always pulled before launching the
    container or whether the container runtime can use the locally cached
    image. This setting is controlled via the environment variable
    ``PULL_ALWAYS``. If the environment variable is unset, then the default is
    ``True``.

    """
    return bool(int(os.getenv("PULL_ALWAYS", "1")))
