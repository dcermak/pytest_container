"""Module that defines all commonly used container images for testing."""
from pytest_container.container import Container
from pytest_container.container import DerivedContainer
from pytest_container.container import ImageFormat
from pytest_container.container import PortForwarding
from pytest_container.pod import Pod
from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import Version


LEAP_URL = "registry.opensuse.org/opensuse/leap:latest"
OPENSUSE_BUSYBOX_URL = "registry.opensuse.org/opensuse/busybox:latest"
NGINX_URL = "registry.opensuse.org/opensuse/nginx"

LEAP = Container(url=LEAP_URL)

WEB_SERVER = DerivedContainer(
    base=LEAP,
    containerfile="""
RUN zypper -n in python3 curl && echo "Hello Green World!" > index.html
ENTRYPOINT ["/usr/bin/python3", "-m", "http.server"]
HEALTHCHECK --interval=5s --timeout=1s CMD curl --fail http://0.0.0.0:8000
EXPOSE 8000
""",
    forwarded_ports=[PortForwarding(container_port=8000)],
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

BUSYBOX = Container(url=OPENSUSE_BUSYBOX_URL)

TEST_POD = Pod(
    containers=[LEAP, LEAP_WITH_MAN, BUSYBOX],
    forwarded_ports=[PortForwarding(80), PortForwarding(22)],
)


_curl_version = Version.parse(LOCALHOST.package("curl").version)

#: curl cli with additional retries as a single curl sometimes fails with docker
#: with ``curl: (56) Recv failure: Connection reset by peer`` for reasons…
#: So let's just try again until it works…

CURL = "curl --retry 5"

# the --retry-all-errors has been added in version 7.71.0:
# https://curl.se/docs/manpage.html#--retry-all-errors
if _curl_version >= Version(major=7, minor=71, patch=0):
    CURL = f"{CURL} --retry-all-errors"
