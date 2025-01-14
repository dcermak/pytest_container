"""Module containing tests of the automated port exposure via
:py:attr:`~pytest_container.container.ContainerBase.forwarded_ports`."""

# pylint: disable=missing-function-docstring
import itertools
import socket
from typing import List

import pytest

from pytest_container.container import ContainerData
from pytest_container.container import ContainerLauncher
from pytest_container.container import DerivedContainer
from pytest_container.container import PortForwarding
from pytest_container.container import lock_host_port_search
from pytest_container.inspect import NetworkProtocol
from pytest_container.pod import Pod
from pytest_container.pod import PodLauncher
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import Version

from .images import NGINX_URL
from .images import WEB_SERVER


def _create_nginx_container(number: int) -> DerivedContainer:
    """Creates a nginx based container which serves
    :file:`tests/base/files/index.html` via http and https on ports 80 and 443
    respectively. :file:`index.html` contains the string ``PLACEHOLDER`` that we
    replace with ``Test page $number``, where ``number`` is the parameter of
    this function.

    We also create a self signed certificate authority for this container
    directly inside it so that https works. This is achieved via the script
    :file:`tests/base/files/mk_certs.sh`.

    The Container includes additional 500 TCP and 500 UDP port forwards to
    stress test the random port finder.

    """
    return DerivedContainer(
        base=NGINX_URL,
        containerfile=f"""COPY tests/files/nginx.default.conf /etc/nginx/conf.d/default.conf
COPY tests/files/foobar.crt /root/certs/
COPY tests/files/foobar.key /root/certs/
COPY tests/files/index.html /usr/share/nginx/html/
EXPOSE 80 443
RUN sed -i 's|PLACEHOLDER|Test page {number}|' /usr/share/nginx/html/index.html
""",
        forwarded_ports=[
            PortForwarding(container_port=80),
            PortForwarding(container_port=443),
        ]
        # create an insane number of additional port forwards, that makes it
        # much more likely for any bugs in the host port assignment logic to
        # surface
        + [PortForwarding(container_port=n) for n in range(500, 1000)]
        + [
            PortForwarding(container_port=n, protocol=NetworkProtocol.UDP)
            for n in range(200, 700)
        ],
    )


CONTAINER_IMAGES = [WEB_SERVER]


_curl_version = Version.parse(LOCALHOST.package("curl").version)

#: curl cli with additional retries as a single curl sometimes fails with docker
#: with ``curl: (56) Recv failure: Connection reset by peer`` for reasons…
#: So let's just try again until it works…
_CURL = "curl --retry 5"

# the --retry-all-errors has been added in version 7.71.0:
# https://curl.se/docs/manpage.html#--retry-all-errors
if _curl_version >= Version(major=7, minor=71, patch=0):
    _CURL = f"{_CURL} --retry-all-errors"


@pytest.mark.parametrize(
    "port_forwarding,expected_cli_args",
    [
        (
            PortForwarding(container_port=80, host_port=8080),
            ["-p", "8080:80/tcp"],
        ),
        (
            PortForwarding(
                container_port=80, host_port=8080, bind_ip="127.0.0.1"
            ),
            ["-p", "127.0.0.1:8080:80/tcp"],
        ),
        (
            PortForwarding(container_port=80, host_port=8080, bind_ip="::1"),
            ["-p", "[::1]:8080:80/tcp"],
        ),
        (
            PortForwarding(
                container_port=53, host_port=5053, protocol=NetworkProtocol.UDP
            ),
            ["-p", "5053:53/udp"],
        ),
        (PortForwarding(container_port=6060), ["-p", "6060/tcp"]),
    ],
)
def test_forward_cli_args_with_valid_port(
    port_forwarding: PortForwarding, expected_cli_args: List[str]
) -> None:
    assert port_forwarding.forward_cli_args == expected_cli_args


def test_port_forward_set_up(auto_container: ContainerData, host):
    """Simple smoke test for a single port forward of a Leap based container
    that is serving a file using Python's built in http.server module.

    """
    assert len(auto_container.forwarded_ports) == 1, (
        "exactly one forwarded port must be present"
    )
    assert auto_container.forwarded_ports[0].protocol == NetworkProtocol.TCP, (
        "the default protocol must be tcp"
    )
    assert auto_container.forwarded_ports[0].container_port == 8000, (
        "container port was defined as port 8000"
    )
    assert auto_container.forwarded_ports[0].host_port != -1, (
        "host port must be set"
    )

    assert (
        host.check_output(
            f"{_CURL} localhost:{auto_container.forwarded_ports[0].host_port}",
        ).strip()
        == "Hello Green World!"
    )


@pytest.mark.parametrize(
    "container,number",
    [(_create_nginx_container(i), i) for i in range(10)],
    indirect=["container"],
)
def test_multiple_open_ports(container: ContainerData, number: int, host):
    """Check that multiple containers with two open ports get their port
    forwarding setup correctly.

    For this test we create 10 containers via :py:func:`_create_nginx_container`
    with the ``number`` parameter ranging from 0 to 9. We then check that the
    container's port 80 is reachable and we can use :command:`curl` to fetch
    :file:`index.html` via http. After that we repeat that check for port 443
    via https, however with the added flag ``--insecure`` as we deployed a self
    signed certificate in the container.

    """
    assert len(container.forwarded_ports) == 1002, (
        "exactly 1002 forwarded ports must be present"
    )

    assert (
        container.forwarded_ports[0].protocol == NetworkProtocol.TCP
        and container.forwarded_ports[0].container_port == 80
    )
    assert f"Test page {number}" in host.check_output(
        f"{_CURL} localhost:{container.forwarded_ports[0].host_port}"
    )

    assert (
        container.forwarded_ports[1].protocol == NetworkProtocol.TCP
        and container.forwarded_ports[1].container_port == 443
    )
    assert f"Test page {number}" in host.check_output(
        f"curl --insecure https://localhost:{container.forwarded_ports[1].host_port}",
    )


_INTERFACES = [
    name
    for name in LOCALHOST.interface.names()
    if name[:2] in ("en", "et", "wl")
]
_ADDRESSES = [
    addr
    for addr in itertools.chain.from_iterable(
        LOCALHOST.interface(interface).addresses for interface in _INTERFACES
    )
    if not addr.startswith("169.254.") and not addr.startswith("fe80:")
]


@pytest.mark.parametrize(
    "addr,container",
    zip(
        _ADDRESSES,
        [
            DerivedContainer(
                base=WEB_SERVER,
                forwarded_ports=[
                    PortForwarding(container_port=8000, bind_ip=addr)
                ],
            )
            for addr in _ADDRESSES
        ],
    ),
    indirect=["container"],
)
def test_bind_to_address(addr: str, container: ContainerData, host) -> None:
    """address"""
    for host_addr in _ADDRESSES:
        # need to surround a ipv6 address in [] so that it can be distinguished
        # from a port
        formated_ip = f"[{host_addr}]" if ":" in host_addr else host_addr
        cmd = f"{_CURL} http://{formated_ip}:{container.forwarded_ports[0].host_port}"
        if addr == host_addr:
            assert host.check_output(cmd).strip() == "Hello Green World!"
        else:
            assert host.run_expect([7], cmd)


def test_container_bind_to_host_port(
    container_runtime: OciRuntimeBase, host, pytestconfig: pytest.Config
) -> None:
    with lock_host_port_search(pytestconfig.rootpath):
        with socket.socket(
            family=socket.AF_INET, type=socket.SOCK_STREAM
        ) as sock:
            sock.bind(("", 0))
            PORT = sock.getsockname()[1]

            ctr = DerivedContainer(
                base=WEB_SERVER,
                forwarded_ports=[
                    PortForwarding(container_port=8000, host_port=PORT)
                ],
            )
    with ContainerLauncher(
        container=ctr,
        container_runtime=container_runtime,
        rootdir=pytestconfig.rootpath,
    ) as launcher:
        launcher.launch_container()

        assert launcher.container_data.forwarded_ports[0].host_port == PORT
        assert (
            host.check_output(f"{_CURL} http://localhost:{PORT}").strip()
            == "Hello Green World!"
        )


def test_pod_bind_to_host_port(
    container_runtime: OciRuntimeBase, host, pytestconfig: pytest.Config
) -> None:
    if not container_runtime.runner_binary.endswith("podman"):
        pytest.skip("pods are only supported with podman")

    with lock_host_port_search(pytestconfig.rootpath):
        with socket.socket(
            family=socket.AF_INET, type=socket.SOCK_STREAM
        ) as sock:
            sock.bind(("", 0))
            PORT = sock.getsockname()[1]

            pod = Pod(
                containers=[WEB_SERVER],
                forwarded_ports=[
                    PortForwarding(container_port=8000, host_port=PORT)
                ],
            )

    with PodLauncher.from_pytestconfig(pod, pytestconfig) as launcher:
        launcher.launch_pod()

        assert launcher.pod_data.forwarded_ports[0].host_port == PORT
        assert (
            host.check_output(f"{_CURL} http://localhost:{PORT}").strip()
            == "Hello Green World!"
        )
