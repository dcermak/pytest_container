from subprocess import check_output
from typing import Any
from typing import NamedTuple
from typing import Optional
from typing import Union

import pytest
import testinfra

from pytest_container.container import Container
from pytest_container.container import DerivedContainer
from pytest_container.helpers import get_selected_runtime


class ContainerData(NamedTuple):
    #: url to the container image on the registry or the id of the local image
    #: if the container has been build locally
    image_url_or_id: str
    #: ID of the started container
    container_id: str
    #: the testinfra connection to the running container
    connection: Any


@pytest.fixture(scope="module")
def container_runtime():
    return get_selected_runtime()


def _auto_container_fixture(request, container_runtime):
    """Fixture that will build & launch a container that is either passed as a
    request parameter or it will be automatically parametrized via
    pytest_generate_tests.
    """
    launch_data: Union[Container, DerivedContainer] = request.param

    container_id: Optional[str] = None
    try:
        launch_data.prepare_container()
        container_id = (
            check_output(
                [container_runtime.runner_binary]
                + launch_data.get_launch_cmd()
            )
            .decode()
            .strip()
        )
        yield ContainerData(
            image_url_or_id=launch_data.url or launch_data.container_id,
            container_id=container_id,
            connection=testinfra.get_host(
                f"{container_runtime.runner_binary}://{container_id}"
            ),
        )
    except RuntimeError as exc:
        raise exc
    finally:
        if container_id is not None:
            check_output(
                [container_runtime.runner_binary, "rm", "-f", container_id]
            )


auto_container = pytest.fixture(scope="session")(_auto_container_fixture)
container = auto_container

auto_container_per_test = pytest.fixture(scope="function")(
    _auto_container_fixture
)
container_per_test = auto_container_per_test


def pytest_generate_tests(metafunc):
    container_images = getattr(metafunc.module, "CONTAINER_IMAGES", None)
    if container_images is not None:
        for fixture_name in ("auto_container", "auto_container_per_test"):
            if fixture_name in metafunc.fixturenames:
                metafunc.parametrize(
                    fixture_name, container_images, indirect=True
                )
