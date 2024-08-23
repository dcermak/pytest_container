# pylint: disable=missing-function-docstring,missing-module-docstring
import pytest
from pytest_container.container import ContainerImageData
from pytest_container.container import DerivedContainer

from tests.images import LEAP


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
