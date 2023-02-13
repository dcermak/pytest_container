# pylint: disable=missing-function-docstring,missing-module-docstring
import json
from pathlib import Path

import pytest

from . import images
from pytest_container.container import Container
from pytest_container.container import DerivedContainer
from pytest_container.container import PortForwarding
from pytest_container.pod import Pod
from pytest_container.pod import PodData
from pytest_container.pod import PodLauncher
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime
from tests.test_container_build import LEAP
from tests.test_container_build import LEAP_WITH_MAN
from tests.test_launcher import CONTAINER_THAT_FAILS_TO_LAUNCH
from tests.test_port_forwarding import WEB_SERVER

ALPINE = Container(
    url=images.ALPINE, custom_entry_point="/bin/sh"
)

TEST_POD = Pod(
    containers=[LEAP, LEAP_WITH_MAN, ALPINE],
    forwarded_ports=[PortForwarding(80), PortForwarding(22)],
)

TEST_POD_WITHOUT_PORTS = Pod(containers=[LEAP, LEAP_WITH_MAN, ALPINE])


NGINX_PROXY = DerivedContainer(
    base="docker.io/library/nginx",
    containerfile=r"""RUN echo 'server { \n\
    listen 80; \n\
    server_name  localhost; \n\
    location / { \n\
        proxy_pass http://localhost:8000/; \n\
    } \n\
}' > /etc/nginx/conf.d/default.conf

HEALTHCHECK --interval=5s --timeout=1s CMD curl --fail http://localhost:80
""",
    default_entry_point=True,
)

PROXY_POD = Pod(
    containers=[WEB_SERVER, NGINX_PROXY],
    forwarded_ports=[PortForwarding(container_port=80)],
)


def test_pod_launcher(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    if container_runtime != PodmanRuntime():
        pytest.skip("pods only work with podman")

    with PodLauncher(pod=TEST_POD, rootdir=pytestconfig.rootpath) as launcher:
        pod_data = launcher.pod_data
        assert pod_data.pod_id and pod_data.infra_container_id

        assert (
            len(pod_data.forwarded_ports) == 2
            and pod_data.forwarded_ports[0].container_port == 80
            and pod_data.forwarded_ports[1].container_port == 22
        )
        assert (
            len(pod_data.containers) == 3 and len(pod_data.container_data) == 3
        )


def test_pod_launcher_cleanup(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config, host
) -> None:
    if container_runtime != PodmanRuntime():
        pytest.skip("pods only work with podman")

    name = "i_will_fail_to_launch"
    launcher = PodLauncher(
        pod=Pod(containers=[LEAP, CONTAINER_THAT_FAILS_TO_LAUNCH]),
        rootdir=pytestconfig.rootpath,
        pod_name=name,
    )

    with pytest.raises(RuntimeError) as rt_err_ctx:
        launcher.__enter__()

    assert "did not become healthy" in str(rt_err_ctx.value)

    # the pod is still there as __exit__() did not run
    pod_inspect = json.loads(
        host.run_expect([0], f"podman pod inspect {name}").stdout.strip()
    )
    assert name == pod_inspect["Name"]
    assert len(pod_inspect["Containers"]) == 3

    launcher.__exit__(None, None, None)

    # now the pod should be gone
    assert (
        name
        in host.run_expect([125], f"podman pod inspect {name}").stderr.strip()
    )

    # all containers in it should be gone as well
    for cont in pod_inspect["Containers"]:
        stderr = host.run_expect(
            [125], f"podman inspect {cont['Id']}"
        ).stderr.strip()
        assert cont["Id"] in stderr


def test_pod_launcher_fails_with_non_podman(
    container_runtime: OciRuntimeBase,
) -> None:
    if container_runtime == PodmanRuntime():
        pytest.skip("pods work with podman")

    with pytest.raises(RuntimeError) as rt_err_ctx:
        with PodLauncher(pod=TEST_POD, rootdir=Path("/")) as _:
            pass

    assert "pods can only be created with podman" in str(rt_err_ctx.value)


@pytest.mark.parametrize("pod_per_test", [PROXY_POD], indirect=True)
def test_proxy_pod(pod_per_test: PodData, host) -> None:
    assert (
        pod_per_test.forwarded_ports and len(pod_per_test.forwarded_ports) == 1
    )
    assert host.socket(
        f"tcp://0.0.0.0:{pod_per_test.forwarded_ports[0].host_port}"
    ).is_listening

    assert (
        "Hello Green World"
        in host.run_expect(
            [0],
            f"curl --fail http://localhost:{pod_per_test.forwarded_ports[0].host_port}",
        ).stdout
    )


@pytest.mark.parametrize(
    "pod", [TEST_POD, TEST_POD_WITHOUT_PORTS], indirect=True
)
def test_pod_fixture(pod: PodData) -> None:
    assert pod.pod_id

    for cont_data in pod.container_data[:2]:
        assert (
            "leap"
            in cont_data.connection.run_expect([0], "cat /etc/os-release")
            .stdout.strip()
            .lower()
        )

    assert (
        "alpine"
        in pod.container_data[-1]
        .connection.run_expect([0], "cat /etc/os-release")
        .stdout.strip()
        .lower()
    )


def test_launcher_pod_data_uninitialized() -> None:
    with pytest.raises(RuntimeError) as rt_ctx:
        PodLauncher(TEST_POD, Path("/")).pod_data

    assert "Pod has not been created" in str(rt_ctx.value)
