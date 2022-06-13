import enum
import re
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from os import getenv
from subprocess import check_output
from typing import Any
from typing import Callable
from typing import List
from typing import Optional
from typing import TYPE_CHECKING
from typing import Union

import pytest
import testinfra
from _pytest.mark.structures import ParameterSet

if TYPE_CHECKING:
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
        return pytest.param(self, id=str(self), marks=self.marks or ())


@dataclass(frozen=True)
class Version:
    """Representation of a version of the form ``$major.$minor.$patch`` and an
    optional build string.

    This class supports basic comparison, e.g.:

    >>> Version(1, 0) > Version(0, 1)
    True
    >>> Version(1, 0) == Version(1, 0, 0)
    True
    >>> Version(5, 2, 6, "foobar") == Version(5, 2, 6)
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

    def __str__(self) -> str:
        return (
            f"{self.major}.{self.minor}{('.' + str(self.patch)) if self.patch else ''}"
            + (f" build {self.build}" if self.build else "")
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Version):
            return False
        return (
            self.major == other.major
            and self.minor == other.minor
            and (self.patch or 0) == (other.patch or 0)
            and self.build == other.build
        )

    @staticmethod
    def __generate_cmp(
        cmp_func: Callable[[int, int], bool]
    ) -> Callable[["Version", Any], bool]:
        def cmp(self: Version, other: Any) -> bool:
            if not isinstance(other, Version):
                return NotImplemented

            if cmp_func(self.major, other.major):
                return True
            if cmp_func(self.minor, other.minor):
                return True
            if cmp_func(self.patch or 0, other.patch or 0):
                return True

            return False

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
    build_command: List[str] = field(default_factory=list)
    #: the "main" binary of this runtime, e.g. podman or docker
    runner_binary: str = ""
    _runtime_functional: bool = False
    _version: Version = field(default_factory=Version)


@enum.unique
class ContainerHealth(enum.Enum):
    """Possible states of a container's health using the `HEALTHCHECK
    <https://docs.docker.com/engine/reference/builder/#healthcheck>`_ property
    of a container image.

    """

    #: the container has no health check defined
    NO_HEALTH_CHECK = enum.auto()
    #: the container is healthy
    HEALTHY = enum.auto()
    #: the health check did not complete yet or did not fail often enough
    STARTING = enum.auto()
    #: the healthcheck failed
    UNHEALTHY = enum.auto()


class OciRuntimeABC(ABC):
    """The abstract base class defining the interface of a container runtime."""

    @staticmethod
    @abstractmethod
    def _runtime_error_message() -> str:
        """Returns a human readable error message why the runtime does not
        function.

        """

    @abstractmethod
    def get_image_id_from_stdout(self, stdout: str) -> str:
        """Returns the image id/hash from the stdout of a build command."""

    @abstractmethod
    def get_container_health(self, container_id: str) -> ContainerHealth:
        """Inspects the running container with the supplied id and returns its current
        health.

        """

    @property
    @abstractmethod
    def version(self) -> Version:
        """The version of the container runtime."""


class OciRuntimeBase(_OciRuntimeBase, OciRuntimeABC, ToParamMixin):
    """Base class of the Container Runtimes."""

    def __post_init__(self) -> None:
        if not self.build_command or not self.runner_binary:
            raise ValueError(
                f"build_command ({self.build_command}) or runner_binary "
                f"({self.runner_binary}) were not specified"
            )
        if not self._runtime_functional:
            raise RuntimeError(
                f"The runtime {self.__class__.__name__} is not functional: "
                + self._runtime_error_message()
            )

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
            check_output(
                [
                    self.runner_binary,
                    "inspect",
                    "-f",
                    '"{{ .Size }}"',
                    id_to_inspect,
                ]
            )
            .decode()
            .strip()
            .replace('"', "")
        )

    def __str__(self) -> str:
        return self.__class__.__name__

    @property
    def version(self) -> Version:
        """Returns the container runtime's version"""
        return self._version


LOCALHOST = testinfra.host.get_host("local://")


def _get_podman_version(version_stdout: str) -> Version:
    matches = re.match(
        r"podman version (?P<major>\d+)\.(?P<minor>\d+)(\.(?P<patch>\d+))?",
        version_stdout,
        flags=re.IGNORECASE,
    )
    if not matches:
        raise RuntimeError(
            f"Could not decode the podman version from {version_stdout}"
        )

    patch = matches.group("patch")
    return Version(
        major=int(matches.group("major")),
        minor=int(matches.group("minor")),
        patch=int(patch) if patch else 0,
    )


class PodmanRuntime(OciRuntimeBase):
    """The container runtime using :command:`podman` for running containers and
    :command:`buildah` for building containers.

    """

    _runtime_functional = (
        LOCALHOST.run("podman ps").succeeded
        and LOCALHOST.run("buildah").succeeded
    )

    _version = _get_podman_version(
        LOCALHOST.run_expect([0], "podman --version").stdout
    )

    @staticmethod
    def _runtime_error_message() -> str:
        if PodmanRuntime._runtime_functional:
            return ""
        podman_ps = LOCALHOST.run("podman ps")
        if not podman_ps.succeeded:
            return str(podman_ps.stderr)
        buildah = LOCALHOST.run("buildah")
        assert (
            not buildah.succeeded
        ), "buildah command must not succeed as PodmanRuntime is not functional"
        return str(buildah.stderr)

    def __init__(self) -> None:
        super().__init__(
            build_command=["buildah", "bud", "--layers", "--force-rm"],
            runner_binary="podman",
            _runtime_functional=self._runtime_functional,
        )

    def get_image_id_from_stdout(self, stdout: str) -> str:
        # buildah prints the full image hash to the last non-empty line
        return list(
            filter(None, map(lambda l: l.strip(), stdout.split("\n")))
        )[-1]

    def get_container_health(self, container_id: str) -> ContainerHealth:
        res = LOCALHOST.run_expect(
            [0],
            'podman inspect -f "{{ .State.Healthcheck.Status }}" '
            + container_id,
        )
        stdout = res.stdout.strip()
        if stdout == "":
            return ContainerHealth.NO_HEALTH_CHECK
        if stdout == "healthy":
            return ContainerHealth.HEALTHY
        if stdout == "starting":
            return ContainerHealth.STARTING
        return ContainerHealth.UNHEALTHY


def _get_docker_version(version_stdout: str) -> Version:
    matches = re.match(
        r"docker version (?P<major>\d+)\.(?P<minor>\d+)(\.(?P<patch>\d+)(\S+)?)?,"
        r" build (?P<build>\S+)",
        version_stdout,
        flags=re.IGNORECASE,
    )
    if not matches:
        raise RuntimeError(
            f"Could not decode the docker version from {version_stdout}"
        )
    patch = matches.group("patch")
    return Version(
        major=int(matches.group("major")),
        minor=int(matches.group("minor")),
        patch=int(patch) if patch else 0,
        build=matches.group("build"),
    )


class DockerRuntime(OciRuntimeBase):
    """The container runtime using :command:`docker` for building and running
    containers."""

    _version = _get_docker_version(
        LOCALHOST.run_expect([0], "docker --version").stdout
    )

    _runtime_functional = LOCALHOST.run("docker ps").succeeded

    @staticmethod
    def _runtime_error_message() -> str:
        if DockerRuntime._runtime_functional:
            return ""
        docker_ps = LOCALHOST.run("docker ps")
        assert (
            not docker_ps.succeeded
        ), "docker runtime is not functional, but 'docker ps' succeeded"
        return str(docker_ps.stderr)

    def __init__(self) -> None:
        super().__init__(
            build_command=["docker", "build", "--force-rm"],
            runner_binary="docker",
            _runtime_functional=self._runtime_functional,
        )

    def get_image_id_from_stdout(self, stdout: str) -> str:
        # docker build prints this into the last non-empty line:
        # Successfully built 1e3c746e8069
        # -> grab the last line (see podman) & the last entry
        last_line = list(
            filter(None, map(lambda l: l.strip(), stdout.split("\n")))
        )[-1]
        return last_line.split()[-1]

    def get_container_health(self, container_id: str) -> ContainerHealth:
        res = LOCALHOST.run_expect(
            [0, 1],
            'docker inspect -f "{{ .State.Health.Status }}" ' + container_id,
        )
        if (
            res.rc == 1
            and 'map has no entry for key "Health"' in res.stderr.strip()
        ):
            return ContainerHealth.NO_HEALTH_CHECK
        stdout = res.stdout.strip()
        if stdout == "healthy":
            return ContainerHealth.HEALTHY
        if stdout == "starting":
            return ContainerHealth.STARTING
        return ContainerHealth.UNHEALTHY


def get_selected_runtime() -> OciRuntimeBase:
    """Returns the container runtime that the user selected.

    It defaults to podman and selects docker if podman & buildah are not
    present. If podman and docker are both present, then docker is returned if
    the environment variable `CONTAINER_RUNTIME` is set to `docker`.

    If neither docker nor podman are available, then a ValueError is raised.
    """
    podman_exists = LOCALHOST.exists("podman") and LOCALHOST.exists("buildah")
    docker_exists = LOCALHOST.exists("docker")

    runtime_choice = getenv("CONTAINER_RUNTIME", "podman").lower()
    if runtime_choice not in ("podman", "docker"):
        raise ValueError(f"Invalid CONTAINER_RUNTIME {runtime_choice}")

    if runtime_choice == "podman" and podman_exists:
        return PodmanRuntime()
    if runtime_choice == "docker" and docker_exists:
        return DockerRuntime()

    raise ValueError(
        "Selected runtime " + runtime_choice + " does not exist on the system"
    )
