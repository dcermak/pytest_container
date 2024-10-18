# pylint: disable=missing-function-docstring,missing-module-docstring
import os
from pathlib import Path
from typing import Type
from unittest.mock import patch

import pytest
from pytest_container.runtime import DockerRuntime
from pytest_container.runtime import get_selected_runtime
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime


@pytest.fixture
def container_runtime_envvar(request):
    new_env = {
        "PATH": os.environ["PATH"],
    }
    if request.param is not None:
        new_env["CONTAINER_RUNTIME"] = request.param

    with patch.dict(os.environ, new_env, clear=True):
        yield


@pytest.mark.parametrize(
    "container_runtime_envvar,runtime_class",
    [
        ("podman", PodmanRuntime),
        ("docker", DockerRuntime),
        ("PODMAN", PodmanRuntime),
        ("DOCKER", DockerRuntime),
        (None, PodmanRuntime),
    ],
    indirect=["container_runtime_envvar"],
)
def test_runtime_selection(
    # pylint: disable-next=redefined-outer-name,unused-argument
    container_runtime_envvar: None,
    runtime_class: Type[OciRuntimeBase],
):
    assert isinstance(get_selected_runtime(), runtime_class)


@pytest.mark.parametrize(
    "container_runtime_envvar",
    ["foobar"],
    indirect=["container_runtime_envvar"],
)
def test_errors_out_when_invalid_runtime_selected(
    # pylint: disable-next=redefined-outer-name,unused-argument
    container_runtime_envvar: None,
) -> None:
    with pytest.raises(ValueError) as val_err_ctx:
        get_selected_runtime()

    assert "foobar" in str(val_err_ctx.value)
    assert "Invalid CONTAINER_RUNTIME" in str(val_err_ctx.value)


IMG_ID = "ff6613b5320b83dfcef7bc54e224fd6696d89c6bd5df79d8b5df520a13fa4918"


@pytest.mark.parametrize("iidfile_contents", [IMG_ID, f"sha256:{IMG_ID}"])
def test_get_image_id_from_iidfile(
    iidfile_contents: str, tmp_path: Path
) -> None:
    iidfile_path = str(tmp_path / "iidfile")
    with open(iidfile_path, "w", encoding="utf-8") as iidfile:
        iidfile.write(iidfile_contents)
    assert OciRuntimeBase.get_image_id_from_iidfile(iidfile_path) == IMG_ID


@pytest.mark.parametrize(
    "invalid_digest", [f"md5:{IMG_ID}", f"md4:sha256:{IMG_ID}"]
)
def test_get_image_id_from_iidfile_with_invalid_format(
    invalid_digest: str, tmp_path: Path
) -> None:
    iidfile_path = str(tmp_path / "iidfile")
    with open(iidfile_path, "w", encoding="utf-8") as iidfile:
        iidfile.write(invalid_digest)

    with pytest.raises(ValueError) as val_err_ctx:
        OciRuntimeBase.get_image_id_from_iidfile(iidfile_path)

    assert "Invalid" in str(val_err_ctx.value)
