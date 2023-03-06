# pylint: disable=missing-function-docstring,missing-module-docstring
import os
from time import sleep
from typing import Any

import pytest

from .images import CONTAINER_THAT_FAILS_TO_LAUNCH
from .images import LEAP
from .test_volumes import LEAP_WITH_BIND_MOUNT_AND_VOLUME
from .test_volumes import LEAP_WITH_CONTAINER_VOLUMES
from .test_volumes import LEAP_WITH_VOLUMES
from pytest_container import inspect
from pytest_container.container import BindMount
from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import ContainerVolume
from pytest_container.container import DerivedContainer
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


LEAP_WITH_VOLUME_IN_DOCKERFILE = DerivedContainer(
    base=LEAP, containerfile="VOLUME /foo"
)


@pytest.mark.parametrize("cont", [LEAP_WITH_VOLUME_IN_DOCKERFILE])
def test_launcher_cleanes_up_volumes_from_image(
    cont: DerivedContainer,
    pytestconfig: pytest.Config,
    container_runtime: OciRuntimeBase,
    host: Any,
) -> None:
    with ContainerLauncher(
        cont, container_runtime, pytestconfig.rootpath
    ) as launcher:
        container = launcher.container_data.container
        assert not container.volume_mounts

        mounts = launcher.container_data.inspect.mounts
        assert (
            len(mounts) == 1
            and isinstance(mounts[0], inspect.VolumeMount)
            and mounts[0].destination == "/foo"
        )

        vol_name = mounts[0].name
    assert (
        "Error:"
        in host.run_expect(
            [1, 125],
            f"{container_runtime.runner_binary} volume inspect {vol_name}",
        ).stderr
    )


def test_launcher_container_data_not_available_after_exit(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    with ContainerLauncher(
        LEAP, container_runtime, pytestconfig.rootpath
    ) as launcher:
        assert launcher.container_data

    with pytest.raises(RuntimeError) as runtime_err_ctx:
        _ = launcher.container_data

    assert f"{LEAP} has not started" in str(runtime_err_ctx.value)


def test_launcher_fails_on_failing_healthcheck(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config, host
):
    container_name = "container_with_failing_healthcheck"
    with pytest.raises(RuntimeError) as runtime_err_ctx:
        with ContainerLauncher(
            container=CONTAINER_THAT_FAILS_TO_LAUNCH,
            container_runtime=container_runtime,
            rootdir=pytestconfig.rootpath,
            container_name=container_name,
        ) as _:
            pass

    # manually delete the container as pytest prevents the __exit__() block from
    # running
    host.run_expect(
        [0], f"{container_runtime.runner_binary} rm -f {container_name}"
    )

    assert "did not become healthy within" in str(runtime_err_ctx.value)
