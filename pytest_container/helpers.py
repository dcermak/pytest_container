import os

from pytest_container.runtime import DockerRuntime
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime


def get_selected_runtime() -> OciRuntimeBase:
    """Returns the container runtime that the user selected.

    It defaults to podman and selects docker if podman & buildah are not
    present. If podman and docker are both present, then docker is returned if
    the environment variable `CONTAINER_RUNTIME` is set to `docker`.

    If neither docker nor podman are available, then a ValueError is raised.
    """
    podman_exists = LOCALHOST.exists("podman") and LOCALHOST.exists("buildah")
    docker_exists = LOCALHOST.exists("docker")

    runtime_choice = os.getenv("CONTAINER_RUNTIME", "podman").lower()
    if runtime_choice not in ("podman", "docker"):
        raise ValueError(f"Invalid CONTAINER_RUNTIME {runtime_choice}")

    if runtime_choice == "podman" and podman_exists:
        return PodmanRuntime()
    if runtime_choice == "docker" and docker_exists:
        return DockerRuntime()

    raise ValueError(
        "Selected runtime " + runtime_choice + " does not exist on the system"
    )
