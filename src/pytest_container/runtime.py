import enum
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from os import getenv
from subprocess import check_output
from typing import Any
from typing import List
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
        return pytest.param(self, id=self.__str__(), marks=self.marks or ())


@dataclass(frozen=True)
class _OciRuntimeBase:
    #: command that builds the Dockerfile in the current working directory
    build_command: List[str] = field(default_factory=list)
    #: the "main" binary of this runtime, e.g. podman or docker
    runner_binary: str = ""
    _runtime_functional: bool = False


@enum.unique
class ContainerHealth(enum.Enum):
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
        pass

    @abstractmethod
    def get_image_id_from_stdout(self, stdout: str) -> str:
        pass

    @abstractmethod
    def get_container_health(self, container_id: str) -> ContainerHealth:
        """Inspects the running container with the supplied id and returns its current
        health.

        """
        pass


class OciRuntimeBase(_OciRuntimeBase, OciRuntimeABC, ToParamMixin):
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


LOCALHOST = testinfra.host.get_host("local://")


class PodmanRuntime(OciRuntimeBase):

    _runtime_functional = (
        LOCALHOST.run("podman ps").succeeded
        and LOCALHOST.run("buildah").succeeded
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
        elif stdout == "healthy":
            return ContainerHealth.HEALTHY
        elif stdout == "starting":
            return ContainerHealth.STARTING
        return ContainerHealth.UNHEALTHY


class DockerRuntime(OciRuntimeBase):

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
        elif stdout == "starting":
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
