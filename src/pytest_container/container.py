import enum
import itertools
import os
import tempfile
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from hashlib import md5
from pytest_container.logging import _logger
from pytest_container.runtime import get_selected_runtime
from subprocess import check_output
from typing import Any
from typing import Collection
from typing import Dict
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Union

import pytest
from _pytest.mark.structures import MarkDecorator
from _pytest.mark.structures import ParameterSet
from py.path import local


@enum.unique
class ImageFormat(enum.Enum):
    """Image formats supported by buildah."""

    #: The default OCIv1 image format.
    OCIv1 = "oci"

    #: Docker's default image format that supports additional properties, like
    #: ``HEALTHCHECK``
    DOCKER = "docker"

    def __str__(self) -> str:
        return "oci" if self == ImageFormat.OCIv1 else "docker"


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

    #: time in ms for the container to become healthy (the timeout is ignored
    #: when the container image defined no ``HEALTHCHECK`` or when the timeout is
    #: ``None``)
    healthcheck_timeout_ms: Optional[int] = 10 * 1000

    #: additional environment variables that should be injected into the
    #: container
    extra_environment_variables: Optional[Dict[str, str]] = None

    #: Indicate whether there must never be more than one running container of
    #: this type at all times (e.g. because it opens a shared port).
    singleton: bool = False

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
        cmd = (
            ["run", "-d"]
            + (extra_run_args or [])
            + self.extra_launch_args
            + (
                list(
                    itertools.chain(
                        *[
                            ("-e", f"{k}={v}")
                            for k, v in self.extra_environment_variables.items()
                        ]
                    )
                )
                if self.extra_environment_variables
                else []
            )
        )

        if self.entry_point is None:
            cmd.append(self.container_id or self.url)
        else:
            cmd += ["-it", self.container_id or self.url, self.entry_point]

        return cmd

    @property
    def filelock_filename(self) -> Optional[str]:
        all_elements = []
        for _, v in self.__dict__.items():
            if isinstance(v, list):
                all_elements.append("".join(v))
            elif isinstance(v, dict):
                all_elements.append("".join(v.values()))
            else:
                all_elements.append(str(v))
        return (
            f"{md5((''.join(all_elements)).encode()).hexdigest()}.lock"
            if self.singleton
            else None
        )


class ContainerBaseABC(ABC):
    @abstractmethod
    def prepare_container(
        self, rootdir: local, extra_build_args: Optional[List[str]]
    ) -> None:
        """Prepares the container so that it can be launched."""
        pass

    @abstractmethod
    def get_base(self) -> "Container":
        pass


@dataclass(unsafe_hash=True)
class Container(ContainerBase, ContainerBaseABC):
    """This class stores information about the BCI images under test.

    Instances of this class are constructed from the contents of
    data/containers.json
    """

    def pull_container(self) -> None:
        """Pulls the container with the given url using the currently selected
        container runtime"""
        runtime = get_selected_runtime()
        _logger.debug("Pulling %s via %s", self.url, runtime.runner_binary)
        check_output([runtime.runner_binary, "pull", self.url])

    def prepare_container(
        self, rootdir: local, extra_build_args: Optional[List[str]] = None
    ) -> None:
        """Prepares the container so that it can be launched."""
        self.pull_container()

    def get_base(self) -> "Container":
        return self


@dataclass(unsafe_hash=True)
class DerivedContainer(ContainerBase, ContainerBaseABC):
    base: Union[Container, "DerivedContainer", str] = ""

    #: The :file:`Containerfile` that is used to build this container derived
    #: from :py:attr:`base`.
    containerfile: str = ""

    #: An optional image format when building images with :command:`buildah`.
    #: This attribute can be used to instruct :command:`buildah` to build images
    #: in the ``docker`` format, instead of the default (``oci``).
    #: This attribute is ignored by :command:`docker`.
    image_format: Optional[ImageFormat] = None

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
        _logger.debug("Preparing derived container based on %s", self.base)
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
                containerfile_contents = f"""FROM {from_id}
{self.containerfile}
"""
                _logger.debug(
                    "Writing containerfile to %s: %s",
                    containerfile_path,
                    containerfile_contents,
                )
                containerfile.write(containerfile_contents)

            image_format_args: List[str] = []
            if (
                self.image_format is not None
                and "buildah" in runtime.build_command
            ):
                image_format_args = ["--format", str(self.image_format)]

            cmd = (
                runtime.build_command
                + image_format_args
                + (extra_build_args or [])
                + ["-f", containerfile_path, str(rootdir)]
            )
            _logger.debug("Building image via: %s", cmd)
            self.container_id = runtime.get_image_id_from_stdout(
                check_output(cmd).decode().strip()
            )
            _logger.debug(
                "Successfully build the container image %s", self.container_id
            )


class ContainerData(NamedTuple):
    #: url to the container image on the registry or the id of the local image
    #: if the container has been build locally
    image_url_or_id: str
    #: ID of the started container
    container_id: str
    #: the testinfra connection to the running container
    connection: Any


def container_to_pytest_param(
    container: ContainerBase,
    marks: Optional[Union[Collection[MarkDecorator], MarkDecorator]] = None,
) -> ParameterSet:
    """Converts a subclass of :py:class:`~pytest_container.container.ContainerBase`
    (:py:class:`~pytest_container.container.Container` or
    :py:class:`~pytest_container.container.DerivedContainer`) into a
    `pytest.param
    <https://docs.pytest.org/en/stable/reference.html?#pytest.param>`_ with the
    given marks and sets the id of the parameter to the pretty printed version
    of the container (i.e. its
    :py:attr:`~pytest_container.container.ContainerBase.url` or
    :py:attr:`~pytest_container.container.ContainerBase.container_id`)

    """
    return pytest.param(container, marks=marks or [], id=str(container))


def container_from_pytest_param(
    param: Union[ParameterSet, Container, DerivedContainer],
) -> Union[Container, DerivedContainer]:
    """Extracts the :py:class:`~pytest_container.container.Container` or
    :py:class:`~pytest_container.container.DerivedContainer` from a
    `pytest.param
    <https://docs.pytest.org/en/stable/reference.html?#pytest.param>`_ or just
    returns the value directly, if it is either a
    :py:class:`~pytest_container.container.Container` or a
    :py:class:`~pytest_container.container.DerivedContainer`.

    """
    if isinstance(param, (Container, DerivedContainer)):
        return param

    if len(param.values) > 0 and isinstance(
        param.values[0], (Container, DerivedContainer)
    ):
        return param.values[0]

    raise ValueError(f"Invalid pytest.param values: {param.values}")
