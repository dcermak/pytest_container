from pytest_container.container import DerivedContainer
from pytest_container.container import ImageFormat
from pytest_container.runtime import ContainerHealth
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

CONTAINER_WITH_FAILING_HEALTHCHECK = DerivedContainer(
    base=LEAP,
    image_format=ImageFormat.DOCKER,
    containerfile="""CMD sleep 600
HEALTHCHECK --retries=2 --interval=2s CMD false""",
    healthcheck_timeout=None,
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
