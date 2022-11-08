# pylint: disable=missing-function-docstring,missing-module-docstring
from pytest_container import container_from_pytest_param
from pytest_container import container_to_pytest_param
from pytest_container import DerivedContainer
from pytest_container import get_extra_build_args
from pytest_container import MultiStageBuild
from pytest_container import OciRuntimeBase

import pytest

from tests.base.test_container_build import LEAP


LEAP_PARAM = pytest.param(LEAP)
LEAP_PARAM_2 = pytest.param(
    LEAP, marks=pytest.mark.skipif(False, reason="Don't skip this please :)")
)

TEMPLATE = """FROM $builder as builder
WORKDIR /src
RUN touch test.sh && chmod +x test.sh

FROM $runner as runner
WORKDIR /bin
COPY --from=builder /src/test.sh .
ENTRYPOINT ["/bin/test.sh"]
"""

CONTAINER_IMAGES = [LEAP_PARAM]


def test_multistage_with_param(
    tmp_path, pytestconfig: pytest.Config, container_runtime: OciRuntimeBase
):
    MultiStageBuild(
        containers={"builder": LEAP_PARAM, "runner": LEAP_PARAM_2},
        containerfile_template=TEMPLATE,
    ).build(
        tmp_path,
        pytestconfig.rootpath,
        container_runtime,
        extra_build_args=get_extra_build_args(pytestconfig),
    )


def test_multistage_build_invalid_param(tmp_path, pytestconfig: pytest.Config):
    with pytest.raises(ValueError):
        MultiStageBuild(
            containers={"runner": pytest.param()},
            containerfile_template=TEMPLATE,
        ).prepare_build(tmp_path, pytestconfig.rootpath)

    with pytest.raises(ValueError):
        MultiStageBuild(
            containers={"runner": pytest.param(1.0)},
            containerfile_template=TEMPLATE,
        ).prepare_build(tmp_path, pytestconfig.rootpath)


@pytest.mark.parametrize(
    "container_per_test", [container_to_pytest_param(LEAP)], indirect=True
)
def test_container_build_with_param(container_per_test):
    container_per_test.connection.run_expect([0], "true")


def test_auto_container_build_with_param(auto_container):
    auto_container.connection.run_expect([0], "true")


def test_container_to_pytest_param():
    param = container_to_pytest_param(LEAP)
    assert len(param.values) == 1 and param.values[0] == LEAP
    assert param.id == str(LEAP)
    assert len(param.marks) == 0

    skip_mark = pytest.mark.skip()
    param_with_marks = container_to_pytest_param(LEAP, marks=skip_mark)
    assert (
        len(param_with_marks.marks) == 1
        and param_with_marks.marks[0] == skip_mark
    )

    param_with_marks_2 = container_to_pytest_param(LEAP, marks=[skip_mark])
    assert (
        len(param_with_marks_2.marks) == 1
        and param_with_marks_2.marks[0] == skip_mark
    )


def test_container_from_pytest_param():
    assert container_from_pytest_param(container_to_pytest_param(LEAP)) == LEAP
    assert container_from_pytest_param(pytest.param(LEAP, 1, "a")) == LEAP
    assert container_from_pytest_param(LEAP) == LEAP

    derived = DerivedContainer(base=LEAP, containerfile="ENV foo=bar")
    assert (
        container_from_pytest_param(container_to_pytest_param(derived))
        == derived
    )
    assert container_from_pytest_param(derived) == derived

    with pytest.raises(ValueError) as ve:
        container_from_pytest_param(pytest.param(16, 45))
    assert "Invalid pytest.param values" in str(ve.value)
    assert "(16, 45)" in str(ve.value)
