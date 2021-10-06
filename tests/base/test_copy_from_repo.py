from pytest_container import DerivedContainer


LEAP_WITH_CONFIG_FILE = DerivedContainer(
    base="registry.opensuse.org/opensuse/leap:latest",
    containerfile="""WORKDIR /opt/app/
COPY pyproject.toml /opt/app/pyproject.toml""",
)

CONTAINER_IMAGES = [LEAP_WITH_CONFIG_FILE]


def test_config_file_present(auto_container, pytestconfig):
    assert auto_container.connection.file("/opt/app/pyproject.toml").exists
    with open(pytestconfig.rootdir / "pyproject.toml") as pyproject:
        assert auto_container.connection.file(
            "/opt/app/pyproject.toml"
        ).content_string == pyproject.read(-1)
