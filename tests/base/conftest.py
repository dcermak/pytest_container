from pytest_container import auto_container_parametrize


def pytest_generate_tests(metafunc):
    auto_container_parametrize(metafunc)
