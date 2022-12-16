# pylint: disable=missing-function-docstring,missing-module-docstring
from os import remove
from time import sleep

from _pytest.config import Config
from filelock import FileLock
from pytest_container import Container
from pytest_container import DerivedContainer
from pytest_container.container import ContainerData

from tests.base.test_container_build import BUSYBOX_WITH_ENTRYPOINT
from tests.base.test_container_build import LEAP

LEAP_WITH_LOCK = DerivedContainer(
    base=BUSYBOX_WITH_ENTRYPOINT,
    custom_entry_point="/bin/sh",
    singleton=True,
)
LEAP2_WITH_LOCK = Container(url=LEAP.url, singleton=True)

CONTAINER_IMAGES = [LEAP_WITH_LOCK, LEAP2_WITH_LOCK]


def actual_test(container_data: ContainerData, pytestconf: Config):
    """This is the actual test function which creates a lockfile for the two
    automatic containers and keeps them around for 5 seconds. If any other test
    runs in parallel during that time, it would error out.

    """
    container_data.connection.run_expect([0], "true")
    lockfile = pytestconf.rootpath / (
        "leap.lock"
        if "leap" in container_data.image_url_or_id
        else "busybox.lock"
    )

    assert not lockfile.exists()
    with FileLock(lockfile, timeout=0):
        sleep(5)

    if lockfile.exists():
        remove(lockfile)


def test_create_conflict_1(auto_container_per_test, pytestconfig: Config):
    actual_test(auto_container_per_test, pytestconfig)


def test_create_conflict_2(auto_container_per_test, pytestconfig: Config):
    actual_test(auto_container_per_test, pytestconfig)


def test_create_conflict_3(auto_container_per_test, pytestconfig: Config):
    actual_test(auto_container_per_test, pytestconfig)


def test_create_conflict_4(auto_container_per_test, pytestconfig: Config):
    actual_test(auto_container_per_test, pytestconfig)
