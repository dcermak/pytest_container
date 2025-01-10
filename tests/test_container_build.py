# pylint: disable=missing-function-docstring,missing-module-docstring
from pathlib import Path
from typing import Union

import pytest
from pytest import Config

from pytest_container import Container
from pytest_container import DerivedContainer
from pytest_container import get_extra_build_args
from pytest_container.build import MultiStageBuild
from pytest_container.container import BindMount
from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import EntrypointSelection
from pytest_container.inspect import PortForwarding
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import OciRuntimeBase

from .images import LEAP
from .images import LEAP_URL
from .images import LEAP_WITH_MAN
from .images import LEAP_WITH_MAN_AND_LUA
from .images import OPENSUSE_BUSYBOX_URL

TAG1 = "local/foobar/bazbarf"


LEAP_WITH_TAG = DerivedContainer(
    base=LEAP_URL,
    add_build_tags=[TAG1, "localhost/opensuse/leap/man:latest"],
)


BUSYBOX_WITH_ENTRYPOINT = Container(
    url=OPENSUSE_BUSYBOX_URL,
    custom_entry_point="/bin/sh",
)
#: This is just a busybox container with 4MB of random data in there
BUSYBOX_WITH_GARBAGE = DerivedContainer(
    base=BUSYBOX_WITH_ENTRYPOINT,
    containerfile="""RUN dd if=/dev/random of=/foobar bs=4M count=1
""",
)

SLEEP_CONTAINER = DerivedContainer(
    base=LEAP_URL,
    containerfile="""
# ps is needed for the tests to filter processes
RUN zypper -n in ps
ENTRYPOINT ["/usr/bin/sleep", "3600"]""",
)

LEAP2 = DerivedContainer(base=LEAP)

LEAP_WITH_BIN = DerivedContainer(
    base=LEAP,
    containerfile="""RUN zypper -n in system-user-bin
USER bin
""",
)

LEAP_WITH_BIN_AND_CMD = DerivedContainer(
    base=LEAP_WITH_BIN,
    containerfile="""CMD ["/usr/bin/sleep", "3600"]""",
    forwarded_ports=[PortForwarding(container_port=8080)],
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

# This container would just stop if we would launch it with -d and use the
# default entrypoint. If we set the entrypoint to bash, then it should stay up.
CONTAINER_THAT_STOPS = DerivedContainer(
    base=LEAP,
    containerfile="""ENTRYPOINT ["/bin/echo", "hello world"]""",
    entry_point=EntrypointSelection.BASH,
)


@pytest.mark.parametrize("container", [LEAP], indirect=["container"])
def test_leap(container: ContainerData):
    assert container.connection.file("/etc/os-release").exists
    assert not container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize("container", [LEAP], indirect=["container"])
def test_container_data(container: ContainerData):
    assert container.container_id
    assert container.image_url_or_id == LEAP.url
    assert container.container == LEAP


def test_local_container_image_ref(
    container_runtime: OciRuntimeBase, pytestconfig: Config
):
    LEAP_WITH_TAG.prepare_container(container_runtime, pytestconfig.rootpath)

    # this container only works if LEAP_WITH_TAG exists already
    local_container = Container(url=f"containers-storage:{TAG1}")

    with ContainerLauncher(
        local_container, container_runtime, pytestconfig.rootpath
    ) as launcher:
        launcher.launch_container()
        connection = launcher.container_data.connection
        assert connection.file("/etc/os-release").exists
        assert (
            'ID="opensuse-leap"'
            in connection.file("/etc/os-release").content_string
        )


@pytest.mark.parametrize("container", [LEAP_WITH_MAN], indirect=["container"])
def test_leap_with_man(container: ContainerData):
    assert container.connection.exists("man")
    assert not container.connection.exists("lua")


@pytest.mark.parametrize("container", [LEAP_WITH_MAN], indirect=["container"])
def test_derived_container_data(container: ContainerData):
    assert container.container_id
    assert container.image_url_or_id == LEAP_WITH_MAN.container_id
    assert container.container == LEAP_WITH_MAN


@pytest.mark.parametrize("container", [LEAP2], indirect=True)
def test_container_without_containerfile_and_without_tags_not_rebuild(
    container: ContainerData,
):
    assert (
        isinstance(container.container, DerivedContainer)
        and not container.container.containerfile
        and not container.container.add_build_tags
    )
    assert container.container.get_base() == LEAP
    assert container.container.url == LEAP.url
    assert container.container._build_tag == LEAP.url


@pytest.mark.parametrize("container", [LEAP_WITH_TAG], indirect=True)
def test_container_without_containerfile_but_with_tags_is_rebuild(
    container: ContainerData,
):
    assert (
        isinstance(container.container, DerivedContainer)
        and not container.container.containerfile
        and container.container.add_build_tags
    )
    assert container.container.get_base() == LEAP
    assert container.container.container_id != LEAP.url


@pytest.mark.parametrize(
    "container", [LEAP_WITH_MAN_AND_LUA], indirect=["container"]
)
def test_leap_with_man_and_lua(container: ContainerData):
    assert container.connection.exists("man")
    assert container.connection.exists("lua")


@pytest.mark.parametrize(
    "cont,base", list(zip(CONTAINER_IMAGES, [LEAP, LEAP, LEAP_WITH_MAN]))
)
def test_container_objects(
    cont: Union[Container, DerivedContainer],
    base: Union[Container, DerivedContainer],
) -> None:
    assert cont.get_base() == base


def test_auto_container_fixture(auto_container: ContainerData):
    assert auto_container.connection.file("/etc/os-release").exists


@pytest.mark.parametrize(
    "container", [BUSYBOX_WITH_ENTRYPOINT], indirect=["container"]
)
def test_custom_entry_point(container: ContainerData):
    container.connection.check_output("true")


@pytest.mark.parametrize(
    "container", [SLEEP_CONTAINER], indirect=["container"]
)
def test_default_entry_point(container: ContainerData):
    sleep = container.connection.process.filter(comm="sleep")
    assert len(sleep) == 1
    assert "/usr/bin/sleep 3600" == sleep[0].args


@pytest.mark.parametrize("container", [CONTAINER_THAT_STOPS], indirect=True)
def test_container_that_stops(container: ContainerData) -> None:
    # it should just be alive
    container.connection.check_output("true")


def test_container_size(
    container_runtime: OciRuntimeBase, pytestconfig: Config
):
    for container in [BUSYBOX_WITH_ENTRYPOINT, BUSYBOX_WITH_GARBAGE]:
        container.prepare_container(container_runtime, pytestconfig.rootpath)

    assert container_runtime.get_image_size(
        BUSYBOX_WITH_ENTRYPOINT
    ) < container_runtime.get_image_size(BUSYBOX_WITH_GARBAGE)
    assert (
        container_runtime.get_image_size(BUSYBOX_WITH_ENTRYPOINT)
        - container_runtime.get_image_size(BUSYBOX_WITH_GARBAGE)
        < 4096 * 1024 * 1024
    )


@pytest.mark.parametrize(
    "container",
    (LEAP_WITH_BIN, LEAP_WITH_BIN_AND_CMD),
    indirect=True,
)
def test_derived_containers_use_correct_user(
    container: ContainerData,
) -> None:
    assert container.connection.check_output("id -nu").strip() == "bin"
    assert container.inspect.config.user == "bin"


@pytest.mark.parametrize(
    "container",
    [
        DerivedContainer(base=ctr, extra_launch_args=["--user", "root"])
        for ctr in (LEAP_WITH_BIN, LEAP_WITH_BIN_AND_CMD)
    ],
    indirect=True,
)
def test_derived_container_respects_launch_args(
    container: ContainerData,
) -> None:
    assert int(container.connection.check_output("id -u").strip()) == 0


def test_multistage_containerfile() -> None:
    assert "FROM docker.io/alpine" in MULTI_STAGE_BUILD.containerfile


def test_multistage_build(
    tmp_path: Path, pytestconfig: Config, container_runtime: OciRuntimeBase
):
    MULTI_STAGE_BUILD.build(
        tmp_path,
        pytestconfig.rootpath,
        container_runtime,
        extra_build_args=get_extra_build_args(pytestconfig),
    )


def test_multistage_build_target(
    tmp_path: Path, pytestconfig: Config, container_runtime: OciRuntimeBase
):
    first_target = MULTI_STAGE_BUILD.build(
        tmp_path,
        pytestconfig.rootpath,
        container_runtime,
        "runner1",
        extra_build_args=get_extra_build_args(pytestconfig),
    )
    assert (
        LOCALHOST.check_output(
            f"{container_runtime.runner_binary} run --rm {first_target}",
        ).strip()
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
        LOCALHOST.check_output(
            f"{container_runtime.runner_binary} run --rm {second_target} /bin/test.sh",
        ).strip()
        == "foobar"
    )

    for distro, target in (
        ("Leap", first_target),
        ("Alpine", second_target),
    ):
        assert (
            distro
            in LOCALHOST.check_output(
                f"{container_runtime.runner_binary} run --rm --entrypoint= {target} "
                "cat /etc/os-release",
            ).strip()
        )


LEAP_THAT_ECHOES_STUFF = DerivedContainer(
    base=LEAP, containerfile="""CMD ["echo", "foobar"]"""
)


@pytest.mark.parametrize("container", [LEAP_THAT_ECHOES_STUFF], indirect=True)
def test_container_logs(container: ContainerData) -> None:
    assert "foobar" in container.read_container_logs()


def test_container_stops_on_exit(
    container_runtime: OciRuntimeBase,
    pytestconfig: Config,
    tmp_path: Path,
):
    _CONTAINER_THAT_TRAPS_SIGTERM = DerivedContainer(
        base=BUSYBOX_WITH_ENTRYPOINT,
        containerfile="""COPY tests/files/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
CMD ["/usr/local/bin/entrypoint.sh"]
""",
        volume_mounts=[
            BindMount(host_path=tmp_path, container_path="/var/volume")
        ],
    )
    with ContainerLauncher(
        _CONTAINER_THAT_TRAPS_SIGTERM,
        container_runtime,
        pytestconfig.rootpath,
    ) as launcher:
        launcher.launch_container()
        connection = launcher.container_data.connection
        assert connection.file("/var/volume/cleanup_confirmed").exists

    assert (tmp_path / "cleanup_confirmed").read_text().strip() == "1"
