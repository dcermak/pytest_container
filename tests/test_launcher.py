# pylint: disable=missing-function-docstring,missing-module-docstring
import os
import tempfile
from pathlib import Path
from subprocess import CalledProcessError
from time import sleep
from typing import Any

import pytest
from pytest_container import inspect
from pytest_container.container import BindMount
from pytest_container.container import Container
from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import ContainerVolume
from pytest_container.container import DerivedContainer
from pytest_container.container import EntrypointSelection
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import OciRuntimeBase

from .images import CMDLINE_APP_CONTAINER
from .images import CONTAINER_THAT_FAILS_TO_LAUNCH
from .images import LEAP
from .test_volumes import LEAP_WITH_BIND_MOUNT_AND_VOLUME
from .test_volumes import LEAP_WITH_CONTAINER_VOLUMES
from .test_volumes import LEAP_WITH_VOLUMES


LEAP_WITH_STOPSIGNAL_SIGKILL = DerivedContainer(
    base=LEAP,
    containerfile="STOPSIGNAL SIGKILL",
    entry_point=EntrypointSelection.BASH,
)

LEAP_WITH_STOPSIGNAL_SIGKILL_AND_ENTRYPOINT = DerivedContainer(
    base=LEAP,
    containerfile="STOPSIGNAL SIGKILL",
    entry_point=EntrypointSelection.IMAGE,
)

LEAP_WITH_STOPSIGNAL_SIGKILL_AND_CUSTOM_ENTRYPOINT = DerivedContainer(
    base=LEAP,
    containerfile="STOPSIGNAL SIGKILL",
    custom_entry_point="/bin/sh",
)

PYTHON_LEAP = DerivedContainer(
    base=LEAP,
    containerfile="""
RUN set -euxo pipefail; zypper -n ref; zypper -n in python3 curl;

ENTRYPOINT ["/usr/bin/python3"]
CMD ["-m", "http.server"]
""",
)


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
        launcher.launch_container()

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
        launcher.launch_container()

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
        "no such volume"
        in host.run_expect(
            [1, 125],
            f"{container_runtime.runner_binary} volume inspect {vol_name}",
        ).stderr.lower()
    )


def test_launcher_container_data_not_available_after_exit(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    with ContainerLauncher(
        LEAP, container_runtime, pytestconfig.rootpath
    ) as launcher:
        launcher.launch_container()
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
        ) as launcher:
            launcher.launch_container()
            assert False, "This code must be unreachable"

    assert "did not become healthy within" in str(runtime_err_ctx.value)

    # the container must not exist anymore
    err_msg = host.run_expect(
        [1, 125],
        f"{container_runtime.runner_binary} inspect {container_name}",
    ).stderr
    assert ("no such object" in err_msg.lower()) or (
        "error getting image" in err_msg
    )


@pytest.mark.parametrize(
    "container", [LEAP_WITH_STOPSIGNAL_SIGKILL], indirect=True
)
def test_launcher_overrides_stopsignal(container: ContainerData) -> None:
    """Verify that we override the stop signal by default to ``SIGTERM`` as we
    launch containers with :file:`/bin/bash` as the entrypoint.

    """
    assert container.inspect.config.stop_signal in (15, "SIGTERM")


@pytest.mark.parametrize(
    "container",
    [
        LEAP_WITH_STOPSIGNAL_SIGKILL_AND_ENTRYPOINT,
        LEAP_WITH_STOPSIGNAL_SIGKILL_AND_CUSTOM_ENTRYPOINT,
    ],
    indirect=True,
)
def test_launcher_does_not_override_stopsignal_for_entrypoint(
    container: ContainerData,
) -> None:
    """Check that the stop signal is **not** modified when the attribute
    `default_entry_point` is ``True`` (then we assume that the stop signal has
    been set to the appropriate value by the author of the image).

    """
    assert container.inspect.config.stop_signal in (9, "SIGKILL")


@pytest.mark.parametrize(
    "container",
    [
        CMDLINE_APP_CONTAINER,
    ],
    indirect=True,
)
def test_launcher_does_can_check_binaries_with_entrypoint(
    container: ContainerData,
) -> None:
    """Check that the we can check for installed binaries even if the container
    has an entrypoint specified that is not a shell and terminates immediately.
    """
    assert container.connection.exists("bash")


def test_derived_container_pulls_base(
    container_runtime: OciRuntimeBase, host: Any, pytestconfig: pytest.Config
) -> None:
    registry_url = "registry.opensuse.org/opensuse/registry:latest"

    # remove the container image so that the preparation in the launcher must
    # pull the image
    host.run(f"{container_runtime.runner_binary} rmi {registry_url}")

    reg = DerivedContainer(base=registry_url)
    with ContainerLauncher(
        reg, container_runtime, pytestconfig.rootpath
    ) as launcher:
        launcher.launch_container()
        assert launcher.container_data.container_id


def test_launcher_unlocks_on_preparation_failure(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    container_with_wrong_url = Container(
        url="registry.invalid.xyz.foobar/i/should/not/exist:42"
    )

    def try_launch():
        with pytest.raises(CalledProcessError):
            with ContainerLauncher(
                container_with_wrong_url,
                container_runtime,
                pytestconfig.rootpath,
            ) as launcher:
                launcher.launch_container()
                assert False, "The container must not have launched"

    try_launch()
    # not the best as we are testing an internal implementation detail
    assert not Path(
        tempfile.gettempdir(), container_with_wrong_url.filelock_filename
    ).exists()


@pytest.mark.parametrize(
    "container,port_num",
    [
        (
            DerivedContainer(
                base=PYTHON_LEAP,
                extra_entrypoint_args=["-m", "http.server", "8080"],
            ),
            8080,
        ),
        (PYTHON_LEAP, 8000),
    ],
    indirect=["container"],
)
def test_extra_command_args(container: ContainerData, port_num: int) -> None:
    print(id(container.container))
    assert container.connection.check_output(
        f"curl http://localhost:{port_num}"
    )
