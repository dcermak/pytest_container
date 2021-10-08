from pytest_container import Container
from pytest_container import DerivedContainer

import pytest

LEAP = Container(url="registry.opensuse.org/opensuse/leap:latest")

LEAP_WITH_MAN = DerivedContainer(
    base=LEAP, containerfile="RUN zypper -n in man"
)

LEAP_WITH_MAN_AND_LUA = DerivedContainer(
    base=LEAP_WITH_MAN, containerfile="RUN zypper -n in lua"
)

BUSYBOX_WITH_ENTRYPOINT = Container(
    url="registry.opensuse.org/opensuse/busybox:latest",
    custom_entry_point="/bin/sh",
)

SLEEP_CONTAINER = DerivedContainer(
    base="registry.opensuse.org/opensuse/leap:latest",
    containerfile="""ENTRYPOINT ["/usr/bin/sleep", "3600"]""",
    default_entry_point=True,
)

CONTAINER_IMAGES = [LEAP, LEAP_WITH_MAN, LEAP_WITH_MAN_AND_LUA]


@pytest.mark.parametrize("container", [LEAP], indirect=["container"])
def test_leap(container):
    assert container.connection.file("/etc/os-release").exists
    assert not container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize("container", [LEAP_WITH_MAN], indirect=["container"])
def test_leap_with_man(container):
    assert container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize(
    "container", [LEAP_WITH_MAN_AND_LUA], indirect=["container"]
)
def test_leap_with_man_and_info(container):
    assert container.connection.exists("man")
    assert container.connection.exists("lua")


def test_container_objects():
    for cont in CONTAINER_IMAGES:
        assert cont.get_base() == LEAP


def test_auto_container_fixture(auto_container):
    auto_container.connection.file("/etc/os-release").exists


@pytest.mark.parametrize(
    "container", [BUSYBOX_WITH_ENTRYPOINT], indirect=["container"]
)
def test_custom_entry_point(container):
    container.connection.run_expect([0], "true")


@pytest.mark.parametrize(
    "container", [SLEEP_CONTAINER], indirect=["container"]
)
def test_default_entry_point(container):
    sleep = container.connection.process.filter(comm="sleep")
    assert len(sleep) == 1
    assert "/usr/bin/sleep 3600" == sleep[0].args
