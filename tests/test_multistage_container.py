# pylint: disable=missing-function-docstring,missing-module-docstring
from pathlib import Path

import pytest
from pytest_container import get_extra_build_args
from pytest_container import MultiStageBuild
from pytest_container import MultiStageContainer
from pytest_container import OciRuntimeBase
from pytest_container.container import ContainerData
from pytest_container.container import EntrypointSelection
from pytest_container.runtime import LOCALHOST

from tests.images import LEAP
from tests.images import LEAP_URL
from tests.images import LEAP_WITH_MAN


_MULTISTAGE_CTR_FILE = r"""FROM $builder as builder
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
"""

_MULTISTAGE_CTRS = {
    "builder": LEAP_WITH_MAN,
    "runner1": LEAP,
    "runner2": "docker.io/alpine",
}

MULTI_STAGE_BUILD = MultiStageBuild(
    containers=_MULTISTAGE_CTRS,
    containerfile_template=_MULTISTAGE_CTR_FILE,
)

MULTI_STAGE_CTR = MultiStageContainer(
    containers=_MULTISTAGE_CTRS,
    containerfile=_MULTISTAGE_CTR_FILE,
)

MULTI_STAGE_CTR_STAGE_1 = MultiStageContainer(
    containers=_MULTISTAGE_CTRS,
    containerfile=_MULTISTAGE_CTR_FILE,
    target_stage="runner1",
    entry_point=EntrypointSelection.BASH,
)

MULTI_STAGE_CTR_STAGE_2 = MultiStageContainer(
    containers=_MULTISTAGE_CTRS,
    containerfile=_MULTISTAGE_CTR_FILE,
    target_stage="runner2",
)


def test_multistage_containerfile() -> None:
    assert "FROM docker.io/alpine" in MULTI_STAGE_BUILD.containerfile


def test_multistage_build(
    tmp_path: Path,
    pytestconfig: pytest.Config,
    container_runtime: OciRuntimeBase,
):
    MULTI_STAGE_BUILD.build(
        tmp_path,
        pytestconfig.rootpath,
        container_runtime,
        extra_build_args=get_extra_build_args(pytestconfig),
    )


def test_multistage_build_target(
    tmp_path: Path,
    pytestconfig: pytest.Config,
    container_runtime: OciRuntimeBase,
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

    for (distro, target) in (
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


@pytest.mark.parametrize("container", [MULTI_STAGE_CTR], indirect=True)
def test_multistage_container_without_stage(container: ContainerData) -> None:
    assert container.connection.file("/bin/test.sh").exists
    assert (
        "Alpine" in container.connection.file("/etc/os-release").content_string
    )


@pytest.mark.parametrize("container", [MULTI_STAGE_CTR_STAGE_2], indirect=True)
def test_multistage_container_with_runner2_stage(
    container: ContainerData,
) -> None:
    assert container.connection.file("/bin/test.sh").exists
    assert (
        "Alpine" in container.connection.file("/etc/os-release").content_string
    )


@pytest.mark.parametrize("container", [MULTI_STAGE_CTR_STAGE_1], indirect=True)
def test_multistage_container_with_runner1_stage(
    container: ContainerData,
) -> None:
    assert container.connection.file("/bin/test.sh").exists
    assert (
        "Leap" in container.connection.file("/etc/os-release").content_string
    )


@pytest.mark.parametrize(
    "container",
    [
        MultiStageContainer(
            containerfile="""FROM $nothing as nothing
FROM $builder as builder
RUN zypper -n in busybox
""",
            containers={"nothing": "scratch", "builder": LEAP_URL},
        )
    ],
    indirect=True,
)
def test_multistage_does_not_pull_scratch(container: ContainerData) -> None:
    container.connection.check_output("true")
