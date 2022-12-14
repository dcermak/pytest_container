import enum
import functools
import itertools
import operator
import os
import socket
import sys
import tempfile
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from hashlib import md5
from pathlib import Path
from pytest_container.logging import _logger
from pytest_container.runtime import get_selected_runtime
from subprocess import check_output
from typing import Any
from typing import Collection
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import pytest
from _pytest.mark.structures import MarkDecorator
from _pytest.mark.structures import ParameterSet


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


@enum.unique
class NetworkProtocol(enum.Enum):
    """Network protocols supporting port forwarding."""

    #: Transmission Control Protocol
    TCP = "tcp"
    #: User Datagram Protocol
    UDP = "udp"

    def __str__(self) -> str:
        return self.value

    @property
    def SOCK_CONST(self) -> int:
        """Returns the appropriate socket type constant (``SOCK_STREAM`` or
        ``SOCK_DGRAM``) for the current protocol.

        """
        return {
            NetworkProtocol.TCP.value: socket.SOCK_STREAM,
            NetworkProtocol.UDP.value: socket.SOCK_DGRAM,
        }[self.value]


@dataclass(frozen=True)
class PortForwarding:
    """Representation of a port forward from a container to the host.

    To expose a port of a container automatically, create an instance of this
    class, set the attribute :py:attr:`container_port` and optionally
    :py:attr:`protocol` as well and pass it via the parameter
    :py:attr:`ContainerBase.forwarded_ports` to either the :py:class:`Container`
    or :py:class:`DerivedContainer`:

    >>> Container(url="my-webserver", forwarded_ports=[PortForwarding(container_port=8000)])

    """

    #: The port which shall be exposed by the container.
    container_port: int

    #: The protocol which the exposed port is using. Defaults to TCP.
    protocol: NetworkProtocol = NetworkProtocol.TCP

    #: The port as which the port from :py:attr:`container_port` is exposed on
    #: the host. This value is automatically set by the `*container_*` fixtures,
    #: so there's no need for the user to modify it
    host_port: int = -1

    @property
    def forward_cli_args(self) -> List[str]:
        """Returns a list of command line arguments for the container launch
        command to automatically expose this port forwarding.

        """
        return [
            "-p",
            f"{self.host_port}:{self.container_port}/{self.protocol}",
        ]

    def __str__(self) -> str:
        return str(self.forward_cli_args)


def create_host_port_port_forward(
    port_forwards: List[PortForwarding],
) -> List[PortForwarding]:
    """Given a list of port_forwards, this function finds random free ports on
    the host system to which the container ports can be bound and returns a new
    list of appropriately configured :py:class:`PortForwarding` instances.

    """
    finished_forwards: List[PortForwarding] = []

    # list of sockets that will be created and cleaned up afterwards
    # We have to defer the cleanup, as otherwise the OS might give us a
    # previously freed socket again. But it will not do that, if we are still
    # listening on it.
    sockets: List[socket.socket] = []

    for port in port_forwards:
        sock = socket.socket(type=port.protocol.SOCK_CONST)
        sock.bind(("", 0))

        finished_forwards.append(
            PortForwarding(
                container_port=port.container_port,
                protocol=port.protocol,
                host_port=sock.getsockname()[1],
            )
        )
        sockets.append(sock)

    for sock in sockets:
        sock.close()

    assert len(port_forwards) == len(finished_forwards)
    return finished_forwards


@enum.unique
class VolumeFlag(enum.Enum):
    """Supported flags for mounting container volumes."""

    #: The volume is mounted read-only
    READ_ONLY = "ro"
    #: The volume is mounted read-write (default)
    READ_WRITE = "rw"

    #: The volume is relabeled so that it can be shared by two containers
    SELINUX_SHARED = "z"
    #: The volume is relabeled so that only a single container can access it
    SELINUX_PRIVATE = "Z"

    #: The volume is mounted as a temporary storage using overlay-fs (only
    #: supported by :command:`podman`)
    OVERLAY = "O"

    def __str__(self) -> str:
        assert isinstance(self.value, str)
        return self.value


if sys.version_info >= (3, 9):
    TEMPDIR_T = tempfile.TemporaryDirectory[str]
else:
    TEMPDIR_T = tempfile.TemporaryDirectory


@dataclass
class ContainerVolume:
    """A volume mounted into a container from the host using bind mounts.

    This class describes a bind mount of a host directory into a container. In
    the most minimal configuration, all you need to specify is the path in the
    container via :py:attr:`~ContainerVolume.container_path`. The ``container*``
    fixtures will then create a temporary directory on the host for you that
    will be used as the mount point. Alternatively, you can also specify the
    path on the host yourself via :py:attr:`host_path`.

    """

    #: Path inside the container where this volume will be mounted
    container_path: str

    #: Path on the host that will be mounted. When omitted, a temporary
    #: directory will be created and the path will be saved in this attribute.
    host_path: Optional[str] = None

    #: Flags for mounting this volume.
    #:
    #: Note that some flags are mutually exclusive and potentially not supported
    #: by all container runtimes.
    #: The :py:attr:`VolumeFlag.SELINUX_PRIVATE` flag will be added by default
    #: to the flags unless :py:attr:`ContainerVolume.shared` is ``True``.
    flags: List[VolumeFlag] = field(default_factory=list)

    #: Define whether this volume should can be shared between
    #: containers. Defaults to ``False``.
    #:
    #: This affects only the addition of SELinux flags to
    #: :py:attr:`~ContainerVolume.flags`.
    shared: bool = False

    _tmpdir: Optional[TEMPDIR_T] = None

    # This is a stupid hack that we require for this plugin to work with
    # pytest-rerunfailures:
    # rerunfailures will reset this class only partially, it sets `_tmpdir` to
    # `None` but it does **not** reset `host_path`...
    # That makes it more or less impossible to correctly implement setup()
    # without an auxiliary variable that stores whether a tmpdir should be
    # created. Well and that's the story behind this one...
    _create_tmp: bool = True

    def __post_init__(self) -> None:
        self._create_tmp = not self.host_path

        if (
            VolumeFlag.SELINUX_PRIVATE not in self.flags
            and VolumeFlag.SELINUX_SHARED not in self.flags
        ):
            self.flags.append(
                VolumeFlag.SELINUX_SHARED
                if self.shared
                else VolumeFlag.SELINUX_PRIVATE
            )

        for mutually_exclusive_flags in (
            (VolumeFlag.READ_ONLY, VolumeFlag.READ_WRITE),
            (VolumeFlag.SELINUX_SHARED, VolumeFlag.SELINUX_PRIVATE),
        ):
            if (
                mutually_exclusive_flags[0] in self.flags
                and mutually_exclusive_flags[1] in self.flags
            ):
                raise ValueError(
                    f"Invalid container volume flags: {', '.join(str(f) for f in self.flags)}; "
                    f"flags {mutually_exclusive_flags[0]} and {mutually_exclusive_flags[1]} "
                    "are mutually exclusive"
                )

    def setup(self) -> None:
        """Creates the temporary host path if necessary. This function is called
        automatically by the ``*container*`` fixtures.

        """
        if self._create_tmp:
            self._tmpdir = tempfile.TemporaryDirectory()
            self.host_path = self._tmpdir.name

            _logger.debug(
                "created temporary directory %s for the container volume %s",
                self._tmpdir.name,
                self.container_path,
            )

        assert self.host_path
        if not os.path.exists(self.host_path):
            raise RuntimeError(
                f"Volume with the host path '{self.host_path}' "
                "was requested but the directory does not exist"
            )

    def cleanup(self) -> None:
        """Cleans up the temporary host directory if necessary. This function is
        called automatically by the ``*container*`` fixtures.

        """
        if self._tmpdir:
            _logger.debug(
                "cleaning up directory %s for the container volume %s",
                self.host_path,
                self.container_path,
            )
            assert self.host_path
            self._tmpdir.cleanup()

    @property
    def cli_arg(self) -> str:
        """Command line argument to mount this volume."""
        assert self.host_path
        res = f"-v={self.host_path}:{self.container_path}"
        if self.flags:
            res += ":" + ",".join(str(f) for f in self.flags)
        return res


@dataclass
class ContainerBase:
    #: Full url to this container via which it can be pulled
    #:
    #: If your container image is not available via a registry and only locally,
    #: then you can use the following syntax: ``containers-storage:$local_name``
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

    #: Time for the container to become healthy (the timeout is ignored
    #: when the container image defines no ``HEALTHCHECK`` or when the timeout
    #: is below zero).
    #: When the value is ``None``, then the timeout will be inferred from the
    #: container image's ``HEALTHCHECK`` directive.
    healthcheck_timeout: Optional[timedelta] = None

    #: additional environment variables that should be injected into the
    #: container
    extra_environment_variables: Optional[Dict[str, str]] = None

    #: Indicate whether there must never be more than one running container of
    #: this type at all times (e.g. because it opens a shared port).
    singleton: bool = False

    #: forwarded ports of this container
    forwarded_ports: List[PortForwarding] = field(default_factory=list)

    #: optional list of volumes that should be mounted in this container
    volume_mounts: List[ContainerVolume] = field(default_factory=list)

    _is_local: bool = False

    def __post_init__(self) -> None:
        if self.default_entry_point and self.custom_entry_point:
            raise ValueError(
                "A custom entry point has been provided "
                + self.custom_entry_point
                + "with default_entry_point being set to True"
            )

        if self.url.split(":", maxsplit=1)[0] == "containers-storage":
            self._is_local = True
            self.url = self.url.replace("containers-storage:", "")

    def __str__(self) -> str:
        return self.url or self.container_id

    @property
    def local_image(self) -> bool:
        """Returns true if this image has been build locally and has not been
        pulled from a registry.

        """
        return self._is_local

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
            + [vol.cli_arg for vol in self.volume_mounts]
        )

        if self.entry_point is None:
            cmd.append(self.container_id or self.url)
        else:
            cmd += ["-it", self.container_id or self.url, self.entry_point]

        return cmd

    @property
    def filelock_filename(self) -> str:
        all_elements = []
        for attr_name, value in self.__dict__.items():
            # don't include the container_id in the hash calculation as the id
            # might not yet be known but could be populated later on i.e. that
            # would cause a different hash for the same container
            if attr_name == "container_id":
                continue
            if isinstance(value, list):
                all_elements.append("".join([str(elem) for elem in value]))
            elif isinstance(value, dict):
                all_elements.append("".join(value.values()))
            else:
                all_elements.append(str(value))
        return f"{md5((''.join(all_elements)).encode()).hexdigest()}.lock"


class ContainerBaseABC(ABC):
    @abstractmethod
    def prepare_container(
        self, rootdir: Path, extra_build_args: Optional[List[str]]
    ) -> None:
        """Prepares the container so that it can be launched."""

    @abstractmethod
    def get_base(self) -> "Container":
        """Returns the Base of this Container Image. If the container has no
        base, then ``self`` is returned.

        """


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
        self, rootdir: Path, extra_build_args: Optional[List[str]] = None
    ) -> None:
        """Prepares the container so that it can be launched."""
        if not self._is_local:
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

    #: Additional build tags/names that should be added to the container once it
    #: has been built
    add_build_tags: List[str] = field(default_factory=list)

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
        self, rootdir: Path, extra_build_args: Optional[List[str]] = None
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
                + (
                    functools.reduce(
                        operator.add,
                        (["-t", tag] for tag in self.add_build_tags),
                    )
                    if self.add_build_tags
                    else []
                )
                + ["-f", containerfile_path, str(rootdir)]
            )
            _logger.debug("Building image via: %s", cmd)
            self.container_id = runtime.get_image_id_from_stdout(
                check_output(cmd).decode().strip()
            )
            _logger.debug(
                "Successfully build the container image %s", self.container_id
            )


@dataclass(frozen=True)
class ContainerData:
    #: url to the container image on the registry or the id of the local image
    #: if the container has been build locally
    image_url_or_id: str
    #: ID of the started container
    container_id: str
    #: the testinfra connection to the running container
    connection: Any
    #: the container data class that has been used in this test
    container: ContainerBase
    #: any ports that are exposed by this container
    forwarded_ports: List[PortForwarding]


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
