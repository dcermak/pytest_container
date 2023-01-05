"""The container module contains all classes for abstracting the details of
launching containers away. These classes are used to parametrize test cases
using the fixtures provided by this plugin.

"""
import contextlib
import enum
import functools
import itertools
import operator
import os
import socket
import sys
import tempfile
import time
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from hashlib import md5
from pathlib import Path
from subprocess import check_output
from types import TracebackType
from typing import Any
from typing import Collection
from typing import Dict
from typing import List
from typing import Optional
from typing import overload
from typing import Type
from typing import Union

import pytest
import testinfra
from _pytest.mark.structures import MarkDecorator
from _pytest.mark.structures import ParameterSet
from filelock import FileLock

from pytest_container.logging import _logger
from pytest_container.runtime import ContainerHealth
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase


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

    #: chown the content of the volume for rootless runs
    CHOWN_USER = "U"

    #: ensure the volume is mounted as noexec (data only)
    NOEXEC = "noexec"

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
class ContainerVolumeBase:
    """Base class for container volumes."""

    #: Path inside the container where this volume will be mounted
    container_path: str

    #: Flags for mounting this volume.
    #:
    #: Note that some flags are mutually exclusive and potentially not supported
    #: by all container runtimes.
    #: The :py:attr:`VolumeFlag.SELINUX_PRIVATE` flag will be added by default
    #: to the flags unless :py:attr:`ContainerVolumeBase.shared` is ``True``.
    flags: List[VolumeFlag] = field(default_factory=list)

    #: Define whether this volume should can be shared between
    #: containers. Defaults to ``False``.
    #:
    #: This affects only the addition of SELinux flags to
    #: :py:attr:`~ContainerVolumeBase.flags`.
    shared: bool = False

    #: internal volume name via which it can be mounted, e.g. the volume's ID or
    #: the path on the host
    _vol_name: str = ""

    def __post_init__(self) -> None:
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

    @property
    def cli_arg(self) -> str:
        """Command line argument to mount this volume."""
        assert self._vol_name
        res = f"-v={self._vol_name}:{self.container_path}"
        if self.flags:
            res += ":" + ",".join(str(f) for f in self.flags)
        return res


@dataclass
class ContainerVolume(ContainerVolumeBase):
    """A container volume created by the container runtime for persisting files
    outside of (ephemeral) containers.

    """

    @property
    def volume_id(self) -> str:
        """Unique ID of the volume. It is automatically set when the volume is
        created by :py:class:`VolumeCreator`.

        """
        return self._vol_name


@dataclass
class BindMount(ContainerVolumeBase):
    """A volume mounted into a container from the host using bind mounts.

    This class describes a bind mount of a host directory into a container. In
    the most minimal configuration, all you need to specify is the path in the
    container via :py:attr:`~ContainerVolumeBase.container_path`. The
    ``container*`` fixtures will then create a temporary directory on the host
    for you that will be used as the mount point. Alternatively, you can also
    specify the path on the host yourself via :py:attr:`host_path`.

    """

    #: Path on the host that will be mounted if absolute. if relative,
    #: it refers to a volume to be auto-created. When omitted, a temporary
    #: directory will be created and the path will be saved in this attribute.
    host_path: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.host_path:
            self._vol_name = self.host_path


@dataclass
class VolumeCreator:
    """Context Manager to create and remove a :py:class:`ContainerVolume`.

    This context manager creates a volume using the supplied
    :py:attr:`container_runtime` When the ``with`` block is entered and removes
    it once it is exited.
    """

    #: The volume to be created
    volume: ContainerVolume

    #: The container runtime, via which the volume is created & destroyed
    container_runtime: OciRuntimeBase

    def __enter__(self) -> "VolumeCreator":
        """Creates the container volume"""
        vol_id = (
            check_output(
                [self.container_runtime.runner_binary, "volume", "create"]
            )
            .decode()
            .strip()
        )
        self.volume._vol_name = vol_id
        return self

    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> None:
        """Cleans up the container volume."""
        assert self.volume.volume_id

        # Clean up container volume
        check_output(
            [
                self.container_runtime.runner_binary,
                "volume",
                "rm",
                "-f",
                self.volume.volume_id,
            ],
        )
        self.volume._vol_name = ""


@dataclass
class BindMountCreator:
    """Context Manager that creates temporary directories for bind mounts (if
    necessary, i.e. when :py:attr:`BindMount.host_path` is ``None``).

    """

    #: The bind mount which host path should be created
    volume: BindMount

    #: internal temporary directory
    _tmpdir: Optional[TEMPDIR_T] = None

    def __post__init__(self) -> None:
        # the tempdir must not be set accidentally by the user
        assert self._tmpdir is None, "_tmpdir must only be set in __enter__()"

    def __enter__(self) -> "BindMountCreator":
        """Creates the temporary host path if necessary."""
        if not self.volume.host_path:
            # we don't want to use a with statement, as the temporary directory
            # must survive this function
            # pylint: disable=consider-using-with
            self._tmpdir = tempfile.TemporaryDirectory()
            self.volume.host_path = self._tmpdir.name

            _logger.debug(
                "created temporary directory %s for the container volume %s",
                self._tmpdir.name,
                self.volume.container_path,
            )

        assert self.volume.host_path
        self.volume._vol_name = self.volume.host_path
        if os.path.isabs(self.volume.host_path) and not os.path.exists(
            self.volume.host_path
        ):
            raise RuntimeError(
                f"Volume with the host path '{self.volume.host_path}' "
                "was requested but the directory does not exist"
            )
        return self

    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> None:
        """Cleans up the temporary host directory or the container volume."""
        assert self.volume.host_path

        if self._tmpdir:
            _logger.debug(
                "cleaning up directory %s for the container volume %s",
                self.volume.host_path,
                self.volume.container_path,
            )
            self._tmpdir.cleanup()
            self.volume.host_path = None
            self.volume._vol_name = ""


@overload
def get_volume_creator(
    volume: ContainerVolume, runtime: OciRuntimeBase
) -> VolumeCreator:
    ...


@overload
def get_volume_creator(
    volume: BindMount, runtime: OciRuntimeBase
) -> BindMountCreator:
    ...


def get_volume_creator(
    volume: Union[ContainerVolume, BindMount], runtime: OciRuntimeBase
) -> Union[VolumeCreator, BindMountCreator]:
    """Returns the appropriate volume creation context manager for the given
    volume.

    """
    if isinstance(volume, ContainerVolume):
        return VolumeCreator(volume, runtime)

    if isinstance(volume, BindMount):
        return BindMountCreator(volume)

    assert False, f"invalid volume type {type(volume)}"


@dataclass
class ContainerBase:
    """Base class for defining containers to be tested. Not to be used directly,
    instead use :py:class:`Container` or :py:class:`DerivedContainer`.

    """

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
    volume_mounts: List[Union[ContainerVolume, BindMount]] = field(
        default_factory=list
    )

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
        preferred, otherwise bash is used unless :py:attr:`default_entry_point`
        is ``True``.

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

        Args:
            extra_run_args: optional list of arguments that are added to the
                launch command directly after the ``run -d``.

        Returns:
            The command to launch the container image described by this class
            instance as a list of strings that can be fed directly to
            :py:class:`subprocess.Popen` as the ``args`` parameter.
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
        """Filename of a lockfile unique to the container image under test.

        It is a hash of the properties of this class excluding all values that
        are set after the container is launched. Thereby, this filename can be
        used to acquire a lock blocking any action using this specific container
        image across threads/processes.

        """
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
    """Abstract base class defining the methods that must be implemented by the
    classes fed to the ``*container*`` fixtures.

    """

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
    """This class stores information about the Container Image under test."""

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
    """Class for storing information about the Container Image under test, that
    is build from a :file:`Containerfile`/:file:`Dockerfile` from a different
    image (can be any image from a registry or an instance of
    :py:class:`Container` or :py:class:`DerivedContainer`).

    """

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

        # do not build containers without a containerfile and where no build
        # tags are added
        if not self.containerfile and not self.add_build_tags:
            self.container_id = str(self.get_base())
            return

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
    """Class returned by the ``*container*`` fixtures to the test function. It
    contains information about the launched container and the testinfra
    :py:attr:`connection` to the running container.

    """

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


@dataclass
class ContainerLauncher:
    """Helper context manager to setup, start and teardown a container including
    all of its resources. It is used by the ``*container*`` fixtures.

    """

    #: The container that will be launched
    container: Union[Container, DerivedContainer]

    #: The container runtime via which the container will be launched
    container_runtime: OciRuntimeBase

    #: root directory of the pytest testsuite
    rootdir: Path

    #: additional arguments to pass to the container build commands
    extra_build_args: List[str] = field(default_factory=list)

    #: additional arguments to pass to the container run commands
    extra_run_args: List[str] = field(default_factory=list)

    _new_port_forwards: List[PortForwarding] = field(default_factory=list)
    _container_id: Optional[str] = None

    _stack: contextlib.ExitStack = field(default_factory=contextlib.ExitStack)

    def __enter__(self) -> "ContainerLauncher":
        # Lock guarding the container preparation, so that only one process
        # tries to pull/build it at the same time.
        # If this container is a singleton, then we use it as a lock until
        # __exit__()
        lock = FileLock(
            Path(tempfile.gettempdir()) / self.container.filelock_filename
        )
        _logger.debug(
            "Locking container preparation via file %s", lock.lock_file
        )
        lock.acquire()

        def release_lock() -> None:
            _logger.debug("Releasing lock %s", lock.lock_file)
            lock.release()
            os.unlink(lock.lock_file)

        self.container.prepare_container(self.rootdir, self.extra_build_args)

        # ordinary containers are only locked during the build,
        # singleton containers are unlocked after everything
        if not self.container.singleton:
            release_lock()
        else:
            self._stack.callback(release_lock)

        for cont_vol in self.container.volume_mounts:
            self._stack.enter_context(
                get_volume_creator(cont_vol, self.container_runtime)
            )

        forwarded_ports = self.container.forwarded_ports

        # We must perform the launches in separate branches, as containers with
        # port forwards must be launched while the lock is being held. Otherwise
        # another container could pick the same ports before this one launches.
        if forwarded_ports:
            with FileLock(self.rootdir / "port_check.lock"):
                self._new_port_forwards = create_host_port_port_forward(
                    forwarded_ports
                )
                port_forward_args = []
                for new_forward in self._new_port_forwards:
                    port_forward_args += new_forward.forward_cli_args

                launch_cmd = [
                    self.container_runtime.runner_binary
                ] + self.container.get_launch_cmd(
                    extra_run_args=(self.extra_run_args or [])
                    + port_forward_args
                )

                _logger.debug("Launching container via: %s", launch_cmd)
                self._container_id = check_output(launch_cmd).decode().strip()
        else:
            launch_cmd = [
                self.container_runtime.runner_binary
            ] + self.container.get_launch_cmd(
                extra_run_args=self.extra_run_args
            )

            _logger.debug("Launching container via: %s", launch_cmd)
            self._container_id = check_output(launch_cmd).decode().strip()

        self._wait_for_container_to_become_healthy()

        return self

    @property
    def container_data(self) -> ContainerData:
        """The :py:class:`ContainerData` instance corresponding to the running
        container. This property is only valid after the context manager has
        been "entered" via a ``with`` statement.

        """
        assert self._container_id
        return ContainerData(
            image_url_or_id=self.container.url or self.container.container_id,
            container_id=self._container_id,
            connection=testinfra.get_host(
                f"{self.container_runtime.runner_binary}://{self._container_id}"
            ),
            container=self.container,
            forwarded_ports=self._new_port_forwards,
        )

    def _wait_for_container_to_become_healthy(self) -> None:
        assert self._container_id

        start = datetime.now()
        timeout: Optional[timedelta] = self.container.healthcheck_timeout
        _logger.debug(
            "Started container with %s at %s", self._container_id, start
        )

        if timeout is None:
            healthcheck = self.container_runtime.get_container_healthcheck(
                self.container
            )
            if healthcheck is not None:
                timeout = healthcheck.max_wait_time

        if timeout is not None and timeout > timedelta(seconds=0):
            _logger.debug(
                "Container has a healthcheck defined, will wait at most %s ms",
                timeout,
            )
            while True:
                health = self.container_runtime.get_container_health(
                    self._container_id
                )
                _logger.debug("Container has the health status %s", health)

                if health in (
                    ContainerHealth.NO_HEALTH_CHECK,
                    ContainerHealth.HEALTHY,
                ):
                    break
                delta = datetime.now() - start
                if delta > timeout:
                    raise RuntimeError(
                        f"Container {self._container_id} did not become healthy within "
                        f"{1000 * timeout.total_seconds()}ms, took {delta} and "
                        f"state is {str(health)}"
                    )
                time.sleep(max(0.5, timeout.total_seconds() / 10))

    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> None:
        if self._container_id is not None:
            _logger.debug(
                "Removing container %s via %s",
                self._container_id,
                self.container_runtime.runner_binary,
            )
            check_output(
                [
                    self.container_runtime.runner_binary,
                    "rm",
                    "-f",
                    self._container_id,
                ]
            )
        self._stack.close()
