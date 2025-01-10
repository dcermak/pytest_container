# pylint: disable=missing-function-docstring,missing-module-docstring
from pathlib import Path
from tempfile import gettempdir
from typing import Optional
from typing import Union

import pytest

from pytest_container import Container
from pytest_container import DerivedContainer
from pytest_container.container import ContainerLauncher
from pytest_container.container import ImageFormat
from pytest_container.runtime import OciRuntimeBase

from . import images


def test_derived_container_fails_without_base() -> None:
    """Ensure that a DerivedContainer cannot be instantiated without providing
    the base parameter.

    """
    with pytest.raises(ValueError) as val_err_ctx:
        DerivedContainer()

    assert str(val_err_ctx.value) == "A base container must be provided"


def test_get_base_of_derived_container() -> None:
    """Ensure that :py:meth:`~pytest_container.DerivedContainer.get_base`
    returns a :py:class:`Container` with the correct url.

    """
    url = "registry.foobar.org/my_img:latest"
    assert DerivedContainer(base=url).get_base() == Container(url=url)


def test_image_format() -> None:
    """Check that the string representation of the ImageFormat enum is correct."""
    assert str(ImageFormat.DOCKER) == "docker"
    assert str(ImageFormat.OCIv1) == "oci"


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
