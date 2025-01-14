# pylint: disable=missing-function-docstring,missing-module-docstring
import logging
from datetime import datetime
from datetime import timedelta
from time import sleep
from typing import Optional

import pytest

from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import DerivedContainer
from pytest_container.container import ImageFormat
from pytest_container.runtime import ContainerHealth
from pytest_container.runtime import HealthCheck
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import get_selected_runtime

from .images import LEAP
from .images import LEAP_URL

CONTAINER_WITH_HEALTHCHECK = DerivedContainer(
    base=LEAP_URL,
    image_format=ImageFormat.DOCKER,
    # iproute2 is needed for checking the socket connection
    containerfile="""RUN zypper -n in python3 curl iproute2
EXPOSE 8000
CMD /usr/bin/python3 -c "import http.server; import os; from time import sleep; sleep(5); http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler)"
HEALTHCHECK --interval=5s --timeout=1s CMD curl --fail http://0.0.0.0:8000
""",
)

CONTAINER_DERIVING_FROM_HEALTHCHECK = DerivedContainer(
    base=CONTAINER_WITH_HEALTHCHECK, containerfile="ENV DUMMY=baz"
)


def _failing_healthcheck_container(healtcheck_args: str) -> DerivedContainer:
    return DerivedContainer(
        base=LEAP_URL,
        image_format=ImageFormat.DOCKER,
        containerfile=f"""CMD sleep 600
HEALTHCHECK {healtcheck_args} CMD false
""",
        healthcheck_timeout=timedelta(seconds=-1),
    )


CONTAINER_WITH_FAILING_HEALTHCHECK = _failing_healthcheck_container(
    "--retries=2 --interval=2s"
)

CONTAINER_THAT_FAILS_TO_LAUNCH_WITH_FAILING_HEALTHCHECK = DerivedContainer(
    base=LEAP_URL,
    image_format=ImageFormat.DOCKER,
    containerfile="""ENTRYPOINT ["/bin/false"]
HEALTHCHECK --retries=5 --timeout=10s --interval=10s CMD false
""",
)


@pytest.mark.parametrize(
    "container", [CONTAINER_WITH_HEALTHCHECK], indirect=True
)
def test_container_healthcheck(
    container: ContainerData, container_runtime: OciRuntimeBase
) -> None:
    assert (
        container_runtime.get_container_health(container.container_id)
        == ContainerHealth.HEALTHY
    )
    assert container.connection.socket("tcp://0.0.0.0:8000").is_listening


@pytest.mark.parametrize("container", [LEAP], indirect=True)
def test_container_without_healthcheck(
    container: ContainerData, container_runtime: OciRuntimeBase
) -> None:
    assert (
        container_runtime.get_container_health(container.container_id)
        == ContainerHealth.NO_HEALTH_CHECK
    )


@pytest.mark.parametrize(
    "container", [CONTAINER_WITH_FAILING_HEALTHCHECK], indirect=True
)
def test_container_with_failing_healthcheck(
    container: ContainerData, container_runtime: OciRuntimeBase
) -> None:
    # the container must be in starting state at first
    assert (
        container_runtime.get_container_health(container.container_id)
        == ContainerHealth.STARTING
    )

    # the runtime will retry the healthcheck command a few times and fail
    for _ in range(10):
        if (
            container_runtime.get_container_health(container.container_id)
            != ContainerHealth.STARTING
        ):
            break
        sleep(1)

    # the container must be unhealthy now
    assert (
        container_runtime.get_container_health(container.container_id)
        == ContainerHealth.UNHEALTHY
    )


@pytest.mark.parametrize(
    "container,healthcheck",
    [
        (
            CONTAINER_WITH_FAILING_HEALTHCHECK,
            HealthCheck(retries=2, interval=timedelta(seconds=2)),
        ),
        (
            CONTAINER_WITH_HEALTHCHECK,
            HealthCheck(
                interval=timedelta(seconds=5), timeout=timedelta(seconds=1)
            ),
        ),
        (LEAP, None),
        (
            _failing_healthcheck_container("--retries=16"),
            HealthCheck(retries=16),
        ),
        (
            _failing_healthcheck_container("--interval=21s"),
            HealthCheck(interval=timedelta(seconds=21)),
        ),
        (
            _failing_healthcheck_container("--timeout=15s"),
            HealthCheck(timeout=timedelta(seconds=15)),
        ),
        (
            _failing_healthcheck_container("--start-period=24s"),
            HealthCheck(start_period=timedelta(seconds=24)),
        ),
    ],
    indirect=["container"],
)
def test_healthcheck_timeout(
    container: ContainerData, healthcheck: Optional[HealthCheck]
) -> None:
    assert container.inspect.config.healthcheck == healthcheck


@pytest.mark.skipif(
    not get_selected_runtime().supports_healthcheck_inherit_from_base,
    reason="Runtime does not inheriting HEALTHCHECK from base images",
)
@pytest.mark.parametrize(
    "container", [CONTAINER_DERIVING_FROM_HEALTHCHECK], indirect=True
)
def test_image_deriving_from_healthcheck_has_healthcheck(
    container: ContainerData, container_runtime: OciRuntimeBase
) -> None:
    assert (
        container_runtime.get_container_health(container.container_id)
        == ContainerHealth.HEALTHY
    )


def test_container_that_doesnt_run_is_reported_unhealthy(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    before = datetime.now()
    with pytest.raises(RuntimeError) as rt_err_ctx:
        with ContainerLauncher(
            container=CONTAINER_THAT_FAILS_TO_LAUNCH_WITH_FAILING_HEALTHCHECK,
            container_runtime=container_runtime,
            rootdir=pytestconfig.rootpath,
        ) as launcher:
            launcher.launch_container()
            assert False, "The container must fail to launch"
    after = datetime.now()

    time_to_fail = after - before
    assert time_to_fail < timedelta(seconds=15), (
        f"container must fail quickly (threshold 15s), but it took {time_to_fail.total_seconds()}"
    )
    assert "not running, got " in str(rt_err_ctx.value)


def test_container_launcher_logs_correct_healthcheck_timeout(
    container_runtime: OciRuntimeBase,
    pytestconfig: pytest.Config,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    ctr = DerivedContainer(
        base=LEAP_URL,
        image_format=ImageFormat.DOCKER,
        containerfile="HEALTHCHECK --retries=5 --timeout=10s --interval=10s CMD true",
    )
    with ContainerLauncher(
        container=ctr,
        container_runtime=container_runtime,
        rootdir=pytestconfig.rootpath,
    ) as launcher:
        launcher.launch_container()
        assert launcher.container_data.inspect.config.healthcheck
        timeout = (
            launcher.container_data.inspect.config.healthcheck.max_wait_time
        )
        assert timeout == timedelta(seconds=60)

    assert (
        "Container has a healthcheck defined, will wait at most 60.0 s"
        in caplog.text
    )
