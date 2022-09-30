# pylint: disable=missing-function-docstring
from pathlib import Path
from pytest_container import Container
from pytest_container import DerivedContainer
from pytest_container.container import ImageFormat

import pytest


def test_container_default_entry_point_and_custom_one_set():
    with pytest.raises(ValueError) as ve:
        Container(
            url="ignore", default_entry_point=True, custom_entry_point="foobar"
        )
    assert "A custom entry point has been provided" in str(ve.value)


def test_derived_container_default_entry_point_and_custom_one_set():
    with pytest.raises(ValueError) as ve:
        DerivedContainer(
            base="foobar",
            default_entry_point=True,
            custom_entry_point="foobar",
        )
    assert "A custom entry point has been provided" in str(ve.value)


def test_derived_container_fails_without_base():
    """Ensure that a DerivedContainer cannot be instantiated without providing
    the base parameter.

    """
    with pytest.raises(ValueError) as ve:
        DerivedContainer()

    assert str(ve.value) == "A base container must be provided"


def test_get_base_of_derived_container():
    """Ensure that :py:meth:`~pytest_container.DerivedContainer.get_base`
    returns a :py:class:`Container` with the correct url.

    """
    url = "registry.foobar.org/my_img:latest"
    assert DerivedContainer(base=url).get_base() == Container(url=url)


def test_image_format():
    """Check that the string representation of the ImageFormat enum is correct."""
    assert str(ImageFormat.DOCKER) == "docker"
    assert str(ImageFormat.OCIv1) == "oci"


def test_local_image_url():
    url = "docker.io/library/iDontExistHopefully/bazbarf/something"
    cont = Container(url=f"containers-storage:{url}")
    assert cont.local_image
    assert cont.url == url
    # prepare must not call `$runtime pull` as that would fail
    cont.prepare_container(Path("."), [])


def test_lockfile_path(pytestconfig: pytest.Config):
    """Check that the attribute
    :py:attr:`~pytest_container.ContainerBase.lockfile_filename` does change by
    the container having the attribute
    :py:attr:`~pytest_container.ContainerBase.container_id` set.

    """
    cont = DerivedContainer(base="docker.io/library/busybox", containerfile="")
    original_lock_fname = cont.filelock_filename

    cont.prepare_container(pytestconfig.rootpath)
    assert cont.container_id, "container_id must not be empty"
    assert cont.filelock_filename == original_lock_fname


def test_lockfile_unique():
    cont1 = DerivedContainer(
        base="docker.io/library/busybox", containerfile=""
    )
    cont2 = DerivedContainer(
        base="docker.io/library/busybox", containerfile="ENV foobar=1"
    )
    assert cont1.filelock_filename != cont2.filelock_filename
