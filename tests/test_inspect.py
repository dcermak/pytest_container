# pylint: disable=missing-function-docstring,missing-module-docstring
import pytest
from pytest_container import DerivedContainer
from pytest_container.container import ContainerData
from pytest_container.inspect import VolumeMount
from pytest_container.runtime import OciRuntimeBase

from .test_container_build import LEAP

_CTR_NAME = "foobar-12345"

IMAGE_WITH_EVERYTHING = DerivedContainer(
    singleton=True,
    extra_launch_args=["--name", _CTR_NAME],
    base=LEAP,
    containerfile="""VOLUME /src/
EXPOSE 8080 666
RUN useradd opensuse
USER opensuse
ENTRYPOINT /bin/bash
ENV HOME=/src/
ENV MY_VAR=
ENV SUFFIX_NAME=dc=example,dc=com
CMD ["/bin/sh"]
""",
)


@pytest.mark.parametrize(
    "container_per_test", [IMAGE_WITH_EVERYTHING], indirect=True
)
def test_inspect(
    container_per_test: ContainerData, container_runtime: OciRuntimeBase, host
) -> None:
    inspect = container_per_test.inspect

    assert inspect.id == container_per_test.container_id
    assert inspect.name == _CTR_NAME
    assert inspect.config.user == "opensuse"
    assert inspect.config.entrypoint == ["/bin/sh", "-c", "/bin/bash"]

    assert (
        "HOME" in inspect.config.env and inspect.config.env["HOME"] == "/src/"
    )

    # podman and docker cannot agree on what the Config.Image value is: podman
    # prefixes it with `localhost` and the full build tag
    # (i.e. `pytest_container:$digest`), while docker just uses the digest
    expected_img = (
        str(container_per_test.container)
        if container_runtime.runner_binary == "docker"
        else f"localhost/pytest_container:{container_per_test.container}"
    )

    assert inspect.config.image == expected_img
    assert inspect.config.cmd == ["/bin/sh"]

    assert (
        not inspect.state.paused
        and not inspect.state.dead
        and not inspect.state.oom_killed
        and not inspect.state.restarting
    )

    assert (
        len(inspect.mounts) == 1
        and isinstance(inspect.mounts[0], VolumeMount)
        and inspect.mounts[0].destination == "/src"
    )

    assert inspect.network.ip_address or "" == host.check_output(
        f"{container_runtime.runner_binary} inspect --format "
        f'"{{{{ .NetworkSettings.IPAddress }}}}" {_CTR_NAME}'
    )
