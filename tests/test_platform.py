import pytest
from pytest_container.container import Container
from pytest_container.container import ContainerData
from pytest_container.container import DerivedContainer
from pytest_container.runtime import LOCALHOST

from tests.images import LEAP_URL


_foreign_arch = (
    "aarch64" if LOCALHOST.system_info.arch != "aarch64" else "x86_64"
)

FOREIGN_ARCH_CONTAINER = Container(
    url=LEAP_URL,
    architecture=_foreign_arch,
)

DERIVED_FROM_FOREIGN_ARCH = DerivedContainer(
    base=FOREIGN_ARCH_CONTAINER, containerfile="ENV HOME=/"
)

DERIVED_WITH_FOREIGN_ARCH_FROM_STR = DerivedContainer(
    base=LEAP_URL, architecture=_foreign_arch
)


@pytest.mark.parametrize("container", [FOREIGN_ARCH_CONTAINER], indirect=True)
def test_foreign_arch_container(container: ContainerData) -> None:
    assert container.connection.check_output("uname -m") == _foreign_arch


@pytest.mark.parametrize(
    "container", [DERIVED_FROM_FOREIGN_ARCH], indirect=True
)
def test_derived_container_foreign_arch(container: ContainerData) -> None:
    assert container.connection.check_output("uname -m") == _foreign_arch
