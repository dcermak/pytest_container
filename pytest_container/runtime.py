from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from os import getenv
from os import path
from subprocess import check_output
from typing import Any
from typing import List
from typing import Optional

import pytest
import testinfra


@dataclass(frozen=True)
class ToParamMixin:
    """
    Mixin class that gives child classes the ability to convert themselves into
    a pytest.param with self.__str__() as the default id and optional marks
    """

    marks: Any = None

    def to_pytest_param(self):
        return pytest.param(self, id=self.__str__(), marks=self.marks or ())


@dataclass(frozen=True)
class OciRuntimeBase(ABC, ToParamMixin):
    #: command that builds the Dockerfile in the current working directory
    build_command: List[str] = field(default_factory=list)
    #: the "main" binary of this runtime, e.g. podman or docker
    runner_binary: str = ""
    _runtime_functional: bool = False

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

    @staticmethod
    @abstractmethod
    def _runtime_error_message() -> str:
        pass

    @abstractmethod
    def get_image_id_from_stdout(self, stdout: str) -> str:
        pass

    def get_image_size(self, image_or_id: str) -> float:
        return float(
            check_output(
                [
                    self.runner_binary,
                    "inspect",
                    "-f",
                    '"{{ .Size }}"',
                    image_or_id,
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
            return podman_ps.stderr
        buildah = LOCALHOST.run("buildah")
        assert (
            not buildah.succeeded
        ), "buildah command must not succeed as PodmanRuntime is not functional"
        return buildah.stderr

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
        return docker_ps.stderr

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


@dataclass(frozen=True)
class GitRepositoryBuild(ToParamMixin):
    """Test information storage for running builds using an external git
    repository. It is a required parameter for the `container_git_clone` and
    `host_git_clone` fixtures.
    """

    #: url of the git repository, can end with .git
    repository_url: str = ""
    #: an optional tag at which the repository should be checked out instead of
    #: using the default branch
    repository_tag: Optional[str] = None

    #: The command to run a "build" of the git repository inside a working
    #: copy.
    #: It can be left empty on purpose.
    build_command: str = ""

    def __post_init__(self) -> None:
        if not self.repository_url:
            raise ValueError("A repository url must be provided")

    def __str__(self) -> str:
        return self.repo_name

    @property
    def repo_name(self) -> str:
        """Name of the directory to which the repository will be checked out"""
        return path.basename(self.repository_url.replace(".git", ""))

    @property
    def clone_command(self) -> str:
        """Command to clone the repository at the appropriate tag"""
        clone_cmd_parts = ["git clone --depth 1"]
        if self.repository_tag:
            clone_cmd_parts.append(f"--branch {self.repository_tag}")
        clone_cmd_parts.append(self.repository_url)

        return " ".join(clone_cmd_parts)

    @property
    def test_command(self) -> str:
        """The full test command, including build_command and a cd into the
        correct folder.
        """
        cd_cmd = f"cd {self.repo_name}"
        if self.build_command:
            return f"{cd_cmd} && {self.build_command}"
        return cd_cmd
