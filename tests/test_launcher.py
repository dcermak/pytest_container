# pylint: disable=missing-function-docstring,missing-module-docstring
import os
import re
import subprocess
import tempfile
from pathlib import Path
from time import sleep
from typing import Any
from unittest.mock import call
from unittest.mock import Mock

import pytest
from pytest_container import inspect
from pytest_container.container import BindMount
from pytest_container.container import Container
from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import ContainerVolume
from pytest_container.container import DerivedContainer
from pytest_container.container import EntrypointSelection
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
    assert "Leap" in con.check_output("cat /etc/os-release")


@pytest.mark.parametrize("container", [LEAP], indirect=True)
def test_cleanup_not_immediate(container: ContainerData) -> None:
    _test_func(container.remote)


@pytest.mark.parametrize("container_per_test", [LEAP], indirect=True)
def test_cleanup_not_immediate_per_test(
    container_per_test: ContainerData,
) -> None:
    _test_func(container_per_test.remote)


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
    with ContainerLauncher.from_pytestconfig(
        cont, container_runtime, pytestconfig
    ) as launcher:
        launcher.launch_container()

        container = launcher.container_data.container
        assert container.volume_mounts

        for vol in container.volume_mounts:
            if isinstance(vol, BindMount):
                assert vol.host_path and os.path.exists(vol.host_path)
            elif isinstance(vol, ContainerVolume):
                assert vol.volume_id
                assert container_runtime.run_command(
                    "volume", "inspect", vol.volume_id
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
) -> None:
    with ContainerLauncher.from_pytestconfig(
        cont, container_runtime, pytestconfig
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

    with pytest.raises(subprocess.CalledProcessError) as runtime_err_ctx:
        container_runtime.run_command("volume", "inspect", vol_name)

    assert runtime_err_ctx.value.returncode in [1, 125]
    assert "no such volume" in runtime_err_ctx.value.stderr.lower()


def test_launcher_container_data_not_available_after_exit(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    with ContainerLauncher.from_pytestconfig(
        LEAP, container_runtime, pytestconfig
    ) as launcher:
        launcher.launch_container()
        assert launcher.container_data

    with pytest.raises(RuntimeError) as runtime_err_ctx:
        _ = launcher.container_data

    assert f"{LEAP} has not started" in str(runtime_err_ctx.value)


def test_launcher_fails_on_failing_healthcheck(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
):
    container_name = "container_with_failing_healthcheck"
    with pytest.raises(RuntimeError) as runtime_err_ctx:
        with ContainerLauncher.from_pytestconfig(
            container=CONTAINER_THAT_FAILS_TO_LAUNCH,
            container_runtime=container_runtime,
            pytestconfig=pytestconfig,
            container_name=container_name,
        ) as launcher:
            launcher.launch_container()
            assert False, "This code must be unreachable"

    err_msg_regex = re.compile(
        r"Container (\d|\w*) did not become healthy within (\d+\.\d+s),"
        r" took (\d+.\d+s) and state is (\w+)"
    )
    err_msg_match = err_msg_regex.match(str(runtime_err_ctx.value))
    assert err_msg_match, (
        f"Error message '{str(runtime_err_ctx.value)}' does "
        + "not match expected pattern {err_msg_regex}"
    )

    # the container must not exist anymore
    with pytest.raises(subprocess.CalledProcessError) as runtime_err_ctx:
        container_runtime.run_command("inspect", container_name)

    assert runtime_err_ctx.value.returncode in [1, 125]
    err_msg = runtime_err_ctx.value.stderr
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


@pytest.mark.parametrize("container", [CMDLINE_APP_CONTAINER], indirect=True)
def test_launcher_does_can_check_binaries_with_entrypoint(
    container: ContainerData,
) -> None:
    """Check that the we can check for installed binaries even if the container
    has an entrypoint specified that is not a shell and terminates immediately.
    """
    assert container.remote.exists("bash")


def test_derived_container_pulls_base(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    registry_url = "registry.opensuse.org/opensuse/registry:latest"

    # remove the container image so that the preparation in the launcher must
    # pull the image
    container_runtime.run_command("rmi", registry_url, ignore_errors=True)

    reg = DerivedContainer(base=registry_url)
    with ContainerLauncher.from_pytestconfig(
        reg, container_runtime, pytestconfig
    ) as launcher:
        launcher.launch_container()
        assert launcher.container_data.container_id


def test_pulls_container(
    container_runtime: OciRuntimeBase,
    pytestconfig: pytest.Config,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test of the pull-behavior switching via the environment variable
    ``PULL_ALWAYS``

    """
    quay_busybox = "quay.io/libpod/busybox"
    mock_runner = Mock()
    mock_runner.return_value = "[]"
    monkeypatch.setattr(container_runtime, "run_command", mock_runner)

    def _pull():
        Container(url=quay_busybox).prepare_container(
            container_runtime, pytestconfig.rootpath
        )

    # first test: should always pull the image
    monkeypatch.setenv("PULL_ALWAYS", "1")
    _pull()

    mock_runner.assert_has_calls(
        [
            call("pull", quay_busybox),
        ]
    )
    mock_runner.reset_mock()

    # second test: should only pull the image if inspect fails
    # in this case we mock the inspect call to return 0, i.e. image is there
    monkeypatch.setenv("PULL_ALWAYS", "0")
    mock_runner.return_value = '[{"Id": "1234"}]'
    _pull()
    mock_runner.assert_has_calls(
        [
            call("inspect", quay_busybox, ignore_errors=True),
        ]
    )
    mock_runner.reset_mock()

    # third test: pull the image if inspect fails, so we mock the inspect
    # call to return 1
    mock_runner.return_value = "[]"
    _pull()
    mock_runner.assert_has_calls(
        [
            call("inspect", quay_busybox, ignore_errors=True),
            call("pull", quay_busybox),
        ]
    )
    mock_runner.reset_mock()


def test_launcher_unlocks_on_preparation_failure(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    container_with_wrong_url = Container(
        url="registry.invalid.xyz.foobar/i/should/not/exist:42"
    )

    def try_launch():
        with pytest.raises(subprocess.CalledProcessError):
            with ContainerLauncher.from_pytestconfig(
                container_with_wrong_url,
                container_runtime,
                pytestconfig,
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
    assert container.remote.check_output(
        f"curl -sf --retry 5 --retry-connrefused http://localhost:{port_num}"
    )
