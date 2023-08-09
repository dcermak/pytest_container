# pylint: disable=missing-function-docstring,missing-module-docstring
import os
from unittest.mock import patch

import pytest

from pytest_container.runtime import DockerRuntime
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime


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
# pylint: disable-next=redefined-outer-name,unused-argument
def test_runtime_selection(
    container_runtime_envvar: None, runtime: OciRuntimeBase
):
    assert get_selected_runtime() == runtime


@pytest.mark.parametrize(
    "container_runtime_envvar",
    ["foobar"],
    indirect=["container_runtime_envvar"],
)
# pylint: disable-next=redefined-outer-name,unused-argument
def test_errors_out_when_invalid_runtime_selected(
    container_runtime_envvar: None,
) -> None:
    with pytest.raises(ValueError) as val_err_ctx:
        get_selected_runtime()

    assert "foobar" in str(val_err_ctx.value)
    assert "Invalid CONTAINER_RUNTIME" in str(val_err_ctx.value)


IMG_ID = "ff6613b5320b83dfcef7bc54e224fd6696d89c6bd5df79d8b5df520a13fa4918"


@pytest.mark.parametrize(
)
