from datetime import timedelta
from pytest_container.container import DerivedContainer
from pytest_container.container import ImageFormat
from pytest_container.runtime import ContainerHealth
from pytest_container.runtime import HealthCheck
from pytest_container.runtime import OciRuntimeBase
from time import sleep

import pytest

from tests.base.test_container_build import LEAP


CONTAINER_WITH_HEALTHCHECK = DerivedContainer(
    base=LEAP,
    default_entry_point=True,
    image_format=ImageFormat.DOCKER,
    # iproute2 is needed for checking the socket connection
    containerfile="""RUN zypper -n in python3 curl iproute2
EXPOSE 8000
CMD /usr/bin/python3 -c "import http.server; import os; from time import sleep; sleep(5); http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler)"
HEALTHCHECK --interval=5s --timeout=1s CMD curl --fail http://0.0.0.0:8000
""",
)


def _failing_healthcheck_container(healtcheck_args: str) -> DerivedContainer:
    return DerivedContainer(
        base=LEAP,
        image_format=ImageFormat.DOCKER,
        containerfile=f"""CMD sleep 600
HEALTHCHECK {healtcheck_args} CMD false
""",
        healthcheck_timeout=timedelta(seconds=-1),
    )


CONTAINER_WITH_FAILING_HEALTHCHECK = _failing_healthcheck_container(
    "--retries=2 --interval=2s"
)


@pytest.mark.parametrize(
    "container", [CONTAINER_WITH_HEALTHCHECK], indirect=True
)
def test_container_healthcheck(container, container_runtime: OciRuntimeBase):
    assert (
        container_runtime.get_container_health(container.container_id)
        == ContainerHealth.HEALTHY
    )
    assert container.connection.socket("tcp://0.0.0.0:8000").is_listening


@pytest.mark.parametrize("container", [LEAP], indirect=True)
def test_container_without_healthcheck(
    container, container_runtime: OciRuntimeBase
):
    assert (
        container_runtime.get_container_health(container.container_id)
        == ContainerHealth.NO_HEALTH_CHECK
    )


@pytest.mark.parametrize(
    "container", [CONTAINER_WITH_FAILING_HEALTHCHECK], indirect=True
)
def test_container_with_failing_healthcheck(
    container, container_runtime: OciRuntimeBase
):
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
    container, container_runtime: OciRuntimeBase, healthcheck: HealthCheck
):
    assert (
        container_runtime.get_container_healthcheck(container.container)
        == healthcheck
    )
