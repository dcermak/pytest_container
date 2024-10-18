"""This module contains the container runtime classes abstracting away the
implementation details of container runtimes like :command:`docker` or
:command:`podman`.

"""
import json
import re
import shutil
import subprocess
import sys
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from os import getenv
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import TYPE_CHECKING
from typing import Union

from _pytest.mark.structures import ParameterSet
from pytest import param
from pytest_container.inspect import BindMount
from pytest_container.inspect import Config
from pytest_container.inspect import ContainerHealth
from pytest_container.inspect import ContainerInspect
from pytest_container.inspect import ContainerNetworkSettings
from pytest_container.inspect import ContainerState
from pytest_container.inspect import HealthCheck
from pytest_container.inspect import NetworkProtocol
from pytest_container.inspect import PortForwarding
from pytest_container.inspect import VolumeMount
from pytest_container.logging import _logger


if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

from .compat import cached_property

if TYPE_CHECKING:  # pragma: no cover
    import pytest_container


@dataclass(frozen=True)
class ToParamMixin:
    """
    Mixin class that gives child classes the ability to convert themselves into
    a pytest.param with self.__str__() as the default id and optional marks
    """

    marks: Any = None

    def to_pytest_param(self) -> ParameterSet:
        """Convert this class into a ``pytest.param``"""
        return param(self, id=str(self), marks=self.marks or ())


@dataclass(frozen=True)
class Version:
    """Representation of a version of the form
    ``$major.$minor.$patch[-|+]$release build $build``.

    This class supports basic comparison, e.g.:

    >>> Version(1, 0) > Version(0, 1)
    True
    >>> Version(1, 0) == Version(1, 0, 0)
    True
    >>> Version(5, 2, 6, "foobar") == Version(5, 2, 6)
    False

    Note that the patch and release fields are optional and that the release and
    build are not taken into account for less or greater than comparisons only
    for equality or inequality. I.e.:

    >>> Version(1, 0, release="16") > Version(1, 0)
    False
    >>> Version(1, 0, release="16") == Version(1, 0)
    False


    Additionally you can also pretty print it:

    >>> Version(0, 6)
    0.6
    >>> Version(0, 6, 1)
    0.6.1
    >>> Version(0, 6, 1, "asdf")
    0.6.1 build asdf

    """

    major: int = 0
    minor: int = 0
    patch: Optional[int] = None
    build: str = ""
    release: Optional[str] = None

    def __str__(self) -> str:
        return (
            f"{self.major}.{self.minor}{('.' + str(self.patch)) if self.patch is not None else ''}"
            + (f"-{self.release}" if self.release else "")
            + (f" build {self.build}" if self.build else "")
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Version):
            return False
        return (
            self.major == other.major
            and self.minor == other.minor
            and (self.patch or 0) == (other.patch or 0)
            and (self.release or "") == (other.release or "")
            and self.build == other.build
        )

    @staticmethod
    def parse(version_string: str) -> "Version":
        """Parses a version string and returns a constructed Version from that."""
        matches = re.match(
            r"(?P<major>\d+)(\.(?P<minor>\d+))?(\.(?P<patch>\d+))?"
            r"([+|-](?P<release>\S+))?( build (?P<build>\S+))?$",
            # let's first remove any leading & trailing whitespace to make our life easier
            version_string.strip(),
        )
        if not matches:
            raise ValueError(f"Invalid version string: {version_string}")

        return Version(
            major=int(matches.group("major")),
            minor=int(matches.group("minor")) if matches.group("minor") else 0,
            patch=(
                int(matches.group("patch")) if matches.group("patch") else None
            ),
            build=matches.group("build") or "",
            release=matches.group("release") or None,
        )

    @staticmethod
    def __generate_cmp(
        cmp_func: Callable[[int, int], bool],
    ) -> Callable[["Version", Any], bool]:
        def cmp(self: Version, other: Any) -> bool:
            if not isinstance(other, Version):
                return NotImplemented

            if self.major == other.major:
                if self.minor == other.minor:
                    return cmp_func((self.patch or 0), (other.patch or 0))
                return cmp_func(self.minor, other.minor)
            return cmp_func(self.major, other.major)

        return cmp

    def __lt__(self, other: Any) -> bool:
        return Version.__generate_cmp(lambda m, n: m < n)(self, other)

    def __le__(self, other: Any) -> bool:
        return Version.__generate_cmp(lambda m, n: m <= n)(self, other)

    def __ge__(self, other: Any) -> bool:
        return Version.__generate_cmp(lambda m, n: m >= n)(self, other)

    def __gt__(self, other: Any) -> bool:
        return Version.__generate_cmp(lambda m, n: m > n)(self, other)


@dataclass(frozen=True)
class _OciRuntimeBase:
    #: command that builds the Dockerfile in the current working directory
    build_command: Tuple[str, ...] = field(default_factory=tuple)
    #: the "main" binary of this runtime, e.g. podman or docker
    runner_binary: str = ""
    _runtime_functional: bool = False


class OciRuntimeABC(ABC):
    """The abstract base class defining the interface of a container runtime."""

    def get_container_health(self, container_id: str) -> ContainerHealth:
        """Inspects the running container with the supplied id and returns its current
        health.

        """
        return self.inspect_container(container_id).state.health

    @property
    @abstractmethod
    def version(self) -> Version:
        """The version of the container runtime."""

    @abstractmethod
    def inspect_container(self, container_id: str) -> ContainerInspect:
        """Inspect the container with the provided ``container_id`` and return
        the parsed output from the container runtime as an instance of
        :py:class:`~pytest_container.inspect.ContainerInspect`.

        """

    @property
    @abstractmethod
    def supports_healthcheck_inherit_from_base(self) -> bool:
        """Indicates whether the container runtime supports that derived images
        will inherit the healthcheck from the base image.

        """

    @property
    @abstractmethod
    def family(self) -> Literal["docker", "podman"]:
        """The family of the container runtime, either ``docker`` or ``podman``."""


class OciRuntimeBase(_OciRuntimeBase, OciRuntimeABC, ToParamMixin):
    """Base class of the Container Runtimes."""

    @staticmethod
    def get_image_id_from_iidfile(iidfile_path: str) -> str:
        """Returns the image id/hash from the iidfile that has been created by
        the container runtime to store the image id after a build.

        """
        with open(iidfile_path, "r", encoding="utf-8") as iidfile:
            line = iidfile.read(-1).strip().split(":")
            if len(line) == 2:
                digest_hash, digest = line
                if digest_hash != "sha256":
                    raise ValueError(f"Invalid digest hash: {digest_hash}")
                return digest
            if len(line) == 1:
                return line[0]

            raise ValueError(f"Invalid iidfile contents: {':'.join(line)}")

    def get_image_size(
        self,
        image_or_id_or_container: Union[
            str,
            "pytest_container.container.Container",
            "pytest_container.container.DerivedContainer",
        ],
    ) -> float:
        """Returns the container's size in bytes given an image id, a
        :py:class:`~pytest_container.container.Container` or a
        py:class:`~pytest_container.container.DerivedContainer`.

        """
        id_to_inspect = (
            image_or_id_or_container
            if isinstance(image_or_id_or_container, str)
            else str(image_or_id_or_container)
        )
        return float(
            self.run_command(
                "inspect",
                "-f",
                '"{{ .Size }}"',
                id_to_inspect,
            ).replace('"', "")
        )

    def _run_inspect(self, container_id: str) -> Union[Dict[str, Any], None]:
        inspect = json.loads(
            self.run_command("inspect", container_id, ignore_errors=True)
        )
        if not isinstance(inspect, list):
            raise RuntimeError(
                f"Expected a list of results, but got {inspect} instead"
            )

        if len(inspect) > 1:
            raise RuntimeError(
                f"Got {len(inspect)} results back, "
                f"but expected exactly one container to match {container_id}"
            )

        return inspect[0] if inspect else None

    def _get_image_entrypoint_cmd(
        self, image_url_or_id: str, query_type: Literal["Entrypoint", "Cmd"]
    ) -> Optional[str]:
        """Inspect the container image with the given url or id and return its
        ``ENTRYPOINT`` or ``CMD`` or ``None`` if no entrypoint or cmd has been
        defined.

        """
        entrypoint = self.run_command(
            "inspect", "-f", f"{{{{.Config.{query_type}}}}}", image_url_or_id
        )
        return None if entrypoint == "[]" else entrypoint

    def run_command(
        self,
        *args: str,
        ignore_errors: bool = False,
        strip: bool = True,
    ) -> str:
        cmd = [self.runner_binary]
        cmd.extend(args)
        result: str
        try:
            # universal_newlines is an alias for text before python 3.7
            result = subprocess.check_output(
                cmd, stderr=subprocess.PIPE, universal_newlines=True
            )
        except subprocess.CalledProcessError as exc:
            if not ignore_errors:
                _logger.error(exc.stderr)
                raise exc
            result = exc.stdout
        if strip:
            result = result.strip()
        return result

    @staticmethod
    def _stop_signal_from_inspect_conf(inspect_conf: Any) -> Union[int, str]:
        if "StopSignal" in inspect_conf:
            raw_stop_signal = inspect_conf["StopSignal"]
            try:
                return int(raw_stop_signal)
            except ValueError:
                return str(raw_stop_signal)
        return "SIGTERM"

    @staticmethod
    def _state_from_inspect(container_inspect: Any) -> ContainerState:
        State = container_inspect["State"]
        return ContainerState(
            status=State["Status"],
            running=State["Running"],
            paused=State["Paused"],
            restarting=State["Restarting"],
            oom_killed=State["OOMKilled"],
            dead=State["Dead"],
            pid=State["Pid"],
            # depending on the podman version, this property is called either
            # Health or Healthcheck
            health=ContainerHealth(
                (State.get("Health") or State.get("Healthcheck", {})).get(
                    "Status", ""
                )
            ),
        )

    @staticmethod
    def _network_settings_from_inspect(
        container_inspect: Any,
    ) -> ContainerNetworkSettings:
        # we don't use the NetworkSettings object, but HostConfig as
        # NetworkSettings.Ports changed its structure at some point between
        # podman 1 and 4 from a dictionary into a list. However
        # HostConfig.PortBindings has always been a dictionary, so let's use
        # that for stability.
        host_config = container_inspect["HostConfig"]
        ports = []
        if "PortBindings" in host_config and host_config["PortBindings"]:
            for container_port, bindings in host_config[
                "PortBindings"
            ].items():
                if not bindings:
                    continue

                port, proto = container_port.split("/")
                # FIXME: handle multiple entries here
                ports.append(
                    PortForwarding(
                        container_port=int(port),
                        protocol=NetworkProtocol(proto),
                        host_port=int(bindings[0]["HostPort"]),
                    )
                )

        net_settings = container_inspect["NetworkSettings"]
        ip = net_settings.get("IPAddress") or None

        return ContainerNetworkSettings(ports=ports, ip_address=ip)

    @staticmethod
    def _mounts_from_inspect(
        container_inspect: Any,
    ) -> List[Union[BindMount, VolumeMount]]:
        mounts = container_inspect["Mounts"]
        res: List[Union[BindMount, VolumeMount]] = []
        for mount in mounts:
            kwargs = {
                "source": mount["Source"],
                "destination": mount["Destination"],
                "rw": mount["RW"],
            }
            if mount["Type"] == "volume":
                res.append(
                    VolumeMount(
                        name=mount["Name"], driver=mount["Driver"], **kwargs
                    )
                )
            elif mount["Type"] == "bind":
                res.append(BindMount(**kwargs))
            else:
                raise ValueError(f"Unknown mount type: {mount['Type']}")
        return res

    def __str__(self) -> str:
        return self.__class__.__name__


def _get_podman_version(version_stdout: str) -> Version:
    if version_stdout[:15] != "podman version ":
        raise RuntimeError(
            f"Could not decode the podman version from '{version_stdout}'"
        )

    return Version.parse(version_stdout[15:])


def _get_buildah_version(buildah_binary: str = "buildah") -> Version:
    version_stdout = subprocess.check_output(
        [buildah_binary, "--version"]
    ).decode()
    build_version_begin = "buildah version "
    if not version_stdout.startswith(build_version_begin):
        raise RuntimeError(
            f"Could not decode the buildah version from '{version_stdout}'"
        )

    return Version.parse(
        version_stdout.replace(build_version_begin, "").split(" ")[0]
    )


class _AutoDetect:
    INSTANCE: "_AutoDetect"


_AutoDetect.INSTANCE = _AutoDetect()


class PodmanRuntime(OciRuntimeBase):
    """The container runtime using :command:`podman` for running containers and
    :command:`buildah` for building containers.

    """

    def __init__(
        self,
        runner_binary: str = "podman",
        buildah_binary: Union[str, _AutoDetect, None] = _AutoDetect.INSTANCE,
    ) -> None:
        resolved_buildah_binary: Optional[str] = None

        if buildah_binary is _AutoDetect.INSTANCE:
            # try to guess if argument is omitted
            buildah_binary = shutil.which("buildah")

        if buildah_binary is None:
            # if explicitly set to None or not found, we don't have buildah
            resolved_buildah_binary = None
            self._buildah_functional = False

        elif isinstance(buildah_binary, str):
            # make sure it's fully resolved and not just a binary name
            buildah_binary = shutil.which("buildah")
            self._buildah_functional = (
                subprocess.run(
                    [buildah_binary, "--version"], check=False
                ).returncode
                == 0
                if buildah_binary is not None
                else False
            )
            resolved_buildah_binary = buildah_binary

        super().__init__(
            build_command=tuple(
                [resolved_buildah_binary, "bud", "--layers", "--force-rm"]
                if resolved_buildah_binary is not None
                and self._buildah_functional
                else [runner_binary, "build", "--layers", "--force-rm"]
            ),
            runner_binary=runner_binary,
            _runtime_functional=self._runtime_functional,
        )

    # pragma pylint: disable=used-before-assignment
    @cached_property
    def version(self) -> Version:
        """Returns the version of podman installed on the system"""
        return _get_podman_version(
            subprocess.check_output([self.runner_binary, "--version"]).decode()
        )

    @property
    def family(self) -> Literal["podman"]:
        return "podman"

    @cached_property
    def supports_healthcheck_inherit_from_base(self) -> bool:
        # - buildah supports inheriting HEALTHCHECK since 1.25.0
        #   https://github.com/containers/buildah/blob/main/CHANGELOG.md#v1250-2022-03-25
        # - podman 4.1.0 bundles buildah >= 1.25.0
        #   https://github.com/containers/podman/blob/main/RELEASE_NOTES.md#misc-8
        podman_recent_enough = self.version >= Version(4, 1, 0)

        # if buildah isn't installed, don't check the buildah version
        if not self._buildah_functional:
            return podman_recent_enough

        return podman_recent_enough and _get_buildah_version() >= Version(
            1, 25, 0
        )

    def inspect_container(self, container_id: str) -> ContainerInspect:
        inspect = self._run_inspect(container_id)
        if not inspect:
            raise RuntimeError(f"Container with id {container_id} not found")

        config = inspect["Config"]
        healthcheck = None
        if "Healthcheck" in config:
            healthcheck = HealthCheck.from_container_inspect(
                config["Healthcheck"]
            )

        entrypoint = config.get("Entrypoint")
        if isinstance(entrypoint, str):
            entrypoint = entrypoint.split()
        if not entrypoint:
            entrypoint = []

        conf = Config(
            user=config["User"],
            tty=config["Tty"],
            cmd=config["Cmd"],
            image=config["Image"],
            entrypoint=entrypoint,
            labels=config["Labels"],
            workingdir=Path(config["WorkingDir"]),
            env=dict([env.split("=", maxsplit=1) for env in config["Env"]]),
            stop_signal=self._stop_signal_from_inspect_conf(config),
            healthcheck=healthcheck,
        )

        state = self._state_from_inspect(inspect)

        return ContainerInspect(
            config=conf,
            state=state,
            name=inspect["Name"],
            id=inspect["Id"],
            path=inspect["Path"],
            args=inspect["Args"],
            image_hash=inspect["Image"],
            network=self._network_settings_from_inspect(inspect),
            mounts=self._mounts_from_inspect(inspect),
        )


def _get_docker_version(version_stdout: str) -> Version:
    if version_stdout[:15].lower() != "docker version ":
        raise RuntimeError(
            f"Could not decode the docker version from {version_stdout}"
        )

    return Version.parse(version_stdout[15:].replace(",", ""))


class DockerRuntime(OciRuntimeBase):
    """The container runtime using :command:`docker` for building and running
    containers."""

    def __init__(self, runner_binary: str = "docker") -> None:
        super().__init__(
            build_command=(runner_binary, "build", "--force-rm"),
            runner_binary=runner_binary,
            _runtime_functional=self._runtime_functional,
        )

    @cached_property
    def version(self) -> Version:
        """Returns the version of docker installed on this system"""
        return _get_docker_version(
            subprocess.check_output([self.runner_binary, "--version"]).decode()
        )

    @property
    def family(self) -> Literal["docker"]:
        return "docker"

    @property
    def supports_healthcheck_inherit_from_base(self) -> bool:
        return True

    def inspect_container(self, container_id: str) -> ContainerInspect:
        inspect = self._run_inspect(container_id)
        if not inspect:
            raise RuntimeError(f"Container with id {container_id} not found")

        config = inspect["Config"]
        if config.get("Env"):
            env = dict([env.split("=", maxsplit=1) for env in config["Env"]])
        else:
            env = {}
        healthcheck = None
        if "Healthcheck" in config:
            healthcheck = HealthCheck.from_container_inspect(
                config["Healthcheck"]
            )

        conf = Config(
            user=config["User"],
            tty=config["Tty"],
            cmd=config["Cmd"],
            image=config["Image"],
            entrypoint=config["Entrypoint"],
            labels=config["Labels"],
            # docker sometimes omits the working directory,
            # then it defaults to
            workingdir=Path(config["WorkingDir"] or "/"),
            stop_signal=self._stop_signal_from_inspect_conf(config),
            env=env,
            healthcheck=healthcheck,
        )

        state = self._state_from_inspect(inspect)

        return ContainerInspect(
            config=conf,
            state=state,
            # docker prefixes the name with a / for reasons…
            name=inspect["Name"].lstrip("/"),
            id=inspect["Id"],
            path=inspect["Path"],
            args=inspect["Args"],
            image_hash=inspect["Image"],
            network=self._network_settings_from_inspect(inspect),
            mounts=self._mounts_from_inspect(inspect),
        )


@dataclass
class CachedRuntime:
    requested_runtime: str
    resolved_runtime_family: Literal["docker", "podman"]
    runtime: Union[OciRuntimeBase, ValueError]


_CACHED_RUNTIME: Optional[CachedRuntime] = None


def _resolve_runtime(requested: str) -> Tuple[str, Optional[str]]:
    if requested not in ["docker", "podman", "auto"]:
        raise ValueError(f"Invalid CONTAINER_RUNTIME value: {requested}")
    current = requested
    if current == "auto":
        podmain_path = shutil.which("podman")
        if podmain_path:
            current = "podman"
        else:
            docker_path = shutil.which("docker")
            if docker_path:
                current = "docker"
            else:
                raise ValueError("Neither podman nor docker are installed")

    return current, shutil.which(current)


def get_selected_runtime() -> OciRuntimeBase:
    """Returns the container runtime that the user selected.

    It defaults to podman and selects docker if podman & buildah are not
    present. If podman and docker are both present, then docker is returned if
    the environment variable `CONTAINER_RUNTIME` is set to `docker`.

    If neither docker nor podman are available, then a ValueError is raised.
    """
    global _CACHED_RUNTIME
    requested = getenv("CONTAINER_RUNTIME", "auto").lower()

    if (
        _CACHED_RUNTIME is not None
        and _CACHED_RUNTIME.requested_runtime != requested
    ):
        # check if the user changed the runtime via an environment variable
        _CACHED_RUNTIME = None

    if _CACHED_RUNTIME is None:
        resolved, binary = _resolve_runtime(requested)
        if resolved == "docker":
            _CACHED_RUNTIME = CachedRuntime(
                requested_runtime=requested,
                resolved_runtime_family="docker",
                runtime=(
                    DockerRuntime(binary)
                    if binary
                    else ValueError("docker runtime missing or not functional")
                ),
            )
        elif resolved == "podman":
            _CACHED_RUNTIME = CachedRuntime(
                requested_runtime=requested,
                resolved_runtime_family="podman",
                runtime=(
                    PodmanRuntime(binary)
                    if binary
                    else ValueError("podman runtime missing or not functional")
                ),
            )
        else:
            raise ValueError(
                f"Resolved runtime is neither docker nor podman: {resolved}"
            )

    if isinstance(_CACHED_RUNTIME.runtime, ValueError):
        raise _CACHED_RUNTIME.runtime

    return _CACHED_RUNTIME.runtime
