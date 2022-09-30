# pylint: disable=missing-function-docstring
import os
from pytest_container.runtime import DockerRuntime
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime
from unittest.mock import patch

import pytest


@pytest.fixture
def container_runtime_envvar(request):
    with patch.dict(
        os.environ,
        {} if request.param is None else {"CONTAINER_RUNTIME": request.param},
        clear=True,
    ):
        yield


@pytest.mark.parametrize(
    "container_runtime_envvar,runtime",
    [
        ("podman", PodmanRuntime()),
        ("docker", DockerRuntime()),
        ("PODMAN", PodmanRuntime()),
        ("DOCKER", DockerRuntime()),
        (None, PodmanRuntime()),
    ],
    indirect=["container_runtime_envvar"],
)
def test_runtime_selection(container_runtime_envvar, runtime):
    assert get_selected_runtime() == runtime


@pytest.mark.parametrize(
    "container_runtime_envvar",
    ["foobar"],
    indirect=["container_runtime_envvar"],
)
def test_errors_out_when_invalid_runtime_selected(container_runtime_envvar):
    with pytest.raises(ValueError) as ve:
        get_selected_runtime()

    assert "foobar" in str(ve.value)
    assert "Invalid CONTAINER_RUNTIME" in str(ve.value)


IMG_ID = "ff6613b5320b83dfcef7bc54e224fd6696d89c6bd5df79d8b5df520a13fa4918"


@pytest.mark.parametrize(
    "runtime,stdout",
    [
        (
            PodmanRuntime(),
            f"""--> 4f64f1922f6
STEP 3/3: ENTRYPOINT [ "/usr/bin/gem2rpm" ]
COMMIT tumbleweed-gem2rpm
--> ff6613b5320
Successfully tagged localhost/tumbleweed-gem2rpm:latest
{IMG_ID}

""",
        ),
        (
            DockerRuntime(),
            f"""Step 3/3 : ENTRYPOINT [ "/usr/bin/gem2rpm" ]
 ---> Using cache
 ---> e0216d275900
Successfully built {IMG_ID}

""",
        ),
    ],
)
def test_get_image_id(runtime: OciRuntimeBase, stdout: str):
    assert runtime.get_image_id_from_stdout(stdout) == IMG_ID
