# pylint: disable=missing-function-docstring,missing-module-docstring
import pytest

from .test_container_build import LEAP
from pytest_container import DerivedContainer
from pytest_container.container import ContainerData
from pytest_container.inspect import VolumeMount

IMAGE_WITH_EVERYTHING = DerivedContainer(
    base=LEAP,
    containerfile="""VOLUME /src/
EXPOSE 8080 666
RUN useradd opensuse
USER opensuse
ENTRYPOINT /bin/false
ENV HOME=/src/
ENV MY_VAR=
CMD ["/bin/sh"]
""",
    default_entry_point=True,
)


@pytest.mark.parametrize("container", [IMAGE_WITH_EVERYTHING], indirect=True)
def test_inspect(container: ContainerData):
    inspect = container.inspect

    assert inspect.id == container.container_id
    assert inspect.config.user == "opensuse"
    assert inspect.config.entrypoint == ["/bin/sh", "-c", "/bin/false"]

    assert (
        "HOME" in inspect.config.env and inspect.config.env["HOME"] == "/src/"
    )
    assert inspect.config.image == str(container.container)
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
