# pylint: disable=missing-function-docstring,missing-module-docstring
from pathlib import Path

import pytest

from .images import ALPINE
from .images import CONTAINER_THAT_FAILS_TO_LAUNCH
from .images import LEAP
from .images import LEAP_WITH_MAN
from .images import NGINX_URL
from .images import TEST_POD
from .images import WEB_SERVER
from pytest_container.container import DerivedContainer
from pytest_container.container import PortForwarding
from pytest_container.pod import Pod
from pytest_container.pod import PodData
from pytest_container.pod import PodLauncher
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime


TEST_POD_WITHOUT_PORTS = Pod(containers=[LEAP, LEAP_WITH_MAN, ALPINE])


NGINX_PROXY = DerivedContainer(
    base=NGINX_URL,
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
        launcher.launch_pod()
        pod_data = launcher.pod_data
        assert pod_data.pod_id and pod_data.infra_container_id

        assert (
            len(pod_data.forwarded_ports) == 2
            and pod_data.forwarded_ports[0].container_port == 80
            and pod_data.forwarded_ports[1].container_port == 22
        )
        assert (
            len(pod_data.pod.containers) == 3
            and len(pod_data.container_data) == 3
        )


def test_pod_launcher_pod_data_not_ready(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    if container_runtime != PodmanRuntime():
        pytest.skip("pods only work with podman")

    with PodLauncher(pod=TEST_POD, rootdir=pytestconfig.rootpath) as launcher:
        with pytest.raises(RuntimeError) as rt_err_ctx:
            _ = launcher.pod_data

        assert "Pod has not been created" in str(rt_err_ctx.value)

        launcher.launch_pod()
        assert launcher.pod_data


def test_pod_launcher_cleanup(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config, host
) -> None:
    if container_runtime != PodmanRuntime():
        pytest.skip("pods only work with podman")

    name = "i_will_fail_to_launch"

    with pytest.raises(RuntimeError) as rt_err_ctx:
        with PodLauncher(
            pod=Pod(containers=[LEAP, CONTAINER_THAT_FAILS_TO_LAUNCH]),
            rootdir=pytestconfig.rootpath,
            pod_name=name,
        ) as launcher:
            launcher.launch_pod()
            assert False, "This code must be unreachable"

    assert "did not become healthy" in str(rt_err_ctx.value)

    # the pod should be gone
    assert (
        name
        in host.run_expect([125], f"podman pod inspect {name}").stderr.strip()
    )


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
        _ = PodLauncher(TEST_POD, Path("/")).pod_data

    assert "Pod has not been created" in str(rt_ctx.value)
