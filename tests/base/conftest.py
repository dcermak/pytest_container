from pytest_container import add_extra_run_and_build_args_options
from pytest_container import add_logging_level_options
from pytest_container import auto_container_parametrize
from pytest_container import set_logging_level_from_cli_args


def pytest_generate_tests(metafunc):
    auto_container_parametrize(metafunc)


def pytest_addoption(parser):
    add_extra_run_and_build_args_options(parser)
    add_logging_level_options(parser)


def pytest_configure(config):
    set_logging_level_from_cli_args(config)
