from pytest_container.container import Container
from pytest_container.container import ContainerData
from pytest_container.container import DerivedContainer
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase
from subprocess import check_output
from typing import Generator
from typing import Optional
from typing import Union

import pytest
import testinfra
from _pytest.config import Config
from _pytest.fixtures import SubRequest


@pytest.fixture(scope="session")
def container_runtime() -> OciRuntimeBase:
    """pytest fixture that returns the currently selected container runtime
    according to the rules outlined :ref:`here <runtime selection rules>`.

    """
    return get_selected_runtime()


def _auto_container_fixture(
    request: SubRequest,
    container_runtime: OciRuntimeBase,
    pytestconfig: Config,
) -> Generator[ContainerData, None, None]:
    """Fixture that will build & launch a container that is either passed as a
    request parameter or it will be automatically parametrized via
    pytest_generate_tests.
    """
    launch_data: Union[Container, DerivedContainer] = request.param

    container_id: Optional[str] = None
    try:
        launch_data.prepare_container(rootdir=pytestconfig.rootdir)
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
