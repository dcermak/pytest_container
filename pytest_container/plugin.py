"""The plugin module contains all fixtures that are provided by
``pytest_container``.

"""

import sys
from subprocess import PIPE
from subprocess import run
from typing import Callable
from typing import Generator

from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import container_and_marks_from_pytest_param
from pytest_container.logging import _logger
from pytest_container.pod import PodData
from pytest_container.pod import PodLauncher
from pytest_container.pod import pod_from_pytest_param
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import get_selected_runtime

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

from _pytest.config import Config
from _pytest.fixtures import SubRequest
from pytest import fixture
from pytest import skip


@fixture(scope="session")
def container_runtime() -> OciRuntimeBase:
    """pytest fixture that returns the currently selected container runtime
    according to the rules outlined :ref:`here <runtime selection rules>`.

    """
    return get_selected_runtime()


def _log_container_logs(
    container_id: str, ctr_runtime: OciRuntimeBase
) -> None:
    # don't die if logging fails for some reason
    # pylint: disable=subprocess-run-check
    logs_call = run(
        [ctr_runtime.runner_binary, "logs", container_id],
        stdout=PIPE,
        stderr=PIPE,
    )
    if logs_call.returncode == 0:
        _logger.debug(
            "logs from container %s: %s",
            container_id,
            logs_call.stdout.decode(),
        )


def _create_auto_container_fixture(
    scope: Literal["session", "function"],
) -> Callable[
    [SubRequest, OciRuntimeBase, Config], Generator[ContainerData, None, None]
]:
    def fixture_funct(
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

        try:
            container, _ = container_and_marks_from_pytest_param(request.param)
        except AttributeError as attr_err:
            raise RuntimeError(
                "This fixture was not parametrized correctly, "
                "did you forget to call `auto_container_parametrize` in `pytest_generate_tests`?"
            ) from attr_err
        _logger.debug("Requesting the container %s", str(container))

        if scope == "session" and container.singleton:
            raise RuntimeError(
                f"A singleton container ({container}) cannot be used in a session level fixture"
            )

        with ContainerLauncher.from_pytestconfig(
            container=container,
            container_runtime=container_runtime,
            pytestconfig=pytestconfig,
        ) as launcher:
            # we want to ensure that the container's logs are saved at "all
            # cost", especially when the container fails to launch for some
            # reason
            try:
                launcher.launch_container()
                container_data = launcher.container_data
                yield container_data
            finally:
                if launcher._container_id:
                    _log_container_logs(
                        launcher._container_id, container_runtime
                    )

    return fixture(scope=scope)(fixture_funct)


def _create_auto_pod_fixture(
    scope: Literal["session", "function"],
) -> Callable[
    [SubRequest, OciRuntimeBase, Config], Generator[PodData, None, None]
]:
    def fixture_funct(
        request: SubRequest,
        # we must call this parameter container runtime, so that pytest will
        # treat it as a fixture, but that causes pylint to complain…
        # pylint: disable=redefined-outer-name
        container_runtime: OciRuntimeBase,
        pytestconfig: Config,
    ) -> Generator[PodData, None, None]:
        if "podman" not in container_runtime.runner_binary:
            skip("Pods are only supported in podman")

        pod = pod_from_pytest_param(request.param)
        with PodLauncher.from_pytestconfig(pod, pytestconfig) as launcher:
            try:
                launcher.launch_pod()
                pod_data = launcher.pod_data
                yield pod_data
            finally:
                for ctr_launcher in launcher._launchers:
                    if ctr_launcher._container_id:
                        _log_container_logs(
                            ctr_launcher._container_id, container_runtime
                        )

    return fixture(scope=scope)(fixture_funct)


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

#: Fixture that has to be parametrized with an instance of
#: :py:class:`~pytest_container.pod.Pod` with `indirect=True`.
#: It creates the pod, launches all of its containers and yields an instance of
#: :py:class:`~pytest_container.pod.PodData`. The fixture automatically skips
#: the test when the current container runtime is not :command:`podman`.
#: The pod created by this fixture is shared by all test functions.
pod = _create_auto_pod_fixture("session")

#: Same as :py:func:`pod`, except that it creates a pod for each test function.
pod_per_test = _create_auto_pod_fixture("function")
