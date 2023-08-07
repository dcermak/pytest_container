# pylint: disable=missing-function-docstring,missing-module-docstring
import pytest

from .test_container_build import LEAP
from pytest_container import DerivedContainer
from pytest_container.container import ContainerData
from pytest_container.inspect import VolumeMount
from pytest_container.runtime import OciRuntimeBase


IMAGE_WITH_EVERYTHING = DerivedContainer(
    base=LEAP,
    containerfile="""VOLUME /src/
EXPOSE 8080 666
RUN useradd opensuse
USER opensuse
ENTRYPOINT /bin/false
ENV HOME=/src/
ENV MY_VAR=
ENV SUFFIX_NAME=dc=example,dc=com
CMD ["/bin/sh"]
""",
)


@pytest.mark.parametrize("container", [IMAGE_WITH_EVERYTHING], indirect=True)
def test_inspect(container: ContainerData, container_runtime: OciRuntimeBase):
    inspect = container.inspect

    assert inspect.id == container.container_id
    assert inspect.config.user == "opensuse"
    assert inspect.config.entrypoint == ["/bin/sh", "-c", "/bin/false"]

    assert (
        "HOME" in inspect.config.env and inspect.config.env["HOME"] == "/src/"
    )

    # podman and docker cannot agree on what the Config.Image value is: podman
    # prefixes it with `localhost` and the full build tag
    # (i.e. `pytest_container:$digest`), while docker just uses the digest
    expected_img = (
        str(container.container)
        if container_runtime.runner_binary == "docker"
        else f"localhost/pytest_container:{container.container}"
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
