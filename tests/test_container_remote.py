import pytest
from pytest_container.container import ContainerData

from .images import BUSYBOX


@pytest.mark.parametrize("container", [BUSYBOX], indirect=True)
def test_container_remote_check_output(container: ContainerData) -> None:
    """
    Test that `check_output` works as expected.
    """
    assert container.remote.check_output("uname") == "Linux"

    # Optionally, don't strip the output
    assert container.remote.check_output("uname", strip=False) == "Linux\n"


@pytest.mark.parametrize("container", [BUSYBOX], indirect=True)
def test_container_remote_file(container: ContainerData) -> None:
    """
    Test that `file` works as expected.
    """

    # Directory
    d = container.remote.file("/usr/share/licenses/busybox")
    assert d.exists
    assert d.is_directory
    assert not d.is_file
    assert d.listdir() == ["LICENSE"]
    with pytest.raises(
        ValueError, match="/usr/share/licenses/busybox is a directory"
    ):
        d.content_string

    # File
    f = container.remote.file("/usr/share/licenses/busybox/LICENSE")
    assert f.exists
    assert f.is_file
    assert not f.is_directory
    assert f.content_string.startswith(
        """\
--- A note on GPL versions

BusyBox is distributed under version 2 of the General Public License (included
in its entirety, below).  Version 2 is the only version of this license which
this version of BusyBox (or modified versions derived from this one) may be
distributed under.

------------------------------------------------------------------------
		    GNU GENERAL PUBLIC LICENSE
		       Version 2, June 1991
"""
    )

    # Missing file
    assert not container.remote.file(
        "/usr/share/licenses/busybox/MISSING"
    ).exists


@pytest.mark.parametrize("container", [BUSYBOX], indirect=True)
def test_container_remote_copy(container: ContainerData) -> None:
    """
    Test that `copy` works as expected.
    """
    with open("pyproject.toml", "r", encoding="utf-8") as f:
        expected_content = f.read()

    f = container.remote.copy("pyproject.toml", "/tmp/pyproject.toml")
    assert f.path == "/tmp/pyproject.toml"
    assert f.exists
    assert f.is_file
    assert f.content_string == expected_content
