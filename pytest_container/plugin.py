"""The plugin module contains all fixtures that are provided by
``pytest_container``.

"""
import sys
from typing import Callable
from typing import Generator

from pytest_container.container import container_from_pytest_param
from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.helpers import get_extra_build_args
from pytest_container.helpers import get_extra_run_args
from pytest_container.logging import _logger
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

import pytest
from _pytest.config import Config
from _pytest.fixtures import SubRequest


@pytest.fixture(scope="session")
def container_runtime() -> OciRuntimeBase:
    """pytest fixture that returns the currently selected container runtime
    according to the rules outlined :ref:`here <runtime selection rules>`.

    """
    return get_selected_runtime()


def _create_auto_container_fixture(
    scope: Literal["session", "function"]
) -> Callable[
    [SubRequest, OciRuntimeBase, Config], Generator[ContainerData, None, None]
]:
    def fixture(
        request: SubRequest,
        # we must call this parameter container runtime, so that pytest will
        # treat it as a fixture, but that causes pylint to complain…
        # pylint: disable=redefined-outer-name
        container_runtime: OciRuntimeBase,
        pytestconfig: Config,
    ) -> Generator[ContainerData, None, None]:
        """Fixture that will build & launch a container that is either passed as a
        request parameter or it will be automatically parametrized via
        pytest_generate_tests.
        """

        launch_data = container_from_pytest_param(request.param)
        _logger.debug("Requesting the container %s", str(launch_data))

        if scope == "session" and launch_data.singleton:
            raise RuntimeError(
                f"A singleton container ({launch_data}) cannot be used in a session level fixture"
            )

        add_labels = [
            "--label",
            f"pytest_container.request={request}",
            "--label",
            f"pytest_container.node.name={request.node.name}",
            "--label",
            f"pytest_container.scope={request.scope}",
        ]
        try:
            add_labels.extend(
                ["--label", f"pytest_container.path={request.path}"]
            )
        except AttributeError:
            pass

        with ContainerLauncher(
            container=launch_data,
            container_runtime=container_runtime,
            rootdir=pytestconfig.rootpath,
            extra_build_args=get_extra_build_args(pytestconfig),
            extra_run_args=get_extra_run_args(pytestconfig) + add_labels,
        ) as launcher:
            yield launcher.container_data

    return pytest.fixture(scope=scope)(fixture)


#: This fixture parametrizes the test function once for each container image
#: defined in the module level variable ``CONTAINER_IMAGES`` of the current test
#: module and yield an instance of
#: :py:attr:`~pytest_container.container.ContainerData`.
#: This fixture will reuse the same container for all tests of the same session.
auto_container = _create_auto_container_fixture("session")

#: Fixture that expects to be parametrized with an instance of a subclass of
#: :py:class:`~pytest_container.container.ContainerBase` with `indirect=True`.
#: It will launch the container and yield an instance of
#: :py:attr:`~pytest_container.container.ContainerData`.
#: This fixture will reuse the same container for all tests of the same session.
container = _create_auto_container_fixture("session")

#: Same as :py:func:`auto_container` but it will launch individual containers
#: for each test function.
auto_container_per_test = _create_auto_container_fixture("function")

#: Same as :py:func:`container` but it will launch individual containers for
#: each test function.
container_per_test = _create_auto_container_fixture("function")
