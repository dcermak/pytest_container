# pylint: disable=missing-function-docstring,missing-module-docstring
from pytest_container.container import Container
from pytest_container.container import ContainerData

from .images import LEAP_URL

ENV = {"SOMETHING": "42", "ANOTHER": "value", "dist": "/bin/dist"}
LEAP_WITH_ENV = Container(
    url=LEAP_URL,
    extra_environment_variables=ENV,
)


CONTAINER_IMAGES = [LEAP_WITH_ENV]


def test_environment_variables_present(auto_container: ContainerData):
    for env_var_name, env_var_val in ENV.items():
        assert (
            auto_container.connection.run_expect(
                [0], f"echo ${env_var_name}"
            ).stdout.strip()
            == env_var_val
        )
