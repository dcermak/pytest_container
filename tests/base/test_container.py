from pytest_container import Container
from pytest_container import DerivedContainer

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
