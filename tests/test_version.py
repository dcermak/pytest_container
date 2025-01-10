"""Unit tests of the Version class"""

# pylint: disable=missing-function-docstring,missing-module-docstring
import pytest

from pytest_container import Version
from pytest_container.runtime import OciRuntimeBase
from pytest_container.runtime import _get_docker_version
from pytest_container.runtime import _get_podman_version

# pragma pylint: disable=missing-function-docstring


@pytest.mark.parametrize(
    "ver1,ver2",
    [
        (Version(1, 0, 2), Version(1, 0, 2)),
        (Version(2, 0), Version(2, 0, 0)),
    ],
)
def test_version_eq(ver1: Version, ver2: Version):
    assert ver1 == ver2


def test_incompatible_types_eq() -> None:
    assert Version(1, 2) != 3


def test_incompatible_types_cmp() -> None:
    with pytest.raises(TypeError) as ctx:
        _ = Version(1, 2) < 3

    assert "'<' not supported between instances of 'Version' and 'int'" in str(
        ctx.value
    )


@pytest.mark.parametrize(
    "ver1,ver2",
    [
        (Version(1, 0, 2), Version(1, 0, 1)),
        (Version(2, 0, 1), Version(1, 0, 1)),
        (Version(1, 5, 1), Version(1, 0, 1)),
        (Version(1, 0, 1), Version(1, 0, 1, build="foobar")),
        (Version(1, 0, 1), Version(1, 0, 1, release="foobar")),
        (Version(1, 0, 1), Version(1, 0, 1, release="foobar", build="5")),
    ],
)
def test_version_ne(ver1: Version, ver2: Version):
    assert ver1 != ver2


@pytest.mark.parametrize(
    "ver,stringified",
    [
        (Version(1, 2), "1.2"),
        (Version(1, 2, 5), "1.2.5"),
        (Version(0, 3, 0), "0.3.0"),
        (Version(1, 2, 5, build="sdf"), "1.2.5 build sdf"),
        (Version(1, 2, 5, release="1.fc16"), "1.2.5-1.fc16"),
        (
            Version(1, 2, 5, release="1.fc16", build="38"),
            "1.2.5-1.fc16 build 38",
        ),
    ],
)
def test_version_str(ver: Version, stringified: str):
    assert str(ver) == stringified


@pytest.mark.parametrize(
    "larger,smaller",
    [
        (Version(1, 2, 3), Version(1, 2, 2)),
        (Version(1, 2, 3), Version(1, 1, 3)),
        (Version(1, 2, 3), Version(0, 2, 3)),
    ],
)
def test_version_ge_gt(larger: Version, smaller: Version):
    assert larger > smaller
    assert not smaller > larger

    assert larger >= smaller
    assert not smaller >= larger

    # pragma pylint: disable=comparison-with-itself
    assert larger >= larger
    assert smaller >= smaller


@pytest.mark.parametrize(
    "larger,smaller",
    [
        (Version(1, 2, 3), Version(1, 2, 2)),
        (Version(1, 2, 3), Version(1, 1, 3)),
        (Version(1, 2, 3), Version(0, 2, 3)),
    ],
)
def test_version_le_lt(larger: Version, smaller: Version):
    assert smaller < larger
    assert not larger < smaller

    assert smaller <= larger
    assert not larger <= smaller

    # pragma pylint: disable=comparison-with-itself
    assert larger <= larger
    assert smaller <= smaller


@pytest.mark.parametrize(
    "stdout,ver",
    [
        (
            "Docker version 1.12.6, build 78d1802",
            Version(1, 12, 6, build="78d1802"),
        ),
        (
            "Docker version 20.10.12-ce, build 459d0dfbbb51",
            Version(20, 10, 12, build="459d0dfbbb51", release="ce"),
        ),
        (
            "Docker version 20.10.16, build aa7e414",
            Version(20, 10, 16, build="aa7e414"),
        ),
        (
            "Docker version 1.13.1, build 7d71120/1.13.1",
            Version(1, 13, 1, build="7d71120/1.13.1"),
        ),
        (
            "Docker version 20.10.17+azure-1, build 100c70180fde3601def79a59cc3e996aa553c9b9",
            Version(
                20,
                10,
                17,
                release="azure-1",
                build="100c70180fde3601def79a59cc3e996aa553c9b9",
            ),
        ),
    ],
)
def test_docker_version_extract(stdout: str, ver: Version):
    assert _get_docker_version(stdout) == ver


@pytest.mark.parametrize(
    "stdout,ver",
    [
        ("podman version 3.0.1", Version(3, 0, 1)),
        ("podman version 3.4.4", Version(3, 4, 4)),
        ("podman version 1.6.4", Version(1, 6, 4)),
        ("podman version 4.0.2", Version(4, 0, 2)),
    ],
)
def test_podman_version_extract(stdout: str, ver: Version):
    assert _get_podman_version(stdout) == ver


def test_container_runtime_parsing(host, container_runtime: OciRuntimeBase):
    """Test that we can recreate the output of
    :command:`$container_runtime_binary --version` from the attribute
    :py:attr:`~pytest_container.runtime.OciRuntimeBase.version`.

    """
    version_without_build = Version(
        major=container_runtime.version.major,
        minor=container_runtime.version.minor,
        patch=container_runtime.version.patch,
    )
    version_string = (
        host.run_expect([0], f"{container_runtime.runner_binary} --version")
        .stdout.strip()
        .lower()
    )

    assert (
        f"{container_runtime.runner_binary} version {version_without_build}"
        in version_string
    )

    if container_runtime.runner_binary == "docker":
        assert f"build {container_runtime.version.build}" in version_string


@pytest.mark.parametrize(
    "ver_str,expected_version",
    [
        ("1.2.3", Version(1, 2, 3)),
        ("65.8", Version(65, 8)),
        ("6", Version(6, 0)),
        ("2.7.8-55ubuntu~", Version(2, 7, 8, release="55ubuntu~")),
        ("2.8-16.fc37", Version(2, 8, release="16.fc37")),
        (
            "2.7.8-55ubuntu~ build 42",
            Version(2, 7, 8, release="55ubuntu~", build="42"),
        ),
        ("2.7.8 build 42", Version(2, 7, 8, build="42")),
    ],
)
def test_parse_valid_version_strings(ver_str: str, expected_version: Version):
    """Check that ``ver_str`` is parsed correctly into ``expected_version``."""
    assert Version.parse(ver_str) == expected_version


_INVALID_1 = "2.5 not-build 46"
_INVALID_2 = "16.84 build but with too much text"
_INVALID_3 = "asdf"


@pytest.mark.parametrize(
    "ver_str,exception,exception_text",
    [
        (
            _INVALID_1,
            ValueError,
            f"Invalid version string: {_INVALID_1}",
        ),
        (
            _INVALID_2,
            ValueError,
            f"Invalid version string: {_INVALID_2}",
        ),
        (_INVALID_3, ValueError, f"Invalid version string: {_INVALID_3}"),
    ],
)
def test_parse_invalid_version_strings(
    ver_str: str, exception, exception_text: str
):
    """Check that parsing the version string `ver_str` raises the supplied
    exception type and includes the provided ``exception_text``.

    """
    with pytest.raises(exception) as exc_ctx:
        Version.parse(ver_str)
    assert exception_text in str(exc_ctx.value)
