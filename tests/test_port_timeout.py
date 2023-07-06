"""Module for testing the
:py:attr:`pytest_container.container.PortForwarding.timeout` property.

"""
from datetime import timedelta


import pytest

from pytest_container.container import ContainerData, ContainerLauncher
from pytest_container.container import DerivedContainer
from pytest_container.inspect import NetworkProtocol
from pytest_container.inspect import PortForwarding
from pytest_container.runtime import OciRuntimeBase
from tests.images import CURL
from tests.images import LEAP


WEB_SERVER_WITHOUT_HEALTHCHECK = DerivedContainer(
    base=LEAP,
    containerfile="""RUN zypper -n in python3 curl && echo "Hello Green World!" > index.html
ENTRYPOINT ["/usr/bin/python3", "-m", "http.server"]
""",
    forwarded_ports=[
        PortForwarding(container_port=8000, timeout=timedelta(seconds=60))
    ],
)


@pytest.mark.parametrize(
    "container", (WEB_SERVER_WITHOUT_HEALTHCHECK,), indirect=True
)
def test_port_timeout(container: ContainerData, host) -> None:
    assert (
        host.run_expect(
            [0],
            f"{CURL} localhost:{container.forwarded_ports[0].host_port}",
        ).stdout.strip()
        == "Hello Green World!"
    )


def test_udp_port_forward_with_timeout() -> None:
    with pytest.raises(ValueError) as val_err_ctx:
        PortForwarding(
            container_port=1,
            protocol=NetworkProtocol.UDP,
            timeout=timedelta(seconds=1),
        )

    assert "Cannot wait for an UDP port" in str(val_err_ctx.value)


def test_container_fails_to_launch_on_unreachable_port(container_runtime: OciRuntimeBase, pytestconfig: pytest.Config, host) -> None:
    container_name = "container_with_exposing_ports"
    with pytest.raises(RuntimeError) as runtime_err_ctx:
        with ContainerLauncher(
                container=DerivedContainer(base=LEAP, forwarded_ports=[PortForwarding(container_port=8080, timeout=timedelta(seconds = 1))]),
            container_runtime=container_runtime,
            rootdir=pytestconfig.rootpath,
            container_name=container_name,
        ) as launcher:
            launcher.launch_container()
            assert False, "This code must be unreachable"

    assert "did not become healthy within" in str(runtime_err_ctx.value)

