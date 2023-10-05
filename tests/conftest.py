# pylint: disable=missing-function-docstring,missing-module-docstring
from typeguard import typechecked

try:
    from typeguard.importhook import install_import_hook
except ImportError:
    from typeguard import install_import_hook

from pytest_container import add_extra_run_and_build_args_options
from pytest_container import add_logging_level_options
from pytest_container import auto_container_parametrize
from pytest_container import set_logging_level_from_cli_args


def pytest_runtest_call(item):
    # Decorate every test function [e.g. test_foo()] with typeguard's
    # typechecked() decorator.
    test_func = getattr(item, "obj", None)
    if test_func is not None:
        setattr(item, "obj", typechecked(test_func))


def pytest_generate_tests(metafunc):
    auto_container_parametrize(metafunc)


def pytest_addoption(parser):
    add_extra_run_and_build_args_options(parser)
    add_logging_level_options(parser)


def pytest_configure(config):
    set_logging_level_from_cli_args(config)
    install_import_hook("pytest_container")
