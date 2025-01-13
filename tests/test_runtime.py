# pylint: disable=missing-function-docstring,missing-module-docstring
import os
from pathlib import Path
from typing import Callable
from typing import Type
from typing import Union
from unittest.mock import patch

import pytest

from pytest_container.runtime import LOCALHOST
from pytest_container.runtime import DockerRuntime
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import PodmanRuntime
from pytest_container.runtime import Version
from pytest_container.runtime import _get_buildah_version
from pytest_container.runtime import get_selected_runtime


@pytest.fixture
def container_runtime_envvar(request):
    with patch.dict(
        os.environ,
        {} if request.param is None else {"CONTAINER_RUNTIME": request.param},
        clear=True,
    ):
        yield


# pylint: disable-next=unused-argument
def _mock_run_success(*args, **kwargs):
    class Succeeded:
        """Class that mocks the returned object of `testinfra`'s `run`."""

        @property
        def succeeded(self) -> bool:
            return True

        @property
        def rc(self) -> int:
            return 0

    return Succeeded()


def generate_mock_fail(*, rc: int = 1, stderr: str = "failure!!"):
    # pylint: disable-next=unused-argument
    def mock_run_fail(cmd: str):
        class Failure:
            """Class that mocks the returned object of `testinfra`'s `run`."""

            @property
            def succeeded(self) -> bool:
                return False

            @property
            def rc(self) -> int:
                return rc

            @property
            def stderr(self) -> str:
                return stderr

        return Failure()

    return mock_run_fail


def _create_mock_exists(
    podman_should_exist: bool, docker_should_exist: bool
) -> Callable[[str], bool]:
    def exists(prog: str) -> bool:
        if prog == "podman" and podman_should_exist:
            return True
        if prog == "docker" and docker_should_exist:
            return True
        return False

    return exists


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
def test_runtime_selection(
    # pylint: disable-next=redefined-outer-name,unused-argument
    container_runtime_envvar: None,
    runtime: OciRuntimeBase,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(LOCALHOST, "run", _mock_run_success)
    monkeypatch.setattr(LOCALHOST, "exists", _create_mock_exists(True, True))

    assert get_selected_runtime() == runtime


@pytest.mark.parametrize("runtime", ("podman", "docker"))
def test_value_err_when_docker_and_podman_missing(
    runtime: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTAINER_RUNTIME", runtime)
    monkeypatch.setattr(LOCALHOST, "exists", _create_mock_exists(False, False))
    with pytest.raises(ValueError) as val_err_ctx:
        get_selected_runtime()

    assert f"Selected runtime {runtime} does not exist on the system" in str(
        val_err_ctx.value
    )


@pytest.mark.parametrize(
    "cls, name", ((PodmanRuntime, "podman"), (DockerRuntime, "docker"))
)
def test_runtime_construction_fails_if_ps_fails(
    cls: Union[Type[PodmanRuntime], Type[DockerRuntime]],
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = "container runtime failed"
    monkeypatch.setattr(LOCALHOST, "run", generate_mock_fail(stderr=stderr))
    with pytest.raises(RuntimeError) as rt_err_ctx:
        cls()

    assert f"`{name} ps` failed with {stderr}" in str(rt_err_ctx.value)


@pytest.mark.parametrize(
    "version_str, expected_version",
    (
        ("1.38.0", Version(1, 38, 0)),
        ("1.25.3", Version(1, 25, 3)),
    ),
)
def test_buildah_version_parsing(
    version_str: str,
    expected_version: Version,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LOCALHOST, "check_output", lambda _: f"buildah version {version_str}"
    )

    assert _get_buildah_version() == expected_version


def test_get_buildah_version_fails_on_unexpected_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(LOCALHOST, "check_output", lambda _: "foobar")
    with pytest.raises(RuntimeError) as rt_err_ctx:
        _get_buildah_version()

    assert "Could not decode the buildah version from 'foobar'" in str(
        rt_err_ctx.value
    )


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
