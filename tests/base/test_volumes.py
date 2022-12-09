# pylint: disable=missing-function-docstring,missing-module-docstring
import os.path
from pytest_container.container import ContainerData
from pytest_container.container import ContainerVolume
from pytest_container.container import DerivedContainer
from pytest_container.container import VolumeFlag
from pytest_container.runtime import LOCALHOST
from typing import List

import pytest

from tests.base.test_container_build import LEAP


@pytest.mark.parametrize(
    "volume,expected_flag",
    [
        (ContainerVolume("/foo"), VolumeFlag.SELINUX_PRIVATE),
        (ContainerVolume("/foo", shared=True), VolumeFlag.SELINUX_SHARED),
    ],
)
def test_adds_selinux(volume: ContainerVolume, expected_flag: VolumeFlag):
    assert len(volume.flags) == 1
    assert volume.flags[0] == expected_flag


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
        (ContainerVolume("/src", "/bar"), "-v=/bar:/src:Z"),
        (
            ContainerVolume(
                "/src",
                "/bar",
                flags=[VolumeFlag.READ_ONLY, VolumeFlag.SELINUX_SHARED],
            ),
            "-v=/bar:/src:ro,z",
        ),
    ],
)
def test_cli_arg(vol: ContainerVolume, expected_cli: str):
    assert vol.cli_arg == expected_cli


def test_volume_re_create():
    vol = ContainerVolume("/foo")

    for _ in range(10):
        vol.setup()
        vol.cleanup()


LEAP_WITH_VOLUMES = DerivedContainer(
    base=LEAP, volume_mounts=[ContainerVolume("/foo"), ContainerVolume("/bar")]
)


@pytest.mark.parametrize(
    "container_per_test", [LEAP_WITH_VOLUMES], indirect=True
)
def test_container_volumes(container_per_test: ContainerData):
    assert len(container_per_test.container.volume_mounts) == 2
    for vol in container_per_test.container.volume_mounts:
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
def test_container_volume_writing(container_per_test: ContainerData):
    vol = container_per_test.container.volume_mounts[0]
    assert vol.host_path

    host_dir = LOCALHOST.file(vol.host_path)
    assert not host_dir.listdir()

    container_dir = container_per_test.connection.file(vol.container_path)
    assert not container_dir.listdir()

    _CONTENTS = """This is just a testfile

- there is nothing to see, please carry on"""

    with open(os.path.join(vol.host_path, "test"), "w") as testfile:
        testfile.write(_CONTENTS)

    testfile_in_container = container_per_test.connection.file(
        os.path.join(vol.container_path, "test")
    )
    assert (
        testfile_in_container.exists
        and testfile_in_container.is_file
        and testfile_in_container.content_string == _CONTENTS
    )

    # check that the file does not appear in the second mount
    vol2 = container_per_test.container.volume_mounts[1]
    assert not container_per_test.connection.file(
        vol2.container_path
    ).listdir()
