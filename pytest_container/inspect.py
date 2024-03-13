"""This module contains the class definitions that represent the output of
:command:`$runtime inspect $ctr_id`.

"""
import enum
import socket
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


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
    :py:attr:`~pytest_container.container.ContainerBase.forwarded_ports` to
    either the :py:class:`pytest_container.container.Container` or
    :py:class:`pytest_container.container.DerivedContainer`:

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

    #: The IP address to which to bind. By default, it will be '::' (all addresses).
    bind_ip: str = ""

    @property
    def forward_cli_args(self) -> List[str]:
        """Returns a list of command line arguments for the container launch
        command to automatically expose this port forwarding.

        """

        if self.bind_ip:
            # If it contains a colon, it must be an IPv6 address and thus must
            # be wrapped in brackets for the launch command
            if ":" in self.bind_ip:
                bind_ip = f"[{self.bind_ip}]:"
            else:
                bind_ip = self.bind_ip + ":"
        else:
            bind_ip = ""

        return [
            "-p",
            bind_ip
            + ("" if self.host_port == -1 else f"{self.host_port}:")
            + f"{self.container_port}/{self.protocol}",
        ]

    def __str__(self) -> str:
        return str(self.forward_cli_args)


class ContainerInspectHealthCheck(TypedDict, total=False):
    """Dictionary created by loading the json output of :command:`podman inspect
    $img_id | jq '.[0]["Healthcheck]` or :command:`docker inspect $img_id | jq
    '.[0]["Config"]["Healthcheck]`.

    """

    Test: List[str]
    Interval: int
    Timeout: int
    StartPeriod: int
    Retries: int


@enum.unique
class ContainerHealth(enum.Enum):
    """Possible states of a container's health using the `HEALTHCHECK
    <https://docs.docker.com/engine/reference/builder/#healthcheck>`_ property
    of a container image.

    """

    #: the container has no health check defined
    NO_HEALTH_CHECK = ""
    #: the container is healthy
    HEALTHY = "healthy"
    #: the health check did not complete yet or did not fail often enough
    STARTING = "starting"
    #: the healthcheck failed
    UNHEALTHY = "unhealthy"


_DEFAULT_START_PERIOD = timedelta(seconds=0)
_DEFAULT_INTERVAL = timedelta(seconds=30)
_DEFAULT_TIMEOUT = timedelta(seconds=30)
_DEFAULT_RETRIES = 3


@dataclass(frozen=True)
class HealthCheck:
    """The HEALTHCHECK of a container image."""

    #: startup period of the container during which healthcheck failures will
    #: not count towards the failure count
    start_period: timedelta = field(default=_DEFAULT_START_PERIOD)

    #: healthcheck command is run every interval
    interval: timedelta = field(default=_DEFAULT_INTERVAL)

    #: timeout of the healthcheck command after which it is considered unsuccessful
    timeout: timedelta = field(default=_DEFAULT_TIMEOUT)

    #: how often the healthcheck command is retried
    retries: int = _DEFAULT_RETRIES

    @property
    def max_wait_time(self) -> timedelta:
        """The maximum time to wait until a container can become healthy"""
        return self.start_period + self.retries * self.interval + self.timeout

    @staticmethod
    def from_container_inspect(
        inspect_json: ContainerInspectHealthCheck,
    ) -> "HealthCheck":
        """Convert the json-loaded output of :command:`podman inspect $ctr` or
        :command:`docker inspect $ctr` into a :py:class:`HealthCheck`.

        """
        return HealthCheck(
            start_period=timedelta(
                microseconds=inspect_json["StartPeriod"] / 1000
            )
            if "StartPeriod" in inspect_json
            else _DEFAULT_START_PERIOD,
            interval=timedelta(microseconds=inspect_json["Interval"] / 1000)
            if "Interval" in inspect_json
            else _DEFAULT_INTERVAL,
            timeout=timedelta(microseconds=inspect_json["Timeout"] / 1000)
            if "Timeout" in inspect_json
            else _DEFAULT_TIMEOUT,
            retries=inspect_json.get("Retries", _DEFAULT_RETRIES),
        )


@dataclass(frozen=True)
class ContainerState:
    #: status of the container, e.g. ``running``, ``stopped``, etc.
    status: str
    #: True if the container is running
    running: bool
    #: True if the container has been paused
    paused: bool
    #: True if the container is restarting
    restarting: bool
    #: True if the container is has been killed by a Out Of Memory condition
    oom_killed: bool
    #: True if the container is dead
    dead: bool
    #: process id of the main container process
    pid: int
    #: status of the last health check run for this container image
    health: ContainerHealth = ContainerHealth.NO_HEALTH_CHECK


@dataclass(frozen=True)
class Config:
    #: User defined in the container image
    user: str

    #: true if this container has a TTY attached
    tty: bool

    #: command defined in this container
    cmd: List[str]

    #: the entrypoint of this container
    entrypoint: List[str]

    #: environment variables set in the container image
    env: Dict[str, str]

    #: name of image used to launch this container
    image: str

    #: labels of the container
    labels: Dict[str, str]

    #: Signal that will be sent to the container when it is stopped. If the
    #: container does not terminate, ``SIGKILL`` will be used afterwards.
    #:
    stop_signal: Union[int, str]

    #: optional healthcheck defined for the underlying container image
    healthcheck: Optional[HealthCheck] = None


@dataclass(frozen=True)
class ContainerNetworkSettings:
    """Network specific settings of a container."""

    #: list of ports forwarded from the container to the host
    ports: List[PortForwarding] = field(default_factory=list)

    #: IP Address of the container, if it has one
    ip_address: Optional[str] = None


@dataclass(frozen=True)
class Mount:
    """Base class for mount points"""

    #: source folder on the host (if present)
    source: str

    #: mount point in the container
    destination: str

    #: is this mount read-write?
    rw: bool


@dataclass(frozen=True)
class BindMount(Mount):
    """A bind mounted directory"""


@dataclass(frozen=True)
class VolumeMount(Mount):
    """A volume mount"""

    #: name/hash of this volume
    name: str

    #: driver that is backing this volume
    driver: str


@dataclass(frozen=True)
class ContainerInspect:
    """Common subset of the information exposed via :command:`podman inspect`
    and :command:`docker inspect`.

    """

    #: The container's ID
    id: str

    #: the container's name
    name: str

    #: program that has been launched inside the container
    path: str

    #: arguments passed to :py:attr:`path`
    args: List[str]

    #: current state of the container
    state: ContainerState

    #: hash digest of the image
    image_hash: str

    #: general configuration of the container (mostly inherited from the used image)
    config: Config

    #: Current network settings of this container
    network: ContainerNetworkSettings

    #: volumes or bind mounts mounted in this container
    mounts: List[Union[BindMount, VolumeMount]]
