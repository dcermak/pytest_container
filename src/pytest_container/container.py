import os
import tempfile
from dataclasses import dataclass
from dataclasses import field
from string import Template
from subprocess import check_output
from typing import Any
from typing import Dict
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Union

from pytest_container.helpers import get_selected_runtime


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


@dataclass
class Container(ContainerBase):
    """This class stores information about the BCI images under test.

    Instances of this class are constructed from the contents of
    data/containers.json
    """

    def pull_container(self) -> None:
        """Pulls the container with the given url using the currently selected
        container runtime"""
        runtime = get_selected_runtime()
        check_output([runtime.runner_binary, "pull", self.url])

    def prepare_container(self) -> None:
        """Prepares the container so that it can be launched."""
        self.pull_container()

    def get_base(self) -> "Container":
        return self


@dataclass
class DerivedContainer(ContainerBase):
    base: Union[Container, "DerivedContainer"] = None
    containerfile: str = ""

    def __str__(self) -> str:
        return (
            self.container_id
            or f"container derived from {self.base.__str__()}"
        )

    def get_base(self) -> "Container":
        return self.base.get_base()

    def prepare_container(
        self, extra_build_args: Optional[List[str]] = None
    ) -> None:
        self.base.prepare_container()

        runtime = get_selected_runtime()
        with tempfile.TemporaryDirectory() as tmpdirname:
            containerfile_path = os.path.join(tmpdirname, "Dockerfile")
            with open(containerfile_path, "w") as containerfile:
                from_id = (
                    getattr(self.base, "url", self.base.container_id)
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
                    + [tmpdirname]
                )
                .decode()
                .strip()
            )


@dataclass
class MultiStageBuild:
    containers: Dict[str, Union[Container, DerivedContainer, str]]
    dockerfile_template: str

    @property
    def containerfile(self) -> str:
        return Template(self.dockerfile_template).substitute(
            **{k: str(v) for k, v in self.containers.items()}
        )

    def prepare_build(self, tmp_dir):
        for _, container in self.containers.items():
            if not isinstance(container, str):
                container.prepare_container()

        with open(tmp_dir / "Dockerfile", "w") as containerfile:
            containerfile.write(self.containerfile)


class ContainerData(NamedTuple):
    #: url to the container image on the registry or the id of the local image
    #: if the container has been build locally
    image_url_or_id: str
    #: ID of the started container
    container_id: str
    #: the testinfra connection to the running container
    connection: Any
