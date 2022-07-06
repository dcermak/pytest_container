"""Module containing tests of the automated port exposure via
:py:attr:`~pytest_container.container.ContainerBase.forwarded_ports`."""
import socket
from contextlib import closing
from pytest_container.container import ContainerData
from pytest_container.container import DerivedContainer
from pytest_container.container import is_socket_listening_on_localhost
from pytest_container.container import NetworkProtocol
from pytest_container.container import PortForwarding
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import Version

import pytest

from tests.base.test_container_build import LEAP


WEB_SERVER = DerivedContainer(
    base=LEAP,
    containerfile="""
RUN zypper -n in python3 && echo "Hello Green World!" > index.html
ENTRYPOINT ["/usr/bin/python3", "-m", "http.server"]
EXPOSE 8000
""",
    forwarded_ports=[PortForwarding(container_port=8000)],
    default_entry_point=True,
)


def _create_nginx_container(number: int) -> DerivedContainer:
    """Creates a nginx based container which serves
    :file:`tests/base/files/index.html` via http and https on ports 80 and 443
    respectively. :file:`index.html` contains the string ``PLACEHOLDER`` that we
    replace with ``Test page $number``, where ``number`` is the parameter of
    this function.

    We also create a self signed certificate authority for this container
    directly inside it so that https works. This is achieved via the script
    :file:`tests/base/files/mk_certs.sh`.

    """
    return DerivedContainer(
        base="docker.io/library/nginx:latest",
        containerfile=f"""COPY tests/base/files/nginx.default.conf /etc/nginx/conf.d/default.conf
COPY tests/base/files/mk_certs.sh /bin/mk_certs.sh
COPY tests/base/files/index.html /usr/share/nginx/html/
RUN mkdir -p /root/certs/ && cd /root/certs && mk_certs.sh foobar
EXPOSE 80 443
RUN sed -i 's|PLACEHOLDER|Test page {number}|' /usr/share/nginx/html/index.html
""",
        forwarded_ports=[
            PortForwarding(container_port=80),
            PortForwarding(container_port=443),
        ],
        default_entry_point=True,
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


def test_forward_cli_args_with_valid_port():
    assert PortForwarding(
        container_port=80, host_port=8080
    ).forward_cli_args == ["-p", "8080:80/tcp"]
    assert PortForwarding(
        container_port=53, host_port=5053, protocol=NetworkProtocol.UDP
    ).forward_cli_args == ["-p", "5053:53/udp"]


def test_port_forward_set_up(auto_container: ContainerData, host):
    """Simple smoke test for a single port forward of a Leap based container
    that is serving a file using Python's built in http.server module.

    """
    assert (
        len(auto_container.forwarded_ports) == 1
    ), "exactly one forwarded port must be present"
    assert (
        auto_container.forwarded_ports[0].protocol == NetworkProtocol.TCP
    ), "the default protocol must be tcp"
    assert (
        auto_container.forwarded_ports[0].container_port == 8000
    ), "container port was defined as port 8000"
    assert (
        auto_container.forwarded_ports[0].host_port != -1
    ), "host port must be set"

    assert (
        host.run_expect(
            [0],
            f"{_CURL} localhost:{auto_container.forwarded_ports[0].host_port}",
        ).stdout.strip()
        == "Hello Green World!"
    )


def test_is_tcp_port_open():
    """Test for
    :py:func:`~pytest_container.container.is_socket_listening_on_localhost`:
    opens a TCP socket on port 5555 on localhost and verify that the socket is
    reported as occupied. Afterwards the socket is closed and we check that it
    is reported as closed.

    """
    port_to_check = 5555

    assert not is_socket_listening_on_localhost(
        port_to_check, NetworkProtocol.TCP
    ), f"{port_to_check} must be closed for this test"

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", port_to_check))
        sock.listen()

        assert is_socket_listening_on_localhost(
            port_to_check, NetworkProtocol.TCP
        ), f"{port_to_check} must be open"

    assert not is_socket_listening_on_localhost(
        port_to_check, NetworkProtocol.TCP
    ), f"{port_to_check} must be closed"


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
    assert (
        len(container.forwarded_ports) == 2
    ), "exactly two forwarded ports must be present"

    assert (
        container.forwarded_ports[0].protocol == NetworkProtocol.TCP
        and container.forwarded_ports[0].container_port == 80
    )
    assert (
        f"Test page {number}"
        in host.run_expect(
            [0], f"{_CURL} localhost:{container.forwarded_ports[0].host_port}"
        ).stdout
    )

    assert (
        container.forwarded_ports[1].protocol == NetworkProtocol.TCP
        and container.forwarded_ports[1].container_port == 443
    )
    assert (
        f"Test page {number}"
        in host.run_expect(
            [0],
            f"curl --insecure https://localhost:{container.forwarded_ports[1].host_port}",
        ).stdout
    )
