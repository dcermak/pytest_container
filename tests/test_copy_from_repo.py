# pylint: disable=missing-function-docstring,missing-module-docstring
from pytest import Config

from pytest_container import DerivedContainer
from pytest_container.container import ContainerData

from .images import LEAP_URL

_FNAME = "pyproject.toml"

LEAP_WITH_CONFIG_FILE = DerivedContainer(
    base=LEAP_URL,
    containerfile=f"""WORKDIR /opt/app/
COPY {_FNAME} /opt/app/{_FNAME}""",
)

CONTAINER_IMAGES = [LEAP_WITH_CONFIG_FILE]


def test_config_file_present(
    auto_container: ContainerData, pytestconfig: Config
):
    assert auto_container.connection.file(f"/opt/app/{_FNAME}").exists
    with open(pytestconfig.rootpath / _FNAME, encoding="utf-8") as pyproject:
        assert auto_container.connection.file(
            f"/opt/app/{_FNAME}"
        ).content_string == pyproject.read(-1)
