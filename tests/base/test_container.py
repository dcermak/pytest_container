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
    with pytest.raises(ValueError) as ve:
        DerivedContainer()

    assert str(ve.value) == "A base container must be provided"


def test_get_base_of_derived_container():
    url = "registry.foobar.org/my_img:latest"
    assert DerivedContainer(base=url).get_base() == Container(url=url)


def test_image_format():
    assert str(ImageFormat.DOCKER) == "docker"
    assert str(ImageFormat.OCIv1) == "oci"


def test_local_image_url():
    url = "docker.io/library/iDontExistHopefully/bazbarf/something"
    cont = Container(url=f"containers-storage:{url}")
    assert cont.local_image
    assert cont.url == url
    # prepare must not call `$runtime pull` as that would fail
    cont.prepare_container(Path("."), [])
