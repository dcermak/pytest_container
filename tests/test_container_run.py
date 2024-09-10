# pylint: disable=missing-function-docstring,missing-module-docstring
import pytest
from pytest_container.container import ContainerImageData
from pytest_container.container import ContainerLauncher
from pytest_container.container import DerivedContainer
from pytest_container.runtime import OciRuntimeBase

from tests.images import LEAP
from tests.test_volumes import LEAP_WITH_BIND_MOUNT_AND_VOLUME


@pytest.mark.parametrize("container_image", [LEAP], indirect=True)
def test_run_leap(container_image: ContainerImageData, host) -> None:
    assert 'NAME="openSUSE Leap"' in host.check_output(
        f"{container_image.run_command} cat /etc/os-release"
    )


CTR_WITH_ENTRYPOINT_ADDING_PATH = DerivedContainer(
    base=LEAP,
    containerfile="""RUN mkdir -p /usr/test/; \
    echo 'echo "foobar"' > /usr/test/foobar; \
    chmod +x /usr/test/foobar
RUN echo '#!/bin/sh' > /entrypoint.sh; \
    echo "export PATH=/usr/test/:$PATH" >> /entrypoint.sh; \
    echo 'exec "$@"' >> /entrypoint.sh; \
    chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
""",
)


@pytest.mark.parametrize(
    "container_image", [CTR_WITH_ENTRYPOINT_ADDING_PATH], indirect=True
)
def test_entrypoint_respected_in_run(
    container_image: ContainerImageData, host
) -> None:
    assert "foobar" in host.check_output(
        f"{container_image.run_command} foobar"
    )


@pytest.mark.parametrize(
    "container_image", [LEAP_WITH_BIND_MOUNT_AND_VOLUME], indirect=True
)
def test_volume_created_on_enter(
    container_image: ContainerImageData, host
) -> None:
    host.check_output(f"{container_image.run_command} stat /foo")
    host.check_output(f"{container_image.run_command} stat /bar")


def test_volume_destroyed_on_exit(
    host, pytestconfig: pytest.Config, container_runtime: OciRuntimeBase
) -> None:
    with ContainerLauncher.from_pytestconfig(
        LEAP_WITH_BIND_MOUNT_AND_VOLUME, container_runtime, pytestconfig
    ) as launcher:
        launcher.prepare_container_image()

        cid = launcher.container_image_data
        host.check_output(f"{cid.run_command} stat /foo")
        host.check_output(f"{cid.run_command} stat /bar")
