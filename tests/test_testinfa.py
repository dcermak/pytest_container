import pytest

try:
    import testinfra
except ImportError:
    raise pytest.skip("testinfra is not installed", allow_module_level=True)

from pytest_container.container import ContainerData
from .images import BUSYBOX


@pytest.mark.parametrize("container", [BUSYBOX], indirect=True)
def test_testinfra_connection(container: ContainerData):

    assert isinstance(container.connection, testinfra.host.Host)
    cmd = container.connection.run("ls -l /etc/passwd")
    assert cmd.rc == 0
