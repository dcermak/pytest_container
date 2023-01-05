# pylint: disable=missing-function-docstring,missing-module-docstring
import os
from time import sleep
from typing import Any

import pytest

from .test_container_build import LEAP
from .test_volumes import LEAP_WITH_BIND_MOUNT_AND_VOLUME
from .test_volumes import LEAP_WITH_CONTAINER_VOLUMES
from .test_volumes import LEAP_WITH_VOLUMES
from pytest_container.container import BindMount
from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import ContainerVolume
from pytest_container.container import DerivedContainer
from pytest_container.container import ImageFormat
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import OciRuntimeBase


def _test_func(con: Any) -> None:
    sleep(5)
    assert "Leap" in con.run_expect([0], "cat /etc/os-release").stdout


@pytest.mark.parametrize("container", [LEAP], indirect=True)
def test_cleanup_not_immediate(container: ContainerData) -> None:
    _test_func(container.connection)


@pytest.mark.parametrize("container_per_test", [LEAP], indirect=True)
def test_cleanup_not_immediate_per_test(
    container_per_test: ContainerData,
) -> None:
    _test_func(container_per_test.connection)


@pytest.mark.parametrize(
    "cont",
    [
        LEAP_WITH_VOLUMES,
        LEAP_WITH_CONTAINER_VOLUMES,
        LEAP_WITH_BIND_MOUNT_AND_VOLUME,
    ],
)
def test_launcher_creates_and_cleanes_up_volumes(
    cont: DerivedContainer,
    pytestconfig: pytest.Config,
    container_runtime: OciRuntimeBase,
) -> None:
    with ContainerLauncher(
        cont, container_runtime, pytestconfig.rootpath
    ) as launcher:
        container = launcher.container_data.container
        assert container.volume_mounts

        for vol in container.volume_mounts:

            if isinstance(vol, BindMount):
                assert vol.host_path and os.path.exists(vol.host_path)
            elif isinstance(vol, ContainerVolume):
                assert vol.volume_id
                assert LOCALHOST.run_expect(
                    [0],
                    f"{container_runtime.runner_binary} volume inspect {vol.volume_id}",
                )
            else:
                assert False, f"invalid volume type {type(vol)}"

    for vol in container.volume_mounts:
        if isinstance(vol, BindMount):
            assert not vol.host_path
        elif isinstance(vol, ContainerVolume):
            assert not vol.volume_id
        else:
            assert False, f"invalid volume type {type(vol)}"


CONTAINER_THAT_FAILS_TO_LAUNCH = DerivedContainer(
    base=LEAP,
    image_format=ImageFormat.DOCKER,
    containerfile="""CMD sleep 600
# use a short timeout to keep the test run short
HEALTHCHECK --retries=1 --interval=1s --timeout=1s CMD false
""",
)


def test_launcher_fails_on_failing_healthcheck(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
):
    with pytest.raises(RuntimeError) as runtime_err_ctx:
        with ContainerLauncher(
            container=CONTAINER_THAT_FAILS_TO_LAUNCH,
            container_runtime=container_runtime,
            rootdir=pytestconfig.rootpath,
        ) as _:
            pass

    assert "did not become healthy within" in str(runtime_err_ctx.value)
