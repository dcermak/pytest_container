from pathlib import Path
from pytest_container import Container
from pytest_container import DerivedContainer
from pytest_container import get_extra_build_args
from pytest_container.build import MultiStageBuild
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import OciRuntimeBase

import pytest
from _pytest.config import Config

LEAP = Container(url="registry.opensuse.org/opensuse/leap:latest")

TAG1 = "local/foobar/bazbarf"

LEAP_WITH_TAG = DerivedContainer(
    base=LEAP.url, add_build_tags=[TAG1, "localhost/opensuse/leap/man:latest"]
)

# HACK: create this container before collecting tests… dirty, but otherwise the
# local container test fails because we cannot really express a dependency on
# the local image
LEAP_WITH_TAG.prepare_container(Path("."))

LEAP_WITH_MAN = DerivedContainer(
    base=LEAP,
    containerfile="RUN zypper -n in man",
)

LEAP_WITH_MAN_AND_LUA = DerivedContainer(
    base=LEAP_WITH_MAN, containerfile="RUN zypper -n in lua"
)

LOCAL_CONTAINER = Container(url=f"containers-storage:{TAG1}")

BUSYBOX_WITH_ENTRYPOINT = Container(
    url="registry.opensuse.org/opensuse/busybox:latest",
    custom_entry_point="/bin/sh",
)
#: This is just a busybox container with 4MB of random data in there
BUSYBOX_WITH_GARBAGE = DerivedContainer(
    base=BUSYBOX_WITH_ENTRYPOINT,
    containerfile="""RUN dd if=/dev/random of=/foobar bs=4M count=1
""",
)

SLEEP_CONTAINER = DerivedContainer(
    base="registry.opensuse.org/opensuse/leap:latest",
    containerfile="""ENTRYPOINT ["/usr/bin/sleep", "3600"]""",
    default_entry_point=True,
)

CONTAINER_IMAGES = [LEAP, LEAP_WITH_MAN, LEAP_WITH_MAN_AND_LUA]

MULTI_STAGE_BUILD = MultiStageBuild(
    containers={
        "builder": LEAP_WITH_MAN,
        "runner1": LEAP,
        "runner2": "docker.io/alpine",
    },
    containerfile_template=r"""FROM $builder as builder
WORKDIR /src
RUN echo $$'#!/bin/sh \n\
echo "foobar"' > test.sh && chmod +x test.sh

FROM $runner1 as runner1
WORKDIR /bin
COPY --from=builder /src/test.sh .
ENTRYPOINT ["/bin/test.sh"]

FROM $runner2 as runner2
WORKDIR /bin
COPY --from=builder /src/test.sh .
""",
)


@pytest.mark.parametrize("container", [LEAP], indirect=["container"])
def test_leap(container):
    assert container.connection.file("/etc/os-release").exists
    assert not container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize("container", [LEAP], indirect=["container"])
def test_container_data(container):
    assert container.container_id
    assert container.image_url_or_id == LEAP.url
    assert container.container == LEAP


@pytest.mark.parametrize("container", [LOCAL_CONTAINER], indirect=True)
def test_local_container_image_ref(container):
    assert container.connection.file("/etc/os-release").exists
    assert (
        'ID="opensuse-leap"'
        in container.connection.file("/etc/os-release").content_string
    )


@pytest.mark.parametrize("container", [LEAP_WITH_MAN], indirect=["container"])
def test_leap_with_man(container):
    assert container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize("container", [LEAP_WITH_MAN], indirect=["container"])
def test_derived_container_data(container):
    assert container.container_id
    assert container.image_url_or_id == LEAP_WITH_MAN.container_id
    assert container.container == LEAP_WITH_MAN


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


def test_container_size(container_runtime: OciRuntimeBase, pytestconfig):
    for container in [BUSYBOX_WITH_ENTRYPOINT, BUSYBOX_WITH_GARBAGE]:
        container.prepare_container(pytestconfig.rootdir)

    assert container_runtime.get_image_size(
        BUSYBOX_WITH_ENTRYPOINT
    ) < container_runtime.get_image_size(BUSYBOX_WITH_GARBAGE)
    assert (
        container_runtime.get_image_size(BUSYBOX_WITH_ENTRYPOINT)
        - container_runtime.get_image_size(BUSYBOX_WITH_GARBAGE)
        < 4096 * 1024 * 1024
    )


def test_multistage_containerfile():
    assert "FROM docker.io/alpine" in MULTI_STAGE_BUILD.containerfile


def test_multistage_build(tmp_path, pytestconfig, container_runtime):
    MULTI_STAGE_BUILD.build(
        tmp_path,
        pytestconfig.rootdir,
        container_runtime,
        extra_build_args=get_extra_build_args(pytestconfig),
    )


def test_multistage_build_target(
    tmp_path, pytestconfig: Config, container_runtime
):
    first_target = MULTI_STAGE_BUILD.build(
        tmp_path,
        pytestconfig.rootdir,
        container_runtime,
        "runner1",
        extra_build_args=get_extra_build_args(pytestconfig),
    )
    assert (
        LOCALHOST.run_expect(
            [0],
            f"{container_runtime.runner_binary} run --rm {first_target}",
        ).stdout.strip()
        == "foobar"
    )

    second_target = MULTI_STAGE_BUILD.build(
        tmp_path,
        pytestconfig,
        container_runtime,
        "runner2",
        extra_build_args=get_extra_build_args(pytestconfig),
    )

    assert first_target != second_target
    assert (
        LOCALHOST.run_expect(
            [0],
            f"{container_runtime.runner_binary} run --rm {second_target} /bin/test.sh",
        ).stdout.strip()
        == "foobar"
    )

    for (distro, target) in (
        ("Leap", first_target),
        ("Alpine", second_target),
    ):
        assert (
            distro
            in LOCALHOST.run_expect(
                [0],
                f"{container_runtime.runner_binary} run --rm --entrypoint= {target} cat /etc/os-release",
            ).stdout.strip()
        )
