"""Module for managing podman pods."""
import contextlib
import json
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from subprocess import check_output
from types import TracebackType
from typing import List
from typing import Optional
from typing import Type
from typing import Union

from _pytest.mark import ParameterSet
from pytest_container.container import Container
from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import create_host_port_port_forward
from pytest_container.container import DerivedContainer
from pytest_container.container import lock_host_port_search
from pytest_container.inspect import PortForwarding
from pytest_container.logging import _logger
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import PodmanRuntime


@dataclass
class Pod:
    """A pod is a collection of containers that share the same network and port
    forwards. Currently only :command:`podman` supports creating pods.

    **Caution**: port forwards of the individual containers are ignored and only
    the port forwards in the pod class are taken into account!

    """

    #: containers belonging to the pod
    containers: List[Union[DerivedContainer, Container]]

    #: ports exposed by the pod
    forwarded_ports: List[PortForwarding] = field(default_factory=list)


@dataclass(frozen=True)
class PodData:
    """Class that is returned by the ``pod`` and ``pod_per_test`` fixtures. It
    contains all necessary information about the created pod and the containers
    running inside it.

    """

    #: The actual pod that has been launched
    pod: Pod

    #: The :py:class:`~pytest_container.container.ContainerData` instances of
    #: each container in the pod.
    container_data: List[ContainerData]

    #: unique id/hash of the running pod
    pod_id: str

    #: unique id/hash of the infra container of the pod
    infra_container_id: str

    #: ports exposed by this pod
    forwarded_ports: List[PortForwarding]


@dataclass
class PodLauncher:
    """A context manager that creates, starts and destroys a pod with all of its
    containers.

    """

    #: the pod that should be created and launched including all of its
    #: containers
    pod: Pod

    #: root directory of the pytest testsuite
    rootdir: Path

    #: optional name of the pod
    pod_name: str = ""

    #: additional arguments to pass to the container build commands
    extra_build_args: List[str] = field(default_factory=list)

    #: additional arguments to pass to the container run commands
    extra_run_args: List[str] = field(default_factory=list)

    #: additional arguments to pass to the ``pod create`` command
    extra_pod_create_args: List[str] = field(default_factory=list)

    _launchers: List[ContainerLauncher] = field(default_factory=list)
    _new_port_forwards: List[PortForwarding] = field(default_factory=list)

    #: id of the pod
    _pod_id: Optional[str] = None

    #: id of the infra pod
    _infra_container_id: Optional[str] = None

    _stack: contextlib.ExitStack = field(default_factory=contextlib.ExitStack)

    def __enter__(self) -> "PodLauncher":
        runtime = get_selected_runtime()
        if runtime != PodmanRuntime():
            raise RuntimeError(
                f"pods can only be created with podman, but got {runtime}"
            )
        return self

    def launch_pod(self) -> None:
        """Creates the actual pod, establishes the port bindings and launches
        all containers in the pod.

        """
        runtime = get_selected_runtime()
        create_cmd = [runtime.runner_binary, "pod", "create"] + (
            ["--name", self.pod_name] if self.pod_name else []
        )

        if self.pod.forwarded_ports:
            with lock_host_port_search(self.rootdir):
                self._new_port_forwards = create_host_port_port_forward(
                    self.pod.forwarded_ports
                )
                # port_forward_args = []
                for new_forward in self._new_port_forwards:
                    create_cmd += new_forward.forward_cli_args

                _logger.debug("Creating pod via: %s", create_cmd)
                self._pod_id = check_output(create_cmd).decode().strip()
        else:
            _logger.debug("Creating pod via: %s", create_cmd)
            self._pod_id = check_output(create_cmd).decode().strip()

        def _delete_pod() -> None:
            if self._pod_id:
                _logger.debug("Removing pod %s", self._pod_id)
                check_output(
                    [runtime.runner_binary, "pod", "rm", "-f", self._pod_id]
                )
            else:
                _logger.debug("Not removing pod, not created")

        self._stack.callback(_delete_pod)

        # we don't want to directly query the infra container id via
        # podman pod inspect -f "{{.InfraContainerID}}"
        # as that doesn't work on ancient podman versions
        # But both new and old podman versions have the Containers field with
        # (at this stage), just the infra container.
        # So we just grab the id from the full inspect
        pod_inspect = json.loads(
            check_output(
                [
                    runtime.runner_binary,
                    "pod",
                    "inspect",
                    self._pod_id,
                ]
            )
            .decode()
            .strip()
        )
        infra_container = pod_inspect["Containers"][0]
        # old podman had the id of the containers with lowercase, new podman has
        # uppercase => have to check for both :-(
        self._infra_container_id = infra_container.get(
            "Id", infra_container.get("id")
        )

        for container in self.pod.containers:
            self._launchers.append(
                self._stack.enter_context(
                    ContainerLauncher(
                        container=container,
                        container_runtime=runtime,
                        rootdir=self.rootdir,
                        extra_build_args=self.extra_build_args,
                        extra_run_args=(
                            ["--pod", self._pod_id] + self.extra_run_args
                        ),
                        _expose_ports=False,
                    )
                )
            )
            self._launchers[-1].launch_container()

        assert len(self.pod.containers) == len(self._launchers)

    def __exit__(
        self,
        __exc_type: Optional[Type[BaseException]],
        __exc_value: Optional[BaseException],
        __traceback: Optional[TracebackType],
    ) -> None:
        self._stack.close()
        self._pod_id = None
        self._infra_container_id = None

    @property
    def pod_data(self) -> PodData:
        """Returns the :py:class:`PodData` corresponding to this podman pod."""
        if not self._pod_id or not self._infra_container_id:
            raise RuntimeError("Pod has not been created")

        return PodData(
            pod=self.pod,
            container_data=[
                launcher.container_data for launcher in self._launchers
            ],
            pod_id=self._pod_id,
            infra_container_id=self._infra_container_id,
            forwarded_ports=self._new_port_forwards,
        )


def pod_from_pytest_param(param: Union[ParameterSet, Pod]) -> Pod:
    """Extracts the :py:class:`~pytest_container.pod.Pod` from a `pytest.param
    <https://docs.pytest.org/en/stable/reference.html?#pytest.param>`_ or just
    returns the value directly, if it is a
    :py:class:`~pytest_container.pod.Pod`.

    """
    if isinstance(param, Pod):
        return param

    if len(param.values) > 0 and isinstance(param.values[0], Pod):
        return param.values[0]

    raise ValueError(f"Invalid pytest.param values: {param.values}")
