import pytest
from pytest_container import Container
from pytest_container import DerivedContainer

LEAP = Container(url="registry.opensuse.org/opensuse/leap:latest")

LEAP_WITH_MAN = DerivedContainer(
    base=LEAP, containerfile="RUN zypper -n in man"
)

LEAP_WITH_MAN_AND_LUA = DerivedContainer(
    base=LEAP_WITH_MAN, containerfile="RUN zypper -n in lua"
)


@pytest.mark.parametrize("container", [LEAP], indirect=["container"])
def test_tumbleweed(container):
    assert container.connection.file("/etc/os-release").exists
    assert not container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize("container", [LEAP_WITH_MAN], indirect=["container"])
def test_tumbleweed_with_man(container):
    assert container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize(
    "container", [LEAP_WITH_MAN_AND_LUA], indirect=["container"]
)
def test_tumbleweed_with_man_and_info(container):
    assert container.connection.exists("man")
    assert container.connection.exists("lua")


def test_container_objects():
    for cont in (
        LEAP,
        LEAP_WITH_MAN,
        LEAP_WITH_MAN_AND_LUA,
    ):
        assert cont.get_base() == LEAP
