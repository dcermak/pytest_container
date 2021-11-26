from pytest_container import add_extra_run_and_build_args_options
from pytest_container import auto_container_parametrize


def pytest_generate_tests(metafunc):
    auto_container_parametrize(metafunc)


def pytest_addoption(parser):
    add_extra_run_and_build_args_options(parser)
