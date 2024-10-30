"""The container module contains all classes for abstracting the details of
launching containers away. These classes are used to parametrize test cases
using the fixtures provided by this plugin.

"""
import contextlib
import enum
import functools
import inspect
import itertools
import operator
import os
import socket
import sys
import tempfile
import time
import warnings
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from hashlib import sha3_256
from os.path import join
from pathlib import Path
from subprocess import call
from subprocess import check_output
from types import TracebackType
from typing import Any
from typing import Collection
from typing import Dict
from typing import List
from typing import Optional
from typing import overload
from typing import Tuple
from typing import Type
from typing import Union
from uuid import uuid4

import _pytest.mark
import deprecation
import pytest
import testinfra
from filelock import BaseFileLock
from filelock import FileLock
from pytest_container.helpers import get_always_pull_option
from pytest_container.helpers import get_extra_build_args
from pytest_container.helpers import get_extra_run_args
from pytest_container.inspect import ContainerHealth
from pytest_container.inspect import ContainerInspect
from pytest_container.inspect import PortForwarding
from pytest_container.inspect import VolumeMount
from pytest_container.logging import _logger
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase
from pytest_container.volume import BindMount
from pytest_container.volume import ContainerVolume
from pytest_container.volume import get_volume_creator


if sys.version_info >= (3, 8):
    from importlib import metadata
    from typing import Literal
else:
    import importlib_metadata as metadata
    from typing_extensions import Literal


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


def lock_host_port_search(rootdir: Path) -> BaseFileLock:
    """Generate a filelock for finding free ports on the host."""
    return FileLock(rootdir / "port_check.lock")


def create_host_port_port_forward(
    port_forwards: List[PortForwarding],
) -> List[PortForwarding]:
    """Given a list of port_forwards, this function finds random free ports on
    the host system to which the container ports can be bound and returns a new
    list of appropriately configured
    :py:class:`~pytest_container.inspect.PortForwarding` instances.

    """
    finished_forwards: List[PortForwarding] = []

    # We have to defer the cleanup of all sockets via an ExitStack, as otherwise
    # the OS might give us a previously freed port again. But it will not do
    # that, if we are still listening on it
    with contextlib.ExitStack() as stack:
        for port in port_forwards:
            if socket.has_ipv6 and (":" in port.bind_ip or not port.bind_ip):
                family = socket.AF_INET6
            else:
                family = socket.AF_INET

            sock = stack.enter_context(
                socket.socket(
                    family=family,
                    type=port.protocol.SOCK_CONST,
                )
            )
            sock.bind((port.bind_ip, max(0, port.host_port)))

            port_num: int = sock.getsockname()[1]

            finished_forwards.append(
                PortForwarding(
                    container_port=port.container_port,
                    protocol=port.protocol,
                    host_port=port_num,
                    bind_ip=port.bind_ip,
                )
            )

    assert len(port_forwards) == len(finished_forwards)
    return finished_forwards


_CONTAINER_ENTRYPOINT = "/bin/bash"
_CONTAINER_STOPSIGNAL = ("--stop-signal", "SIGTERM")


@enum.unique
class EntrypointSelection(enum.Enum):
    """Choices how the entrypoint of a container is picked."""

    #: If :py:attr:`~ContainerBase.custom_entry_point` is set, then that value
    #: is used. Otherwise the container images entrypoint or cmd is used if it
    #: defines one, or else :file:`/bin/bash` is used.
    AUTO = enum.auto()

    #: :file:`/bin/bash` is used as the entry point
    BASH = enum.auto()

    #: The images' entrypoint or the default from the container runtime is used
    IMAGE = enum.auto()


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

    #: Defines which entrypoint of the container is used.
    #: By default either :py:attr:`custom_entry_point` will be used (if defined)
    #: or the container's entrypoint or cmd. If neither of the two is set, then
    #: :file:`/bin/bash` will be used.
    entry_point: EntrypointSelection = EntrypointSelection.AUTO

    #: custom entry point for this container (i.e. neither its default, nor
    #: :file:`/bin/bash`)
    custom_entry_point: Optional[str] = None

    #: List of additional flags that will be inserted after
    #: `docker/podman run -d` and before the image name (i.e. these arguments
    #: are not passed to the entrypoint or ``CMD``). The list must be properly
    #: escaped, e.g. as created by ``shlex.split``.
    extra_launch_args: List[str] = field(default_factory=list)

    #: List of additional arguments that are passed to the ``CMD`` or
    #: entrypoint. These arguments are inserted after the :command:`docker/podman
    #: run -d $image` on launching the image.
    #: The list must be properly escaped, e.g. by passing the string through
    #: ``shlex.split``.
    #: The arguments must not cause the container to exit early. It must remain
    #: active in the background, otherwise this library will not function
    #: properly.
    extra_entrypoint_args: List[str] = field(default_factory=list)

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
        if self.url.split(":", maxsplit=1)[0] == "containers-storage":
            self._is_local = True
            self.url = self.url.replace("containers-storage:", "")

    def __str__(self) -> str:
        return self.url or self.container_id

    @property
    def _build_tag(self) -> str:
        """Internal build tag assigned to each immage, either the image url or
        the container digest prefixed with ``pytest_container:``.

        """
        return self.url or f"pytest_container:{self.container_id}"

    @property
    def local_image(self) -> bool:
        """Returns true if this image has been build locally and has not been
        pulled from a registry.

        """
        return self._is_local

    def get_launch_cmd(
        self,
        container_runtime: OciRuntimeBase,
        extra_run_args: Optional[List[str]] = None,
    ) -> List[str]:
        """Returns the command to launch this container image.

        Args:
            extra_run_args: optional list of arguments that are added to the
                launch command directly after the ``run -d``.

        Returns:
            The command to launch the container image described by this class
            instance as a list of strings that can be fed directly to
            :py:class:`subprocess.Popen` as the ``args`` parameter.
        """
        cmd = (
            [container_runtime.runner_binary, "run", "-d"]
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

        id_or_url = self.container_id or self.url
        container_launch = ("-it", id_or_url)
        bash_launch_end = (
            *_CONTAINER_STOPSIGNAL,
            *container_launch,
            _CONTAINER_ENTRYPOINT,
        )
        if self.entry_point == EntrypointSelection.IMAGE:
            cmd.extend(container_launch)
        elif self.entry_point == EntrypointSelection.BASH:
            cmd.extend(
                (
                    "--entrypoint",
                    _CONTAINER_ENTRYPOINT,
                    *_CONTAINER_STOPSIGNAL,
                    *container_launch,
                )
            )
        elif self.entry_point == EntrypointSelection.AUTO:
            if self.custom_entry_point:
                cmd.extend(
                    (
                        "--entrypoint",
                        self.custom_entry_point,
                        *container_launch,
                    )
                )
            elif container_runtime._get_image_entrypoint_cmd(
                id_or_url, "Entrypoint"
            ) or container_runtime._get_image_entrypoint_cmd(id_or_url, "Cmd"):
                cmd.extend(container_launch)
            else:
                cmd.extend(bash_launch_end)
        else:  # pragma: no cover
            assert False, "This branch must be unreachable"  # pragma: no cover

        cmd.extend(self.extra_entrypoint_args)

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

        # Use a FIPS supported algorithm in here to avoid potential issues on
        # hosts running in FIPS mode
        # Unfortunately, we cannot use the usedforsecurity=False parameter, as
        # that is not available on old python versions that we still support
        return f"{sha3_256((''.join(all_elements)).encode()).hexdigest()}.lock"


class ContainerBaseABC(ABC):
    """Abstract base class defining the methods that must be implemented by the
    classes fed to the ``*container*`` fixtures.

    """

    @abstractmethod
    def prepare_container(
        self,
        container_runtime: OciRuntimeBase,
        rootdir: Path,
        extra_build_args: Optional[List[str]],
    ) -> None:
        """Prepares the container so that it can be launched."""

    @abstractmethod
    def get_base(self) -> "Union[Container, DerivedContainer]":
        """Returns the Base of this Container Image. If the container has no
        base, then ``self`` is returned.

        """

    @property
    @abstractmethod
    def baseurl(self) -> Optional[str]:
        """The registry url on which this container is based on, if one
        exists. Otherwise ``None`` is returned.

        """


@dataclass(unsafe_hash=True)
class Container(ContainerBase, ContainerBaseABC):
    """This class stores information about the Container Image under test."""

    def pull_container(self, container_runtime: OciRuntimeBase) -> None:
        """Pulls the container with the given url using the currently selected
        container runtime"""
        _logger.debug(
            "Pulling %s via %s", self.url, container_runtime.runner_binary
        )
        check_output([container_runtime.runner_binary, "pull", self.url])

    def prepare_container(
        self,
        container_runtime: OciRuntimeBase,
        rootdir: Path,
        extra_build_args: Optional[List[str]] = None,
    ) -> None:
        """Prepares the container so that it can be launched."""
        if self._is_local:
            return

        if get_always_pull_option():
            self.pull_container(container_runtime)
            return

        if call([container_runtime.runner_binary, "inspect", self.url]) != 0:
            self.pull_container(container_runtime)

    def get_base(self) -> "Container":
        return self

    @property
    def baseurl(self) -> Optional[str]:
        if self._is_local:
            return None
        return self.url


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

    #: An optional image format when building images with :command:`buildah`. It
    #: is ignored when the container runtime is :command:`docker`.
    #: The ``oci`` image format is used by default. If the image format is
    #: ``None`` and the base image has a ``HEALTHCHECK`` defined, then the
    #: ``docker`` image format will be used instead.
    #: Specifying an image format disables the auto-detection and uses the
    #: supplied value.
    image_format: Optional[ImageFormat] = None

    #: Additional build tags/names that should be added to the container once it
    #: has been built
    add_build_tags: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.base:
            raise ValueError("A base container must be provided")

    @property
    def baseurl(self) -> Optional[str]:
        return self.url or self.get_base().baseurl

    def __str__(self) -> str:
        return (
            self.container_id
            or f"container derived from {self.base.__str__()}"
        )

    def get_base(self) -> Union[Container, "DerivedContainer"]:
        """Return the base of this derived container."""
        if isinstance(self.base, str):
            return Container(url=self.base)
        return self.base

    def prepare_container(
        self,
        container_runtime: OciRuntimeBase,
        rootdir: Path,
        extra_build_args: Optional[List[str]] = None,
    ) -> None:
        _logger.debug("Preparing derived container based on %s", self.base)
        if isinstance(self.base, str):
            # we need to pull the container so that the inspect in the launcher
            # doesn't fail
            Container(url=self.base).prepare_container(
                container_runtime, rootdir, extra_build_args
            )
        else:
            self.base.prepare_container(
                container_runtime, rootdir, extra_build_args
            )

        runtime = get_selected_runtime()

        # do not build containers without a containerfile and where no build
        # tags are added
        if not self.containerfile and not self.add_build_tags:
            base = self.get_base()
            base.prepare_container(
                container_runtime, rootdir, extra_build_args
            )
            self.container_id, self.url = base.container_id, base.url
            return

        with tempfile.TemporaryDirectory() as tmpdirname:
            containerfile_path = join(tmpdirname, "Dockerfile")
            iidfile = join(tmpdirname, str(uuid4()))
            with open(containerfile_path, "w") as containerfile:
                from_id = (
                    self.base
                    if isinstance(self.base, str)
                    else (getattr(self.base, "url") or self.base._build_tag)
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

            cmd = runtime.build_command
            if "podman" in runtime.runner_binary:
                if self.image_format is not None:
                    cmd += ["--format", str(self.image_format)]
                else:
                    if not runtime.supports_healthcheck_inherit_from_base:
                        warnings.warn(
                            UserWarning(
                                "Runtime does not support inheriting HEALTHCHECK "
                                "from base images, image format auto-detection "
                                "will *not* work!"
                            )
                        )

                    # if the parent image has a healthcheck defined, then we
                    # have to use the docker image format, so that the
                    # healthcheck is in newly build image as well
                    elif (
                        "<nil>"
                        != check_output(
                            [
                                runtime.runner_binary,
                                "inspect",
                                "-f",
                                "{{.HealthCheck}}",
                                from_id,
                            ]
                        )
                        .decode()
                        .strip()
                    ):
                        cmd += ["--format", str(ImageFormat.DOCKER)]

            cmd += (
                (extra_build_args or [])
                + (
                    functools.reduce(
                        operator.add,
                        (["-t", tag] for tag in self.add_build_tags),
                    )
                    if self.add_build_tags
                    else []
                )
                + [
                    f"--iidfile={iidfile}",
                    "-f",
                    containerfile_path,
                    str(rootdir),
                ]
            )

            _logger.debug("Building image via: %s", cmd)
            check_output(cmd)

            self.container_id = runtime.get_image_id_from_iidfile(iidfile)

            assert self._build_tag.startswith("pytest_container:")

            check_output(
                (
                    runtime.runner_binary,
                    "tag",
                    self.container_id,
                    self._build_tag,
                )
            )

            _logger.debug(
                "Successfully build the container image %s and tagged it as %s",
                self.container_id,
                self._build_tag,
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
    container: Union[Container, DerivedContainer]
    #: any ports that are exposed by this container
    forwarded_ports: List[PortForwarding]

    _container_runtime: OciRuntimeBase

    @property
    def inspect(self) -> ContainerInspect:
        """Inspect the launched container and return the result of
        :command:`$runtime inspect $ctr_id`.

        """
        return self._container_runtime.inspect_container(self.container_id)

    def read_container_logs(self) -> str:
        """Returns the logs from the running container."""
        return check_output(
            [self._container_runtime.runner_binary, "logs", self.container_id]
        ).decode()


def container_to_pytest_param(
    container: ContainerBase,
    marks: Optional[
        Union[
            Collection[_pytest.mark.MarkDecorator], _pytest.mark.MarkDecorator
        ]
    ] = None,
) -> _pytest.mark.ParameterSet:
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


@overload
def container_and_marks_from_pytest_param(
    ctr_or_param: Container,
) -> Tuple[Container, Literal[None]]:
    ...


@overload
def container_and_marks_from_pytest_param(
    ctr_or_param: DerivedContainer,
) -> Tuple[DerivedContainer, Literal[None]]:
    ...


@overload
def container_and_marks_from_pytest_param(
    ctr_or_param: _pytest.mark.ParameterSet,
) -> Tuple[
    Union[Container, DerivedContainer],
    Optional[Collection[Union[_pytest.mark.MarkDecorator, _pytest.mark.Mark]]],
]:
    ...


def container_and_marks_from_pytest_param(
    ctr_or_param: Union[
        _pytest.mark.ParameterSet, Container, DerivedContainer
    ],
) -> Tuple[
    Union[Container, DerivedContainer],
    Optional[Collection[Union[_pytest.mark.MarkDecorator, _pytest.mark.Mark]]],
]:
    """Extracts the :py:class:`~pytest_container.container.Container` or
    :py:class:`~pytest_container.container.DerivedContainer` and the
    corresponding marks from a `pytest.param
    <https://docs.pytest.org/en/stable/reference.html?#pytest.param>`_ and
    returns both.

    If ``param`` is either a :py:class:`~pytest_container.container.Container`
    or a :py:class:`~pytest_container.container.DerivedContainer`, then param is
    returned directly and the second return value is ``None``.

    """
    if isinstance(ctr_or_param, (Container, DerivedContainer)):
        return ctr_or_param, None

    if len(ctr_or_param.values) > 0 and isinstance(
        ctr_or_param.values[0], (Container, DerivedContainer)
    ):
        return ctr_or_param.values[0], ctr_or_param.marks

    raise ValueError(f"Invalid pytest.param values: {ctr_or_param.values}")


@deprecation.deprecated(
    deprecated_in="0.4.0",
    removed_in="0.5.0",
    current_version=metadata.version("pytest_container"),
    details="use container_and_marks_from_pytest_param instead",
)  # type: ignore
def container_from_pytest_param(
    param: Union[_pytest.mark.ParameterSet, Container, DerivedContainer],
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

    #: optional name of this container
    container_name: str = ""

    _expose_ports: bool = True

    _new_port_forwards: List[PortForwarding] = field(default_factory=list)
    _container_id: Optional[str] = None

    _stack: contextlib.ExitStack = field(default_factory=contextlib.ExitStack)

    _cidfile: str = field(
        default_factory=lambda: join(tempfile.gettempdir(), str(uuid4()))
    )

    @staticmethod
    def from_pytestconfig(
        container: Union[Container, DerivedContainer],
        container_runtime: OciRuntimeBase,
        pytestconfig: pytest.Config,
        container_name: str = "",
    ) -> "ContainerLauncher":
        """Constructor of :py:class:`ContainerLauncher` that obtains the
        attributes :py:attr:`rootdir`, :py:attr:`extra_build_args` and
        :py:attr:`extra_run_args` from the pytest configuration object.

        """
        return ContainerLauncher(
            container=container,
            container_runtime=container_runtime,
            rootdir=pytestconfig.rootpath,
            extra_build_args=get_extra_build_args(pytestconfig),
            extra_run_args=get_extra_run_args(pytestconfig),
            container_name=container_name,
        )

    def __enter__(self) -> "ContainerLauncher":
        return self

    def launch_container(self) -> None:
        """This function performs the actual heavy lifting of launching the
        container, creating all the volumes, port bindings, etc.pp.

        """
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

        def release_lock() -> None:
            _logger.debug("Releasing lock %s", lock.lock_file)
            lock.release()
            # we're fine with another process/thread having deleted the
            # lockfile, as long as the locking was thread safe
            try:
                # no we can't use Path.unlink(missing_ok=True) here, as the kw
                # argument is not present in Python < 3.8
                os.unlink(lock.lock_file)
            except FileNotFoundError:
                pass

        # Container preparation can fail, but then we would never release the
        # lock as release_lock is not yet in self._stack. However, we do not
        # want to add it into the exitstack for most containers either, as they
        # should get unlocked right after preparation.
        try:
            lock.acquire()
            self.container.prepare_container(
                self.container_runtime, self.rootdir, self.extra_build_args
            )
        except:
            release_lock()
            raise

        # ordinary containers are only locked during the build,
        # singleton containers are unlocked after everything
        if not self.container.singleton:
            release_lock()
        else:
            self._stack.callback(release_lock)

        extra_run_args = self.extra_run_args

        if self.container_name:
            extra_run_args.extend(("--name", self.container_name))

        extra_run_args.append(f"--cidfile={self._cidfile}")

        new_container_volumes = []
        for cont_vol in self.container.volume_mounts:
            vol_creator = get_volume_creator(cont_vol, self.container_runtime)
            self._stack.enter_context(vol_creator)

            new_volume = vol_creator.created_volume
            assert new_volume
            new_container_volumes.append(new_volume)

            extra_run_args.append(new_volume.cli_arg)

        forwarded_ports = self.container.forwarded_ports

        # Create a copy of the container which was used to parametrize this test
        cls = type(self.container)
        constructor = inspect.signature(cls.__init__)
        constructor.parameters

        kwargs = {
            k: v
            for k, v in self.container.__dict__.items()
            if k in constructor.parameters
        }
        kwargs["volume_mounts"] = new_container_volumes

        # We must perform the launches in separate branches, as containers with
        # port forwards must be launched while the lock is being held. Otherwise
        # another container could pick the same ports before this one launches.
        if forwarded_ports and self._expose_ports:
            with lock_host_port_search(self.rootdir):
                self._new_port_forwards = create_host_port_port_forward(
                    forwarded_ports
                )
                for new_forward in self._new_port_forwards:
                    extra_run_args += new_forward.forward_cli_args

                kwargs["forwarded_ports"] = self._new_port_forwards
                ctr = cls(**kwargs)

                launch_cmd = ctr.get_launch_cmd(
                    self.container_runtime, extra_run_args=extra_run_args
                )

                _logger.debug("Launching container via: %s", launch_cmd)
                check_output(launch_cmd)
        else:
            ctr = cls(**kwargs)
            launch_cmd = ctr.get_launch_cmd(
                self.container_runtime, extra_run_args=extra_run_args
            )

            _logger.debug("Launching container via: %s", launch_cmd)
            check_output(launch_cmd)

        self.container = ctr

        with open(self._cidfile, "r", encoding="utf8") as cidfile:
            self._container_id = cidfile.read(-1).strip()

        self._wait_for_container_to_become_healthy()

    @property
    def container_data(self) -> ContainerData:
        """The :py:class:`ContainerData` instance corresponding to the running
        container. This property is only valid after the context manager has
        been "entered" via a ``with`` statement.

        """
        if not self._container_id:
            raise RuntimeError(f"Container {self.container} has not started")
        return ContainerData(
            image_url_or_id=self.container.url or self.container.container_id,
            container_id=self._container_id,
            connection=testinfra.get_host(
                f"{self.container_runtime.runner_binary}://{self._container_id}"
            ),
            container=self.container,
            forwarded_ports=self._new_port_forwards,
            _container_runtime=self.container_runtime,
        )

    def _wait_for_container_to_become_healthy(self) -> None:
        assert self._container_id

        start = datetime.now()
        timeout: Optional[timedelta] = self.container.healthcheck_timeout
        _logger.debug(
            "Started container with %s at %s", self._container_id, start
        )

        if timeout is None:
            healthcheck = self.container_runtime.inspect_container(
                self._container_id
            ).config.healthcheck
            if healthcheck is not None:
                timeout = healthcheck.max_wait_time

        if timeout is not None and timeout > timedelta(seconds=0):
            _logger.debug(
                "Container has a healthcheck defined, will wait at most %s s",
                timeout.total_seconds(),
            )
            while True:
                inspect = self.container_runtime.inspect_container(
                    self._container_id
                )
                if not inspect.state.running:
                    raise RuntimeError(
                        f"Container {self._container_id} is not running, got {inspect.state.status}"
                    )
                health = inspect.state.health
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
                        f"{timeout.total_seconds()}s, took "
                        f"{delta.total_seconds()}s and state is {str(health)}"
                    )
                time.sleep(max(0.5, timeout.total_seconds() / 10))

    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> None:
        mounts = []
        if self._container_id is not None:
            mounts = self.container_runtime.inspect_container(
                self._container_id
            ).mounts

            _logger.debug(
                "Stopping container %s via %s",
                self._container_id,
                self.container_runtime.runner_binary,
            )
            check_output(
                [
                    self.container_runtime.runner_binary,
                    "stop",
                    self._container_id,
                ]
            )
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
        self._container_id = None

        # cleanup automatically created volumes by VOLUME directives in the
        # Dockerfile:
        # just force remove them and ignore the returncode in case docker/podman
        # complain that the volume doesn't exist
        for mount in mounts:
            if isinstance(mount, VolumeMount):
                call(
                    [
                        self.container_runtime.runner_binary,
                        "volume",
                        "rm",
                        "-f",
                        mount.name,
                    ]
                )
