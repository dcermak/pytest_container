import datetime
import os
import time
from pathlib import Path
from pytest_container.container import container_from_pytest_param
from pytest_container.container import ContainerData
from pytest_container.helpers import get_extra_build_args
from pytest_container.helpers import get_extra_run_args
from pytest_container.logging import _logger
from pytest_container.runtime import ContainerHealth
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase
from subprocess import check_output
from tempfile import gettempdir
from typing import Callable
from typing import Generator
from typing import Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Literal
else:
    try:
        from typing import Literal
    except ImportError:
        from typing_extensions import Literal

import pytest
import testinfra
from _pytest.config import Config
from _pytest.fixtures import SubRequest
from filelock import FileLock


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
        # pylint: disable=W0621
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

        container_id: Optional[str] = None

        lock = FileLock(Path(gettempdir()) / launch_data.filelock_filename)
        _logger.debug(
            "Locking container preparation via file %s", lock.lock_file
        )
        lock.acquire()

        cleanup_ran = False

        def release_lock() -> None:
            _logger.debug("Releasing lock %s", lock.lock_file)
            lock.release()
            os.unlink(lock.lock_file)

        _logger.debug("launching %s", launch_data.__dict__)

        def cleanup(release_lock_cond: bool) -> None:
            """Cleanup the container:
            - if `container_id` is not `None`, then try to remove the container
            - if `release_lock_cond` is true, then release the file lock
            """
            nonlocal cleanup_ran
            if cleanup_ran:
                _logger.debug(
                    "Container %s has already been cleaned up, skipping",
                    str(launch_data),
                )
                return

            cleanup_ran = True
            _logger.debug("Cleaning up container %s", str(launch_data))

            if container_id is not None:
                _logger.debug(
                    "Removing container %s via %s",
                    container_id,
                    container_runtime.runner_binary,
                )
                check_output(
                    [
                        container_runtime.runner_binary,
                        "rm",
                        "-f",
                        container_id,
                    ],
                )

            if release_lock_cond:
                release_lock()

        try:
            try:
                launch_data.prepare_container(
                    rootdir=pytestconfig.rootpath,
                    extra_build_args=get_extra_build_args(pytestconfig),
                )
            except Exception as exc:
                _logger.error(
                    "Caught an exception during container preparation: %s", exc
                )
                cleanup(not launch_data.singleton)
                raise

            # ordinary containers are only locked during the build,
            # singleton containers are unlocked after everything
            if not launch_data.singleton:
                release_lock()

            launch_cmd = [
                container_runtime.runner_binary
            ] + launch_data.get_launch_cmd(
                extra_run_args=get_extra_run_args(pytestconfig)
            )
            _logger.debug("Launching container via: %s", launch_cmd)
            container_id = check_output(launch_cmd).decode().strip()

            start = datetime.datetime.now()
            timeout: Optional[
                datetime.timedelta
            ] = launch_data.healthcheck_timeout
            _logger.debug(
                "Started container with %s at %s", container_id, start
            )

            if timeout is None:
                healthcheck = container_runtime.get_container_healthcheck(
                    launch_data
                )
                if healthcheck is not None:
                    timeout = healthcheck.max_wait_time

            if timeout is not None and timeout > datetime.timedelta(seconds=0):
                _logger.debug(
                    "Container has a healthcheck defined, will wait at most %s ms",
                    timeout,
                )
                while True:
                    health = container_runtime.get_container_health(
                        container_id
                    )
                    _logger.debug("Container has the health status %s", health)

                    if health in (
                        ContainerHealth.NO_HEALTH_CHECK,
                        ContainerHealth.HEALTHY,
                    ):
                        break
                    delta = datetime.datetime.now() - start
                    if delta > timeout:
                        raise RuntimeError(
                            f"Container {container_id} did not become healthy within "
                            f"{1000 * timeout.total_seconds()}ms, took {delta} and "
                            f"state is {str(health)}"
                        )
                    time.sleep(max(0.5, timeout.total_seconds() / 10))

            yield ContainerData(
                image_url_or_id=launch_data.url or launch_data.container_id,
                container_id=container_id,
                connection=testinfra.get_host(
                    f"{container_runtime.runner_binary}://{container_id}"
                ),
                container=launch_data,
            )
        except Exception as exc:
            _logger.error(
                "Caught an exception during container creation: %s", exc
            )
            raise
        finally:
            cleanup(launch_data.singleton)

    return pytest.fixture(scope=scope)(fixture)


auto_container = _create_auto_container_fixture("session")
container = _create_auto_container_fixture("session")

auto_container_per_test = _create_auto_container_fixture("function")
container_per_test = _create_auto_container_fixture("function")
