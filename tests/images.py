from pytest_container.container import Container
from pytest_container.container import DerivedContainer
from pytest_container.container import ImageFormat
from pytest_container.container import PortForwarding
from pytest_container.pod import Pod


BUSYBOX_URL = "docker.io/library/busybox"
LEAP_URL = "registry.opensuse.org/opensuse/leap:latest"
OPENSUSE_BUSYBOX_URL = "registry.opensuse.org/opensuse/busybox:latest"
NGINX_URL = "docker.io/library/nginx"
ALPINE_URL = "docker.io/library/alpine"

LEAP = Container(url=LEAP_URL)

WEB_SERVER = DerivedContainer(
    base=LEAP,
    containerfile="""
RUN zypper -n in python3 && echo "Hello Green World!" > index.html
ENTRYPOINT ["/usr/bin/python3", "-m", "http.server"]
HEALTHCHECK --interval=5s --timeout=1s CMD curl --fail http://0.0.0.0:8000
EXPOSE 8000
""",
    forwarded_ports=[PortForwarding(container_port=8000)],
    default_entry_point=True,
)

CONTAINER_THAT_FAILS_TO_LAUNCH = DerivedContainer(
    base=LEAP_URL,
    image_format=ImageFormat.DOCKER,
    containerfile="""CMD sleep 600
# use a short timeout to keep the test run short
HEALTHCHECK --retries=1 --interval=1s --timeout=1s CMD false
""",
)

LEAP_WITH_MAN = DerivedContainer(
    base=LEAP_URL,
    containerfile="RUN zypper -n in man",
)

ALPINE = Container(url=ALPINE_URL, custom_entry_point="/bin/sh")

TEST_POD = Pod(
    containers=[LEAP, LEAP_WITH_MAN, ALPINE],
    forwarded_ports=[PortForwarding(80), PortForwarding(22)],
)
