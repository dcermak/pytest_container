import os
import tempfile
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from pytest_container.runtime import get_selected_runtime
from subprocess import check_output
from typing import Any
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Union

from py.path import local


@dataclass
class ContainerBase:
    #: full url to this container via which it can be pulled
    url: str = ""

    #: id of the container if it is not available via a registry URL
    container_id: str = ""

    #: flag whether the image should be launched using its own defined entry
    #: point. If False, then ``/bin/bash`` is used.
    default_entry_point: bool = False

    #: custom entry point for this container (i.e. neither its default, nor
    #: `/bin/bash`)
    custom_entry_point: Optional[str] = None

    #: List of additional flags that will be inserted after
    #: `docker/podman run -d`. The list must be properly escaped, e.g. as
    #: created by `shlex.split`
    extra_launch_args: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.default_entry_point and self.custom_entry_point:
            raise ValueError(
                f"A custom entry point has been provided ({self.custom_entry_point}) with default_entry_point being set to True"
            )

    def __str__(self) -> str:
        return self.url or self.container_id

    @property
    def entry_point(self) -> Optional[str]:
        """The entry point of this container, either its default, bash or a
        custom one depending on the set values. A custom entry point is
        preferred, otherwise bash is used unless `self.default_entry_point` is
        `True`.
        """
        if self.custom_entry_point:
            return self.custom_entry_point
        if self.default_entry_point:
            return None
        return "/bin/bash"

    def get_launch_cmd(
        self, extra_run_args: Optional[List[str]] = None
    ) -> List[str]:
        """Returns the command to launch this container image (excluding the
        leading podman or docker binary name).
        """
        cmd = ["run", "-d"] + (extra_run_args or []) + self.extra_launch_args

        if self.entry_point is None:
            cmd.append(self.container_id or self.url)
        else:
            cmd += ["-it", self.container_id or self.url, self.entry_point]

        return cmd


class ContainerBaseABC(ABC):
    @abstractmethod
    def prepare_container(self, rootdir: local) -> None:
        """Prepares the container so that it can be launched."""
        pass

    @abstractmethod
    def get_base(self) -> "Container":
        pass


class Container(ContainerBase, ContainerBaseABC):
    """This class stores information about the BCI images under test.

    Instances of this class are constructed from the contents of
    data/containers.json
    """

    def pull_container(self) -> None:
        """Pulls the container with the given url using the currently selected
        container runtime"""
        runtime = get_selected_runtime()
        check_output([runtime.runner_binary, "pull", self.url])

    def prepare_container(self, rootdir: local) -> None:
        """Prepares the container so that it can be launched."""
        self.pull_container()

    def get_base(self) -> "Container":
        return self


@dataclass
class DerivedContainer(ContainerBase, ContainerBaseABC):
    base: Union[Container, "DerivedContainer", str] = ""
    containerfile: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.base:
            raise ValueError("A base container must be provided")

    def __str__(self) -> str:
        return (
            self.container_id
            or f"container derived from {self.base.__str__()}"
        )

    def get_base(self) -> Container:
        if isinstance(self.base, str):
            return Container(url=self.base)
        return self.base.get_base()

    def prepare_container(
        self, rootdir: local, extra_build_args: Optional[List[str]] = None
    ) -> None:
        if not isinstance(self.base, str):
            self.base.prepare_container(rootdir)

        runtime = get_selected_runtime()

        with tempfile.TemporaryDirectory() as tmpdirname:
            containerfile_path = os.path.join(tmpdirname, "Dockerfile")
            with open(containerfile_path, "w") as containerfile:
                from_id = (
                    self.base
                    if isinstance(self.base, str)
                    else getattr(self.base, "url", self.base.container_id)
                    or self.base.container_id
                )
                assert from_id
                containerfile.write(
                    f"""FROM {from_id}
{self.containerfile}
"""
                )

            self.container_id = runtime.get_image_id_from_stdout(
                check_output(
                    runtime.build_command
                    + (extra_build_args or [])
                    + ["-f", containerfile_path, str(rootdir)],
                    cwd=rootdir,
                )
                .decode()
                .strip()
            )


class ContainerData(NamedTuple):
    #: url to the container image on the registry or the id of the local image
    #: if the container has been build locally
    image_url_or_id: str
    #: ID of the started container
    container_id: str
    #: the testinfra connection to the running container
    connection: Any
