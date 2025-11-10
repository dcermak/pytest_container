# pylint: disable=missing-function-docstring,missing-module-docstring
from pathlib import Path
from tempfile import gettempdir
from typing import Any
from typing import Optional
from typing import Union

import pytest

from pytest_container import Container
from pytest_container import DerivedContainer
from pytest_container.container import ContainerBase
from pytest_container.container import ContainerLauncher
from pytest_container.container import EntrypointSelection
from pytest_container.container import ImageFormat
from pytest_container.runtime import OciRuntimeBase

from . import images


def test_get_base_of_derived_container() -> None:
    """Ensure that :py:meth:`~pytest_container.DerivedContainer.get_base`
    returns a :py:class:`Container` with the correct url.

    """
    url = "registry.foobar.org/my_img:latest"
    assert DerivedContainer(base=url).get_base() == Container(url=url)


@pytest.mark.parametrize(
    "ctr1, ctr2",
    [
        (images.LEAP, images.LEAP),
        (Container(url=images.LEAP_URL), images.LEAP),
    ],
)
def test_equality(ctr1: ContainerBase, ctr2: ContainerBase) -> None:
    assert ctr1 == ctr2
    assert not ctr1 != ctr2


@pytest.mark.parametrize(
    "ctr1, ctr2",
    [
        (images.LEAP, images.LEAP_WITH_MAN),
        (Container(url=images.LEAP_URL), "foobar"),
        (
            images.LEAP,
            Container(
                url=images.LEAP_URL, entry_point=EntrypointSelection.BASH
            ),
        ),
    ],
)
def test_ctr_inequality(ctr1: ContainerBase, ctr2: Any) -> None:
    assert ctr1 != ctr2
    assert not ctr1 == ctr2


def test_image_format() -> None:
    """Check that the string representation of the ImageFormat enum is correct."""
    assert str(ImageFormat.DOCKER) == "docker"
    assert str(ImageFormat.OCIv1) == "oci"


@pytest.mark.parametrize(
    "ctr",
    [
        images.LEAP,
        images.LEAP_WITH_MAN,
        images.LEAP_WITH_MAN,
        images.BUSYBOX,
        images.LEAP_WITH_MAN_AND_LUA,
        Container(url="containers-storage:foo.com/baz:latest"),
        images.LEAP_WITH_MARK,
    ],
)
def test_dict_can_be_passed_into_constructor(ctr: ContainerBase) -> None:
    assert type(ctr)(**ctr.dict()) == ctr


@pytest.mark.parametrize(
    "ctr, new_url, expected_url, expected_local_image",
    (
        (
            Container(url="foobar.com:latest"),
            "baz.com:latest",
            "baz.com:latest",
            False,
        ),
        (
            Container(url="foobar.com:latest"),
            "containers-storage:baz.com:latest",
            "baz.com:latest",
            True,
        ),
    ),
)
def test_url_setting(
    ctr: ContainerBase,
    new_url: str,
    expected_url: str,
    expected_local_image: bool,
) -> None:
    ctr.url = new_url
    assert ctr.url == expected_url
    assert ctr.local_image == expected_local_image


def test_local_image_url(container_runtime: OciRuntimeBase) -> None:
    url = "docker.io/library/iDontExistHopefully/bazbarf/something"
    cont = Container(url=f"containers-storage:{url}")
    assert cont.local_image
    assert cont.url == url
    # prepare must not call `$runtime pull` as that would fail
    cont.prepare_container(container_runtime, Path("."), [])


def test_lockfile_path(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    """Check that the attribute
    :py:attr:`~pytest_container.ContainerBase.lockfile_filename` does change by
    the container having the attribute
    :py:attr:`~pytest_container.ContainerBase.container_id` set.

    """
    cont = DerivedContainer(
        base=images.OPENSUSE_BUSYBOX_URL, containerfile="ENV BAZ=1"
    )
    original_lock_fname = cont.filelock_filename

    cont.prepare_container(container_runtime, pytestconfig.rootpath)
    assert cont.container_id, "container_id must not be empty"
    assert cont.filelock_filename == original_lock_fname


def test_lockfile_unique() -> None:
    cont1 = DerivedContainer(
        base=images.OPENSUSE_BUSYBOX_URL, containerfile=""
    )
    cont2 = DerivedContainer(
        base=images.OPENSUSE_BUSYBOX_URL, containerfile="ENV foobar=1"
    )
    assert cont1.filelock_filename != cont2.filelock_filename


def test_removed_lockfile_does_not_kill_launcher(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    """Test that the container launcher doesn't die if the container lockfile
    got removed by another thread.

    It can happen in certain scenarios that a ``Container`` is launched from two
    concurrently running test functions. These test functions will use the same
    lockfile. A nasty data race can occur, where both test functions unlock the
    lockfile nearly at the same time, but then only one of them can succeed in
    removing it and the other test inadvertently fails. This is a regression
    test, that such a situation is tolerated and doesn't cause a failure.

    In this test we create a singleton container where we utilize that the
    lockfile is removed in ``__exit__()``. We hence already delete the lockfile
    in the ``with`` block and provoke a failure in ``__exit__()``.

    See also https://github.com/dcermak/pytest_container/issues/232.

    """
    cont = Container(url=images.LEAP_URL, singleton=True)

    with ContainerLauncher.from_pytestconfig(
        cont, container_runtime, pytestconfig
    ) as launcher:
        launcher.launch_container()

        lockfile_abspath = Path(gettempdir()) / cont.filelock_filename
        assert lockfile_abspath.exists

        lockfile_abspath.unlink()


def test_derived_container_build_tag(
    container_runtime: OciRuntimeBase, pytestconfig: pytest.Config
) -> None:
    cont = DerivedContainer(base=images.OPENSUSE_BUSYBOX_URL)
    cont.prepare_container(container_runtime, pytestconfig.rootpath)
    assert cont._build_tag == images.OPENSUSE_BUSYBOX_URL


@pytest.mark.parametrize(
    "container_instance,url",
    [
        (Container(url=images.LEAP_URL), images.LEAP_URL),
        (images.LEAP_WITH_MAN, images.LEAP_URL),
        (images.LEAP_WITH_MAN_AND_LUA, images.LEAP_URL),
        (Container(url="containers-storage:foobar"), None),
        (
            DerivedContainer(base=Container(url="containers-storage:foobar")),
            None,
        ),
    ],
)
def test_baseurl(
    container_instance: Union[DerivedContainer, Container], url: Optional[str]
) -> None:
    assert container_instance.baseurl == url


def test_url_does_not_loose_containers_storage_part():
    local_prefix = "containers-storage"
    path = f"this/is/a/fake/image/with/{local_prefix}:latest"
    ctr = Container(url=f"{local_prefix}:{path}")
    assert ctr.local_image
    assert ctr.url == path
