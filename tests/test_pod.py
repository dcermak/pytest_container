# pylint: disable=missing-function-docstring,missing-module-docstring,line-too-long,trailing-whitespace
from pathlib import Path

import pytest

from pytest_container.container import DerivedContainer
from pytest_container.container import ImageFormat
from pytest_container.container import PortForwarding
from pytest_container.pod import Pod
from pytest_container.pod import PodData
from pytest_container.pod import PodLauncher
from pytest_container.pod import infra_container_id_from_pod_inspect
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime

from .images import BUSYBOX
from .images import CONTAINER_THAT_FAILS_TO_LAUNCH
from .images import LEAP
from .images import LEAP_WITH_MAN
from .images import NGINX_URL
from .images import TEST_POD
from .images import WEB_SERVER

TEST_POD_WITHOUT_PORTS = Pod(containers=[LEAP, LEAP_WITH_MAN, BUSYBOX])


NGINX_PROXY = DerivedContainer(
    base=NGINX_URL,
    containerfile=r"""COPY tests/files/nginx.conf /etc/nginx/nginx.conf
RUN set -eu; zypper -n ref; zypper -n in netcat; zypper -n clean; rm -rf /var/log/{zypp,zypper.log,lastlog}

HEALTHCHECK --interval=5s --timeout=1s CMD echo "GET /" | nc localhost 80
""",
    image_format=ImageFormat.DOCKER,
)

PROXY_POD = Pod(
    containers=[WEB_SERVER, NGINX_PROXY],
    forwarded_ports=[PortForwarding(container_port=80)],
)


def test_pod_launcher(
    tmp_path: Path,
    container_runtime: OciRuntimeBase,
    pytestconfig: pytest.Config,
) -> None:
    if container_runtime != PodmanRuntime():
        pytest.skip("pods only work with podman")

    pidfile_path = str(tmp_path / "pidfile")
    with PodLauncher(
        pod=TEST_POD,
        rootdir=pytestconfig.rootpath,
        extra_pod_create_args=["--pod-id-file", pidfile_path],
    ) as launcher:
        launcher.launch_pod()
        pod_data = launcher.pod_data
        assert pod_data.pod_id and pod_data.infra_container_id

        with open(pidfile_path, encoding="utf-8") as pyproject:
            assert pod_data.pod_id == pyproject.read()

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

    with PodLauncher.from_pytestconfig(
        pod=TEST_POD, pytestconfig=pytestconfig
    ) as launcher:
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
        with PodLauncher.from_pytestconfig(
            pod=Pod(containers=[LEAP, CONTAINER_THAT_FAILS_TO_LAUNCH]),
            pytestconfig=pytestconfig,
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
        with PodLauncher(pod=TEST_POD, rootdir=Path("/tmp")) as _:
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
            f"curl --fail http://0.0.0.0:{pod_per_test.forwarded_ports[0].host_port}",
        ).stdout
    )


@pytest.mark.parametrize(
    "pod", [TEST_POD, TEST_POD_WITHOUT_PORTS], indirect=True
)
def test_pod_fixture(pod: PodData) -> None:
    assert pod.pod_id

    for cont_data in pod.container_data:
        # leap has /etc/os-release
        if cont_data.connection.file("/etc/os-release").exists:
            assert (
                "leap"
                in cont_data.connection.run_expect([0], "cat /etc/os-release")
                .stdout.strip()
                .lower()
            )
        # busybox doesn't, but it has /bin/busybox ;-)
        else:
            assert cont_data.connection.file("/bin/busybox").exists


def test_launcher_pod_data_uninitialized() -> None:
    with pytest.raises(RuntimeError) as rt_ctx:
        _ = PodLauncher(TEST_POD, Path("/")).pod_data

    assert "Pod has not been created" in str(rt_ctx.value)


@pytest.mark.parametrize(
    "inspect_output, expected_id",
    (
        # podman 1.6.4 (CentOS 7)
        (
            """{
     "Config": {
          "id": "2df19026a989667f0c9956723a45b25ccd32c0efaec19d375727d37622709040",
          "name": "happy_beaver",
          "hostname": "happy_beaver",
          "labels": {
"""
            # This whitespace is present in the output and should stay there,
            # but ruff complains about it then if it's a single multiline
            # string. But if we split it up, everything is fine ¯\_(ツ)_/¯
            + "               "
            + """
          },
          "cgroupParent": "machine.slice",
          "sharesCgroup": true,
          "sharesIpc": true,
          "sharesNet": true,
          "sharesUts": true,
          "infraConfig": {
               "makeInfraContainer": true,
               "infraPortBindings": null
          },
          "created": "2024-04-09T12:56:00.106588707Z",
          "lockID": 0
     },
     "State": {
          "cgroupPath": "machine.slice/machine-libpod_pod_2df19026a989667f0c9956723a45b25ccd32c0efaec19d375727d37622709040.slice",
          "infraContainerID": "9c77fc16ce2cd7b7b648ac161596b8e2c4b66e6b388b1262de402bb76b2563a4"
     },
     "Containers": [
          {
               "id": "9c77fc16ce2cd7b7b648ac161596b8e2c4b66e6b388b1262de402bb76b2563a4",
               "state": "configured"
          }
     ]
}
""",
            "9c77fc16ce2cd7b7b648ac161596b8e2c4b66e6b388b1262de402bb76b2563a4",
        ),
        # podman < 5
        (
            """{
     "Id": "759b48e641608d2dc8ecef44084d4671b9d127e4f39d9cdfa9c9bb326cfe64f0",
     "Name": "git",
     "Created": "2024-04-09T14:34:44.307240325+02:00",
     "CreateCommand": [
          "podman",
          "pod",
          "create",
          "git"
     ],
     "ExitPolicy": "continue",
     "State": "Created",
     "Hostname": "",
     "CreateCgroup": true,
     "CgroupParent": "user.slice",
     "CgroupPath": "user.slice/user-1000.slice/user@1000.service/user.slice/user-libpod_pod_759b48e641608d2dc8ecef44084d4671b9d127e4f39d9cdfa9c9bb326cfe64f0.slice",
     "CreateInfra": true,
     "InfraContainerID": "b4541110f6c7f06aec932b1e5381682df306d52b6eb080d44aa09c2865469584",
     "InfraConfig": {
          "PortBindings": {},
          "HostNetwork": false,
          "StaticIP": "",
          "StaticMAC": "",
          "NoManageResolvConf": false,
          "DNSServer": null,
          "DNSSearch": null,
          "DNSOption": null,
          "NoManageHosts": false,
          "HostAdd": null,
          "Networks": null,
          "NetworkOptions": null,
          "pid_ns": "private",
          "userns": "host",
          "uts_ns": "private"
     },
     "SharedNamespaces": [
          "ipc",
          "net",
          "uts"
     ],
     "NumContainers": 1,
     "Containers": [
          {
               "Id": "b4541110f6c7f06aec932b1e5381682df306d52b6eb080d44aa09c2865469584",
               "Name": "759b48e64160-infra",
               "State": "created"
          }
     ],
     "LockNumber": 0
}
""",
            "b4541110f6c7f06aec932b1e5381682df306d52b6eb080d44aa09c2865469584",
        ),  # podman > 5
        (
            """[
     {
          "Id": "759b48e641608d2dc8ecef44084d4671b9d127e4f39d9cdfa9c9bb326cfe64f0",
          "Name": "git",
          "Created": "2024-04-09T14:34:44.307240325+02:00",
          "CreateCommand": [
               "podman",
               "pod",
               "create",
               "git"
          ],
          "ExitPolicy": "continue",
          "State": "Created",
          "Hostname": "",
          "CreateCgroup": true,
          "CgroupParent": "user.slice",
          "CgroupPath": "user.slice/user-1000.slice/user@1000.service/user.slice/user-libpod_pod_759b48e641608d2dc8ecef44084d4671b9d127e4f39d9cdfa9c9bb326cfe64f0.slice",
          "CreateInfra": true,
          "InfraContainerID": "b4541110f6c7f06aec932b1e5381682df306d52b6eb080d44aa09c2865469584",
          "InfraConfig": {
               "PortBindings": {},
               "HostNetwork": false,
               "StaticIP": "",
               "StaticMAC": "",
               "NoManageResolvConf": false,
               "DNSServer": null,
               "DNSSearch": null,
               "DNSOption": null,
               "NoManageHosts": false,
               "HostAdd": null,
               "Networks": null,
               "NetworkOptions": null,
               "pid_ns": "private",
               "userns": "host",
               "uts_ns": "private"
          },
          "SharedNamespaces": [
               "net",
               "uts",
               "ipc"
          ],
          "NumContainers": 1,
          "Containers": [
               {
                    "Id": "b4541110f6c7f06aec932b1e5381682df306d52b6eb080d44aa09c2865469584",
                    "Name": "759b48e64160-infra",
                    "State": "created"
               }
          ],
          "LockNumber": 0
     }
]
""",
            "b4541110f6c7f06aec932b1e5381682df306d52b6eb080d44aa09c2865469584",
        ),
    ),
)
def test_get_infra_container_id(inspect_output: str, expected_id: str) -> None:
    assert (
        infra_container_id_from_pod_inspect(inspect_output.encode())
        == expected_id
    )
