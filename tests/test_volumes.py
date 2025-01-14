# pylint: disable=missing-function-docstring,missing-module-docstring
import os
from os.path import abspath
from os.path import join
from typing import List

import pytest

from pytest_container.container import BindMount
from pytest_container.container import BindMountCreator
from pytest_container.container import ContainerData
from pytest_container.container import ContainerVolume
from pytest_container.container import ContainerVolumeBase
from pytest_container.container import DerivedContainer
from pytest_container.container import VolumeFlag
from pytest_container.container import get_volume_creator
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import OciRuntimeBase

from .images import LEAP_URL


@pytest.mark.parametrize(
    "volume,expected_flag",
    [
        (ContainerVolume("/foo"), VolumeFlag.SELINUX_PRIVATE),
        (ContainerVolume("/foo", shared=True), VolumeFlag.SELINUX_SHARED),
    ],
)
def test_adds_selinux(volume: ContainerVolumeBase, expected_flag: VolumeFlag):
    assert len(volume.flags) == 1
    assert volume.flags[0] == expected_flag


@pytest.mark.parametrize(
    "volume,flags",
    [
        (ContainerVolume("/foo", flags=[]), []),
        (
            ContainerVolume("/bar/", flags=[VolumeFlag.READ_ONLY]),
            [VolumeFlag.READ_ONLY],
        ),
    ],
)
def test_does_not_add_selinux_if_flags_is_list(
    volume: ContainerVolumeBase, flags: List[VolumeFlag]
) -> None:
    assert volume.flags == flags


@pytest.mark.parametrize(
    "flags",
    [
        [VolumeFlag.SELINUX_SHARED, VolumeFlag.SELINUX_PRIVATE],
        [VolumeFlag.READ_WRITE, VolumeFlag.READ_ONLY],
    ],
)
def test_errors_on_mutually_exclusive_flags(flags: List[VolumeFlag]):
    with pytest.raises(ValueError) as val_err_ctx:
        ContainerVolume("/foo", flags=flags)

    assert "mutually exclusive" in str(val_err_ctx)


@pytest.mark.parametrize(
    "vol,expected_cli",
    [
        (BindMount("/src", host_path="/bar"), "-v=/bar:/src:Z"),
        (
            BindMount(
                "/src",
                host_path="/bar",
                flags=[VolumeFlag.READ_ONLY, VolumeFlag.SELINUX_SHARED],
            ),
            "-v=/bar:/src:ro,z",
        ),
    ],
)
def test_cli_arg(vol: ContainerVolumeBase, expected_cli: str):
    assert vol.cli_arg == expected_cli


def test_bind_mount_host_path() -> None:
    vol = BindMount("/foo")

    with BindMountCreator(vol) as _:
        assert vol.host_path

    assert not vol.host_path


@pytest.mark.parametrize("vol", [BindMount("/foo"), ContainerVolume("/foo")])
def test_volume_re_create(
    vol: ContainerVolumeBase, container_runtime: OciRuntimeBase
) -> None:
    vol = BindMount("/foo")

    for _ in range(10):
        with get_volume_creator(vol, container_runtime) as _:
            if isinstance(vol, BindMount):
                assert vol.host_path
            elif isinstance(vol, ContainerVolume):
                assert vol.volume_id
            else:
                assert False


LEAP_WITH_VOLUMES = DerivedContainer(
    base=LEAP_URL, volume_mounts=[BindMount("/foo"), BindMount("/bar")]
)


@pytest.mark.parametrize(
    "container_per_test", [LEAP_WITH_VOLUMES], indirect=True
)
def test_container_host_volumes(container_per_test: ContainerData):
    assert len(container_per_test.container.volume_mounts) == 2
    for vol in container_per_test.container.volume_mounts:
        assert isinstance(vol, BindMount)
        assert vol.host_path
        dir_on_host = LOCALHOST.file(vol.host_path)
        assert dir_on_host.exists and dir_on_host.is_directory

        dir_in_container = container_per_test.connection.file(
            vol.container_path
        )
        assert dir_in_container.exists and dir_in_container.is_directory


@pytest.mark.parametrize(
    "flags", [[VolumeFlag.SELINUX_SHARED], [VolumeFlag.SELINUX_PRIVATE]]
)
def test_does_not_add_selinux_flags_if_present(flags: List[VolumeFlag]):
    assert ContainerVolume(flags=flags, container_path="/foo").flags == flags


@pytest.mark.parametrize(
    "container_per_test", [LEAP_WITH_VOLUMES], indirect=True
)
def test_container_volume_host_writing(container_per_test: ContainerData):
    vol = container_per_test.container.volume_mounts[0]
    assert isinstance(vol, BindMount)
    assert vol.host_path

    host_dir = LOCALHOST.file(vol.host_path)
    assert not host_dir.listdir()

    container_dir = container_per_test.connection.file(vol.container_path)
    assert not container_dir.listdir()

    contents = """This is just a testfile

- there is nothing to see, please carry on"""

    with open(join(vol.host_path, "test"), "w", encoding="utf8") as testfile:
        testfile.write(contents)

    testfile_in_container = container_per_test.connection.file(
        join(vol.container_path, "test")
    )
    assert (
        testfile_in_container.exists
        and testfile_in_container.is_file
        and testfile_in_container.content_string == contents
    )

    # check that the file does not appear in the second mount
    vol2 = container_per_test.container.volume_mounts[1]
    assert not container_per_test.connection.file(
        vol2.container_path
    ).listdir()


LEAP_WITH_CONTAINER_VOLUMES = DerivedContainer(
    base=LEAP_URL,
    volume_mounts=[ContainerVolume("/foo"), ContainerVolume("/bar")],
)


@pytest.mark.parametrize(
    "container_per_test", [LEAP_WITH_CONTAINER_VOLUMES], indirect=True
)
def test_container_volumes(container_per_test: ContainerData):
    assert len(container_per_test.container.volume_mounts) == 2
    for vol in container_per_test.container.volume_mounts:
        dir_in_container = container_per_test.connection.file(
            join("/", vol.container_path)
        )
        assert dir_in_container.exists and dir_in_container.is_directory


@pytest.mark.parametrize(
    "container_per_test", [LEAP_WITH_CONTAINER_VOLUMES], indirect=True
)
def test_container_volume_writeable(container_per_test: ContainerData):
    vol = container_per_test.container.volume_mounts[0]
    assert isinstance(vol, ContainerVolume) and vol.volume_id

    container_dir = container_per_test.connection.file(vol.container_path)
    assert not container_dir.listdir()

    contents = "OK"
    container_per_test.connection.run_expect(
        [0], f"bash -c 'echo -n {contents} > {vol.container_path}/test'"
    )

    testfile_in_container = container_per_test.connection.file(
        join(vol.container_path, "test")
    )
    assert (
        testfile_in_container.exists
        and testfile_in_container.is_file
        and testfile_in_container.content_string == contents
    )

    # check that the file does not appear in the second mount
    vol2 = container_per_test.container.volume_mounts[1]
    assert not container_per_test.connection.file(
        vol2.container_path
    ).listdir()


LEAP_WITH_BIND_MOUNT_AND_VOLUME = DerivedContainer(
    base=LEAP_URL, volume_mounts=[BindMount("/foo"), ContainerVolume("/bar")]
)


@pytest.mark.parametrize(
    "container_per_test",
    [LEAP_WITH_BIND_MOUNT_AND_VOLUME for _ in range(10)],
    indirect=True,
)
def test_concurrent_container_volumes(container_per_test: ContainerData):
    """Test that containers can be launched using the same ContainerVolume or
    BindMount and do not influence each other.

    """
    assert container_per_test.container.volume_mounts

    for vol in container_per_test.container.volume_mounts:
        assert container_per_test.connection.file(vol.container_path).exists
        assert not container_per_test.connection.file(
            vol.container_path
        ).listdir()

        container_per_test.connection.run_expect(
            [0], f"echo > {vol.container_path}/test_file"
        )


LEAP_WITH_ROOTDIR_BIND_MOUNTED = DerivedContainer(
    base=LEAP_URL,
    volume_mounts=[
        BindMount(
            "/src/",
            host_path=join(abspath(os.getcwd()), "tests"),
        )
    ],
)


@pytest.mark.parametrize(
    "container", [LEAP_WITH_ROOTDIR_BIND_MOUNTED], indirect=True
)
def test_bind_mount_cwd(container: ContainerData):
    vol = container.container.volume_mounts[0]
    assert isinstance(vol, BindMount)
    assert container.connection.file("/src/").exists and sorted(
        container.connection.file("/src/").listdir()
    ) == sorted(LOCALHOST.file(vol.host_path).listdir())


def test_bind_mount_fails_when_host_path_not_present() -> None:
    vol = BindMount(
        "/src/", host_path="/path/to/something/that/should/be/absent"
    )
    with pytest.raises(RuntimeError) as runtime_err_ctx:
        with BindMountCreator(vol) as _:
            pass

    assert "directory does not exist" in str(runtime_err_ctx.value)
