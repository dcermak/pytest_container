"""Module containing classes & helper functions for handling container volumes
and bind mounts.

"""

from subprocess import check_output
from types import TracebackType
from typing import Iterable, List, Optional, Type, Union, overload
from os.path import exists
from os.path import isabs
from typing_extensions import TypedDict
import enum
import tempfile
import sys
from dataclasses import KW_ONLY, dataclass

from pytest_container.runtime import OciRuntimeBase
from pytest_container.logging import _logger


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


@dataclass(frozen=True)
class ContainerVolumeBase:
    """Base class for container volumes."""

    #: Path inside the container where this volume will be mounted
    container_path: str

    _: KW_ONLY

    #: Flags for mounting this volume.
    #:
    #: Note that some flags are mutually exclusive and potentially not supported
    #: by all container runtimes.
    #:
    #: The :py:attr:`VolumeFlag.SELINUX_PRIVATE` flag will be added by default
    #: if flags is ``None``, unless :py:attr:`ContainerVolumeBase.shared` is
    #: ``True``, then :py:attr:`VolumeFlag.SELINUX_SHARED` is added.
    #:
    #: If flags is a list (even an empty one), then no flags are added.
    flags: Optional[List[VolumeFlag]] = None

    #: Define whether this volume should can be shared between
    #: containers. Defaults to ``False``.
    #:
    #: This affects only the addition of SELinux flags to
    #: :py:attr:`~ContainerVolumeBase.flags`.
    shared: bool = False

    #: internal volume name via which the volume can be mounted, e.g. the
    #: volume's ID or the path on the host
    # _vol_name: str = ""

    def __post_init__(self) -> None:

        for mutually_exclusive_flags in (
            (VolumeFlag.READ_ONLY, VolumeFlag.READ_WRITE),
            (VolumeFlag.SELINUX_SHARED, VolumeFlag.SELINUX_PRIVATE),
        ):
            if (
                mutually_exclusive_flags[0] in self._flags
                and mutually_exclusive_flags[1] in self._flags
            ):
                raise ValueError(
                    f"Invalid container volume flags: {', '.join(str(f) for f in self._flags)}; "
                    f"flags {mutually_exclusive_flags[0]} and {mutually_exclusive_flags[1]} "
                    "are mutually exclusive"
                )

    @property
    def _flags(self) -> Iterable[VolumeFlag]:
        if self.flags:
            return self.flags

        if self.shared:
            return (VolumeFlag.SELINUX_SHARED,)
        else:
            return (VolumeFlag.SELINUX_PRIVATE,)


def container_volume_cli_arg(
    container_volume: ContainerVolumeBase, volume_name: str
) -> str:
    """Command line argument to mount the supplied ``container_volume`` volume."""
    res = f"-v={volume_name}:{container_volume.container_path}"
    res += ":" + ",".join(str(f) for f in container_volume._flags)
    return res


@dataclass(frozen=True)
class ContainerVolume(ContainerVolumeBase):
    """A container volume created by the container runtime for persisting files
    outside of (ephemeral) containers.

    """


@dataclass(frozen=True)
class CreatedContainerVolume(ContainerVolume):

    volume_id: str


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class CreatedBindMount(ContainerVolumeBase):
    host_path: str


class _ContainerVolumeKWARGS(TypedDict, total=False):
    flags: Optional[List[VolumeFlag]]
    container_path: str
    shared: bool


class _BindMountKWARGS(_ContainerVolumeKWARGS, total=False):
    host_path: str


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

    _created_volume: Optional[CreatedContainerVolume] = None

    def __enter__(self) -> "VolumeCreator":
        """Creates the container volume"""
        vol_id = (
            check_output(
                [self.container_runtime.runner_binary, "volume", "create"]
            )
            .decode()
            .strip()
        )
        self._created_volume = CreatedContainerVolume(
            container_path=self.volume.container_path,
            flags=self.volume.flags,
            shared=self.volume.shared,
            volume_id=vol_id,
        )

        return self

    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> None:
        """Cleans up the container volume."""
        assert self._created_volume and self._created_volume.volume_id

        _logger.debug(
            "cleaning up volume %s via %s",
            self._created_volume.volume_id,
            self.container_runtime.runner_binary,
        )

        # Clean up container volume
        check_output(
            [
                self.container_runtime.runner_binary,
                "volume",
                "rm",
                "-f",
                self._created_volume.volume_id,
            ],
        )


@dataclass
class BindMountCreator:
    """Context Manager that creates temporary directories for bind mounts (if
    necessary, i.e. when :py:attr:`BindMount.host_path` is ``None``).

    """

    #: The bind mount which host path should be created
    volume: BindMount

    #: internal temporary directory
    _tmpdir: Optional[TEMPDIR_T] = None

    _created_volume: Optional[CreatedBindMount] = None

    def __post__init__(self) -> None:
        # the tempdir must not be set accidentally by the user
        assert self._tmpdir is None, "_tmpdir must only be set in __enter__()"

    def __enter__(self) -> "BindMountCreator":
        """Creates the temporary host path if necessary."""
        kwargs: _BindMountKWARGS = {
            "container_path": self.volume.container_path,
            "shared": self.volume.shared,
            "flags": self.volume.flags,
            # "host_path": self.volume.host_path,
        }
        host_path = self.volume.host_path

        if not host_path:
            # we don't want to use a with statement, as the temporary directory
            # must survive this function
            # pylint: disable=consider-using-with
            self._tmpdir = tempfile.TemporaryDirectory()

            host_path = self._tmpdir.name

            _logger.debug(
                "created temporary directory %s for the container volume %s",
                host_path,
                self.volume.container_path,
            )

        kwargs["host_path"] = host_path
        if isabs(host_path) and not exists(host_path):
            raise RuntimeError(
                f"Volume with the host path '{host_path}' "
                "was requested but the directory does not exist"
            )

        self._created_volume = CreatedBindMount(**kwargs)

        return self

    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> None:
        """Cleans up the temporary host directory or the container volume."""
        assert self._created_volume and self._created_volume.host_path

        if self._tmpdir:
            _logger.debug(
                "cleaning up directory %s for the container volume %s",
                self.volume.host_path,
                self.volume.container_path,
            )
            self._tmpdir.cleanup()


@overload
def get_volume_creator(
    volume: ContainerVolume, runtime: OciRuntimeBase
) -> VolumeCreator:
    ...  # pragma: no cover


@overload
def get_volume_creator(
    volume: BindMount, runtime: OciRuntimeBase
) -> BindMountCreator:
    ...  # pragma: no cover


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

    assert False, f"invalid volume type {type(volume)}"  # pragma: no cover
