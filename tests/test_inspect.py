# pylint: disable=missing-function-docstring,missing-module-docstring,line-too-long
import json
from pathlib import Path
from typing import List

import pytest

from pytest_container import DerivedContainer
from pytest_container.container import ContainerData
from pytest_container.inspect import VolumeMount
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime

from .test_container_build import LEAP

_CTR_NAME = "foobar-12345"

IMAGE_WITH_EVERYTHING = DerivedContainer(
    singleton=True,
    extra_launch_args=["--name", _CTR_NAME],
    base=LEAP,
    containerfile="""VOLUME /src/
EXPOSE 8080 666
RUN useradd opensuse
USER opensuse
ENTRYPOINT ["/bin/bash", "-e"]
ENV HOME=/src/
WORKDIR /foobar/
ENV MY_VAR=
ENV SUFFIX_NAME=dc=example,dc=com
CMD ["/bin/sh"]
""",
)

IMAGE_WITH_STRING_CMD_AND_ENTRYPOINT = DerivedContainer(
    base=LEAP,
    containerfile="""
ENTRYPOINT /bin/bash
CMD /bin/sh
""",
)


@pytest.mark.parametrize(
    "container_per_test", [IMAGE_WITH_EVERYTHING], indirect=True
)
def test_inspect(
    container_per_test: ContainerData, container_runtime: OciRuntimeBase, host
) -> None:
    inspect = container_per_test.inspect

    assert inspect.id == container_per_test.container_id
    assert inspect.name == _CTR_NAME
    assert inspect.config.user == "opensuse"
    assert inspect.config.entrypoint == ["/bin/bash", "-e"]

    assert (
        "HOME" in inspect.config.env and inspect.config.env["HOME"] == "/src/"
    )

    # podman and docker cannot agree on what the Config.Image value is: podman
    # prefixes it with `localhost` and the full build tag
    # (i.e. `pytest_container:$digest`), while docker just uses the digest
    expected_img = (
        str(container_per_test.container)
        if container_runtime.runner_binary == "docker"
        else f"localhost/pytest_container:{container_per_test.container}"
    )

    assert inspect.config.image == expected_img
    assert inspect.config.cmd == ["/bin/sh"]
    assert Path("/foobar/") == inspect.config.workingdir

    assert (
        not inspect.state.paused
        and not inspect.state.dead
        and not inspect.state.oom_killed
        and not inspect.state.restarting
    )

    assert (
        len(inspect.mounts) == 1
        and isinstance(inspect.mounts[0], VolumeMount)
        and inspect.mounts[0].destination == "/src"
    )

    assert inspect.network.ip_address or "" == host.check_output(
        f"{container_runtime.runner_binary} inspect --format "
        '"{{ .NetworkSettings.IPAddress }}" ' + _CTR_NAME
    )


@pytest.mark.parametrize("container", [LEAP], indirect=True)
def test_inspect_unset_workdir(container: ContainerData) -> None:
    """If the container has no workdir set, check that it defaults to ``/`` as
    docker sometimes omits the workingdir setting.

    """
    assert container.inspect.config.workingdir == Path("/")


@pytest.mark.parametrize(
    "container", [IMAGE_WITH_STRING_CMD_AND_ENTRYPOINT], indirect=True
)
def test_cmd_entrypoint_parsing(container: ContainerData) -> None:
    # if only a string is added as CMD or ENTRYPOINT, then it is passed to
    # `/bin/sh -c`, hence the additional two list entries
    assert container.inspect.config.cmd == ["/bin/sh", "-c", "/bin/sh"]
    assert container.inspect.config.entrypoint == [
        "/bin/sh",
        "-c",
        "/bin/bash",
    ]


@pytest.mark.parametrize(
    "inspect_output, cmd, entrypoint",
    [
        # the outputs are the inspect of a locally build container with the
        # following containerfile:
        #
        # FROM registry.opensuse.org/opensuse/leap:15.5
        # ENTRYPOINT ["/bin/bash", "-e"]
        # CMD ["/bin/sh", "-x"]
        #
        # The first output is with podman 5, the second with podman 4.9.1
        (
            """[
     {
          "Id": "fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e",
          "Created": "2024-04-09T16:47:49.910433337+02:00",
          "Path": "/bin/bash",
          "Args": [
               "-e",
               "/bin/sh",
               "-x"
          ],
          "State": {
               "OciVersion": "1.2.0",
               "Status": "exited",
               "Running": false,
               "Paused": false,
               "Restarting": false,
               "OOMKilled": false,
               "Dead": false,
               "Pid": 0,
               "ExitCode": 126,
               "Error": "",
               "StartedAt": "2024-04-09T16:47:50.010545401+02:00",
               "FinishedAt": "2024-04-09T16:47:50.010980413+02:00",
               "CheckpointedAt": "0001-01-01T00:00:00Z",
               "RestoredAt": "0001-01-01T00:00:00Z"
          },
          "Image": "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078",
          "ImageDigest": "sha256:ff1e7475953099b8220cedba0b94cbcfe527058dbf61395d8e65b41faf98c08f",
          "ImageName": "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078",
          "Rootfs": "",
          "Pod": "",
          "ResolvConfPath": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/resolv.conf",
          "HostnamePath": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/hostname",
          "HostsPath": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/hosts",
          "StaticDir": "/home/dan/.local/share/containers/storage/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata",
          "OCIConfigPath": "/home/dan/.local/share/containers/storage/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/config.json",
          "OCIRuntime": "crun",
          "ConmonPidFile": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/conmon.pid",
          "PidFile": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/pidfile",
          "Name": "friendly_nightingale",
          "RestartCount": 0,
          "Driver": "overlay",
          "MountLabel": "system_u:object_r:container_file_t:s0:c646,c903",
          "ProcessLabel": "system_u:system_r:container_t:s0:c646,c903",
          "AppArmorProfile": "",
          "EffectiveCaps": [
               "CAP_CHOWN",
               "CAP_DAC_OVERRIDE",
               "CAP_FOWNER",
               "CAP_FSETID",
               "CAP_KILL",
               "CAP_NET_BIND_SERVICE",
               "CAP_SETFCAP",
               "CAP_SETGID",
               "CAP_SETPCAP",
               "CAP_SETUID",
               "CAP_SYS_CHROOT"
          ],
          "BoundingCaps": [
               "CAP_CHOWN",
               "CAP_DAC_OVERRIDE",
               "CAP_FOWNER",
               "CAP_FSETID",
               "CAP_KILL",
               "CAP_NET_BIND_SERVICE",
               "CAP_SETFCAP",
               "CAP_SETGID",
               "CAP_SETPCAP",
               "CAP_SETUID",
               "CAP_SYS_CHROOT"
          ],
          "ExecIDs": [],
          "GraphDriver": {
               "Name": "overlay",
               "Data": {
                    "LowerDir": "/home/dan/.local/share/containers/storage/overlay/224932ba2e71427ad30ccd681525f367b54f64745170d78444063a0a773fb0d8/diff",
                    "UpperDir": "/home/dan/.local/share/containers/storage/overlay/282deb6da22d34dfa7e5136b9690c6ea65011a91c744f9b4df838dfee38e04ae/diff",
                    "WorkDir": "/home/dan/.local/share/containers/storage/overlay/282deb6da22d34dfa7e5136b9690c6ea65011a91c744f9b4df838dfee38e04ae/work"
               }
          },
          "Mounts": [],
          "Dependencies": [],
          "NetworkSettings": {
               "EndpointID": "",
               "Gateway": "",
               "IPAddress": "",
               "IPPrefixLen": 0,
               "IPv6Gateway": "",
               "GlobalIPv6Address": "",
               "GlobalIPv6PrefixLen": 0,
               "MacAddress": "",
               "Bridge": "",
               "SandboxID": "",
               "HairpinMode": false,
               "LinkLocalIPv6Address": "",
               "LinkLocalIPv6PrefixLen": 0,
               "Ports": {},
               "SandboxKey": "",
               "Networks": {
                    "pasta": {
                         "EndpointID": "",
                         "Gateway": "",
                         "IPAddress": "",
                         "IPPrefixLen": 0,
                         "IPv6Gateway": "",
                         "GlobalIPv6Address": "",
                         "GlobalIPv6PrefixLen": 0,
                         "MacAddress": "",
                         "NetworkID": "pasta",
                         "DriverOpts": null,
                         "IPAMConfig": null,
                         "Links": null
                    }
               }
          },
          "Namespace": "",
          "IsInfra": false,
          "IsService": false,
          "KubeExitCodePropagation": "invalid",
          "lockNumber": 1,
          "Config": {
               "Hostname": "fd7fb8d8123c",
               "Domainname": "",
               "User": "",
               "AttachStdin": false,
               "AttachStdout": false,
               "AttachStderr": false,
               "Tty": false,
               "OpenStdin": false,
               "StdinOnce": false,
               "Env": [
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "container=podman",
                    "HOME=/root",
                    "HOSTNAME=fd7fb8d8123c"
               ],
               "Cmd": [
                    "/bin/sh",
                    "-x"
               ],
               "Image": "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078",
               "Volumes": null,
               "WorkingDir": "/",
               "Entrypoint": [
                    "/bin/bash",
                    "-e"
               ],
               "OnBuild": null,
               "Labels": {
                    "io.buildah.version": "1.35.3",
                    "org.openbuildservice.disturl": "obs://build.opensuse.org/openSUSE:Leap:15.5:Images/images/8d2ff72f5b3e4b5979c7802995bc09b7-opensuse-leap-image:docker",
                    "org.opencontainers.image.created": "2023-12-19T07:39:42.838441137Z",
                    "org.opencontainers.image.description": "Image containing a minimal environment for containers based on openSUSE Leap 15.5.",
                    "org.opencontainers.image.source": "https://build.opensuse.org/package/show/openSUSE:Leap:15.5:Images/opensuse-leap-image?rev=8d2ff72f5b3e4b5979c7802995bc09b7",
                    "org.opencontainers.image.title": "openSUSE Leap 15.5 Base Container",
                    "org.opencontainers.image.url": "https://www.opensuse.org/",
                    "org.opencontainers.image.vendor": "openSUSE Project",
                    "org.opencontainers.image.version": "15.5.5.28",
                    "org.opensuse.base.created": "2023-12-19T07:39:42.838441137Z",
                    "org.opensuse.base.description": "Image containing a minimal environment for containers based on openSUSE Leap 15.5.",
                    "org.opensuse.base.disturl": "obs://build.opensuse.org/openSUSE:Leap:15.5:Images/images/8d2ff72f5b3e4b5979c7802995bc09b7-opensuse-leap-image:docker",
                    "org.opensuse.base.reference": "registry.opensuse.org/opensuse/leap:15.5.5.28",
                    "org.opensuse.base.source": "https://build.opensuse.org/package/show/openSUSE:Leap:15.5:Images/opensuse-leap-image?rev=8d2ff72f5b3e4b5979c7802995bc09b7",
                    "org.opensuse.base.title": "openSUSE Leap 15.5 Base Container",
                    "org.opensuse.base.url": "https://www.opensuse.org/",
                    "org.opensuse.base.vendor": "openSUSE Project",
                    "org.opensuse.base.version": "15.5.5.28",
                    "org.opensuse.reference": "registry.opensuse.org/opensuse/leap:15.5.5.28"
               },
               "Annotations": {
                    "io.container.manager": "libpod",
                    "org.opencontainers.image.stopSignal": "15"
               },
               "StopSignal": "SIGTERM",
               "HealthcheckOnFailureAction": "none",
               "CreateCommand": [
                    "podman",
                    "run",
                    "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078"
               ],
               "Umask": "0022",
               "Timeout": 0,
               "StopTimeout": 10,
               "Passwd": true,
               "sdNotifyMode": "container"
          },
          "HostConfig": {
               "Binds": [],
               "CgroupManager": "systemd",
               "CgroupMode": "private",
               "ContainerIDFile": "",
               "LogConfig": {
                    "Type": "journald",
                    "Config": null,
                    "Path": "",
                    "Tag": "",
                    "Size": "0B"
               },
               "NetworkMode": "pasta",
               "PortBindings": {},
               "RestartPolicy": {
                    "Name": "",
                    "MaximumRetryCount": 0
               },
               "AutoRemove": false,
               "VolumeDriver": "",
               "VolumesFrom": null,
               "CapAdd": [],
               "CapDrop": [],
               "Dns": [],
               "DnsOptions": [],
               "DnsSearch": [],
               "ExtraHosts": [],
               "GroupAdd": [],
               "IpcMode": "shareable",
               "Cgroup": "",
               "Cgroups": "default",
               "Links": null,
               "OomScoreAdj": 0,
               "PidMode": "private",
               "Privileged": false,
               "PublishAllPorts": false,
               "ReadonlyRootfs": false,
               "SecurityOpt": [],
               "Tmpfs": {},
               "UTSMode": "private",
               "UsernsMode": "",
               "ShmSize": 65536000,
               "Runtime": "oci",
               "ConsoleSize": [
                    0,
                    0
               ],
               "Isolation": "",
               "CpuShares": 0,
               "Memory": 0,
               "NanoCpus": 0,
               "CgroupParent": "user.slice",
               "BlkioWeight": 0,
               "BlkioWeightDevice": null,
               "BlkioDeviceReadBps": null,
               "BlkioDeviceWriteBps": null,
               "BlkioDeviceReadIOps": null,
               "BlkioDeviceWriteIOps": null,
               "CpuPeriod": 0,
               "CpuQuota": 0,
               "CpuRealtimePeriod": 0,
               "CpuRealtimeRuntime": 0,
               "CpusetCpus": "",
               "CpusetMems": "",
               "Devices": [],
               "DiskQuota": 0,
               "KernelMemory": 0,
               "MemoryReservation": 0,
               "MemorySwap": 0,
               "MemorySwappiness": 0,
               "OomKillDisable": false,
               "PidsLimit": 2048,
               "Ulimits": [
                    {
                         "Name": "RLIMIT_NOFILE",
                         "Soft": 1048576,
                         "Hard": 1048576
                    },
                    {
                         "Name": "RLIMIT_NPROC",
                         "Soft": 126926,
                         "Hard": 126926
                    }
               ],
               "CpuCount": 0,
               "CpuPercent": 0,
               "IOMaximumIOps": 0,
               "IOMaximumBandwidth": 0,
               "CgroupConf": null
          }
     }
]
""",
            ["/bin/sh", "-x"],
            ["/bin/bash", "-e"],
        ),
        (
            """[
     {
          "Id": "fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e",
          "Created": "2024-04-09T16:47:49.910433337+02:00",
          "Path": "/bin/bash",
          "Args": [
               "-e",
               "/bin/sh",
               "-x"
          ],
          "State": {
               "OciVersion": "1.2.0",
               "Status": "exited",
               "Running": false,
               "Paused": false,
               "Restarting": false,
               "OOMKilled": false,
               "Dead": false,
               "Pid": 0,
               "ExitCode": 126,
               "Error": "",
               "StartedAt": "2024-04-09T16:47:50.010545401+02:00",
               "FinishedAt": "2024-04-09T16:47:50.010980413+02:00",
               "Health": {
                    "Status": "",
                    "FailingStreak": 0,
                    "Log": null
               },
               "CheckpointedAt": "0001-01-01T00:00:00Z",
               "RestoredAt": "0001-01-01T00:00:00Z"
          },
          "Image": "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078",
          "ImageDigest": "sha256:ff1e7475953099b8220cedba0b94cbcfe527058dbf61395d8e65b41faf98c08f",
          "ImageName": "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078",
          "Rootfs": "",
          "Pod": "",
          "ResolvConfPath": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/resolv.conf",
          "HostnamePath": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/hostname",
          "HostsPath": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/hosts",
          "StaticDir": "/home/dan/.local/share/containers/storage/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata",
          "OCIConfigPath": "/home/dan/.local/share/containers/storage/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/config.json",
          "OCIRuntime": "crun",
          "ConmonPidFile": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/conmon.pid",
          "PidFile": "/run/user/1000/containers/overlay-containers/fd7fb8d8123c0632558620612f900162ea71e574e3caa0ff023565dc8cd42e0e/userdata/pidfile",
          "Name": "friendly_nightingale",
          "RestartCount": 0,
          "Driver": "overlay",
          "MountLabel": "system_u:object_r:container_file_t:s0:c646,c903",
          "ProcessLabel": "system_u:system_r:container_t:s0:c646,c903",
          "AppArmorProfile": "",
          "EffectiveCaps": [
               "CAP_CHOWN",
               "CAP_DAC_OVERRIDE",
               "CAP_FOWNER",
               "CAP_FSETID",
               "CAP_KILL",
               "CAP_NET_BIND_SERVICE",
               "CAP_SETFCAP",
               "CAP_SETGID",
               "CAP_SETPCAP",
               "CAP_SETUID",
               "CAP_SYS_CHROOT"
          ],
          "BoundingCaps": [
               "CAP_CHOWN",
               "CAP_DAC_OVERRIDE",
               "CAP_FOWNER",
               "CAP_FSETID",
               "CAP_KILL",
               "CAP_NET_BIND_SERVICE",
               "CAP_SETFCAP",
               "CAP_SETGID",
               "CAP_SETPCAP",
               "CAP_SETUID",
               "CAP_SYS_CHROOT"
          ],
          "ExecIDs": [],
          "GraphDriver": {
               "Name": "overlay",
               "Data": {
                    "LowerDir": "/home/dan/.local/share/containers/storage/overlay/224932ba2e71427ad30ccd681525f367b54f64745170d78444063a0a773fb0d8/diff",
                    "UpperDir": "/home/dan/.local/share/containers/storage/overlay/282deb6da22d34dfa7e5136b9690c6ea65011a91c744f9b4df838dfee38e04ae/diff",
                    "WorkDir": "/home/dan/.local/share/containers/storage/overlay/282deb6da22d34dfa7e5136b9690c6ea65011a91c744f9b4df838dfee38e04ae/work"
               }
          },
          "Mounts": [],
          "Dependencies": [],
          "NetworkSettings": {
               "EndpointID": "",
               "Gateway": "",
               "IPAddress": "",
               "IPPrefixLen": 0,
               "IPv6Gateway": "",
               "GlobalIPv6Address": "",
               "GlobalIPv6PrefixLen": 0,
               "MacAddress": "",
               "Bridge": "",
               "SandboxID": "",
               "HairpinMode": false,
               "LinkLocalIPv6Address": "",
               "LinkLocalIPv6PrefixLen": 0,
               "Ports": {},
               "SandboxKey": "",
               "Networks": {
                    "pasta": {
                         "EndpointID": "",
                         "Gateway": "",
                         "IPAddress": "",
                         "IPPrefixLen": 0,
                         "IPv6Gateway": "",
                         "GlobalIPv6Address": "",
                         "GlobalIPv6PrefixLen": 0,
                         "MacAddress": "",
                         "NetworkID": "pasta",
                         "DriverOpts": null,
                         "IPAMConfig": null,
                         "Links": null
                    }
               }
          },
          "Namespace": "",
          "IsInfra": false,
          "IsService": false,
          "KubeExitCodePropagation": "invalid",
          "lockNumber": 1,
          "Config": {
               "Hostname": "fd7fb8d8123c",
               "Domainname": "",
               "User": "",
               "AttachStdin": false,
               "AttachStdout": false,
               "AttachStderr": false,
               "Tty": false,
               "OpenStdin": false,
               "StdinOnce": false,
               "Env": [
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "container=podman",
                    "HOME=/root",
                    "HOSTNAME=fd7fb8d8123c"
               ],
               "Cmd": [
                    "/bin/sh",
                    "-x"
               ],
               "Image": "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078",
               "Volumes": null,
               "WorkingDir": "/",
               "Entrypoint": "/bin/bash -e",
               "OnBuild": null,
               "Labels": {
                    "io.buildah.version": "1.35.3",
                    "org.openbuildservice.disturl": "obs://build.opensuse.org/openSUSE:Leap:15.5:Images/images/8d2ff72f5b3e4b5979c7802995bc09b7-opensuse-leap-image:docker",
                    "org.opencontainers.image.created": "2023-12-19T07:39:42.838441137Z",
                    "org.opencontainers.image.description": "Image containing a minimal environment for containers based on openSUSE Leap 15.5.",
                    "org.opencontainers.image.source": "https://build.opensuse.org/package/show/openSUSE:Leap:15.5:Images/opensuse-leap-image?rev=8d2ff72f5b3e4b5979c7802995bc09b7",
                    "org.opencontainers.image.title": "openSUSE Leap 15.5 Base Container",
                    "org.opencontainers.image.url": "https://www.opensuse.org/",
                    "org.opencontainers.image.vendor": "openSUSE Project",
                    "org.opencontainers.image.version": "15.5.5.28",
                    "org.opensuse.base.created": "2023-12-19T07:39:42.838441137Z",
                    "org.opensuse.base.description": "Image containing a minimal environment for containers based on openSUSE Leap 15.5.",
                    "org.opensuse.base.disturl": "obs://build.opensuse.org/openSUSE:Leap:15.5:Images/images/8d2ff72f5b3e4b5979c7802995bc09b7-opensuse-leap-image:docker",
                    "org.opensuse.base.reference": "registry.opensuse.org/opensuse/leap:15.5.5.28",
                    "org.opensuse.base.source": "https://build.opensuse.org/package/show/openSUSE:Leap:15.5:Images/opensuse-leap-image?rev=8d2ff72f5b3e4b5979c7802995bc09b7",
                    "org.opensuse.base.title": "openSUSE Leap 15.5 Base Container",
                    "org.opensuse.base.url": "https://www.opensuse.org/",
                    "org.opensuse.base.vendor": "openSUSE Project",
                    "org.opensuse.base.version": "15.5.5.28",
                    "org.opensuse.reference": "registry.opensuse.org/opensuse/leap:15.5.5.28"
               },
               "Annotations": {
                    "io.container.manager": "libpod",
                    "org.opencontainers.image.stopSignal": "15"
               },
               "StopSignal": 15,
               "HealthcheckOnFailureAction": "none",
               "CreateCommand": [
                    "podman",
                    "run",
                    "5a2338f9e13b00ed6ec6044a16adcc9479d7c27889ad69d5c21acb99a02bb078"
               ],
               "Umask": "0022",
               "Timeout": 0,
               "StopTimeout": 10,
               "Passwd": true,
               "sdNotifyMode": "container"
          },
          "HostConfig": {
               "Binds": [],
               "CgroupManager": "systemd",
               "CgroupMode": "private",
               "ContainerIDFile": "",
               "LogConfig": {
                    "Type": "journald",
                    "Config": null,
                    "Path": "",
                    "Tag": "",
                    "Size": "0B"
               },
               "NetworkMode": "pasta",
               "PortBindings": {},
               "RestartPolicy": {
                    "Name": "",
                    "MaximumRetryCount": 0
               },
               "AutoRemove": false,
               "VolumeDriver": "",
               "VolumesFrom": null,
               "CapAdd": [],
               "CapDrop": [],
               "Dns": [],
               "DnsOptions": [],
               "DnsSearch": [],
               "ExtraHosts": [],
               "GroupAdd": [],
               "IpcMode": "shareable",
               "Cgroup": "",
               "Cgroups": "default",
               "Links": null,
               "OomScoreAdj": 0,
               "PidMode": "private",
               "Privileged": false,
               "PublishAllPorts": false,
               "ReadonlyRootfs": false,
               "SecurityOpt": [],
               "Tmpfs": {},
               "UTSMode": "private",
               "UsernsMode": "",
               "ShmSize": 65536000,
               "Runtime": "oci",
               "ConsoleSize": [
                    0,
                    0
               ],
               "Isolation": "",
               "CpuShares": 0,
               "Memory": 0,
               "NanoCpus": 0,
               "CgroupParent": "user.slice",
               "BlkioWeight": 0,
               "BlkioWeightDevice": null,
               "BlkioDeviceReadBps": null,
               "BlkioDeviceWriteBps": null,
               "BlkioDeviceReadIOps": null,
               "BlkioDeviceWriteIOps": null,
               "CpuPeriod": 0,
               "CpuQuota": 0,
               "CpuRealtimePeriod": 0,
               "CpuRealtimeRuntime": 0,
               "CpusetCpus": "",
               "CpusetMems": "",
               "Devices": [],
               "DiskQuota": 0,
               "KernelMemory": 0,
               "MemoryReservation": 0,
               "MemorySwap": 0,
               "MemorySwappiness": 0,
               "OomKillDisable": false,
               "PidsLimit": 2048,
               "Ulimits": [
                    {
                         "Name": "RLIMIT_NOFILE",
                         "Soft": 1048576,
                         "Hard": 1048576
                    },
                    {
                         "Name": "RLIMIT_NPROC",
                         "Soft": 126926,
                         "Hard": 126926
                    }
               ],
               "CpuCount": 0,
               "CpuPercent": 0,
               "IOMaximumIOps": 0,
               "IOMaximumBandwidth": 0,
               "CgroupConf": null
          }
     }
]
""",
            ["/bin/sh", "-x"],
            ["/bin/bash", "-e"],
        ),
    ],
)
def test_podman_inspect_parsing(
    inspect_output: str,
    monkeypatch: pytest.MonkeyPatch,
    cmd: List[str],
    entrypoint: List[str],
):
    monkeypatch.setattr(
        OciRuntimeBase,
        "_get_container_inspect",
        lambda _self, _unused: json.loads(inspect_output)[0],
    )

    inspect = PodmanRuntime().inspect_container("INVALID")
    assert inspect.config.cmd == cmd
    assert inspect.config.entrypoint == entrypoint
