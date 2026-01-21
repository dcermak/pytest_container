# pylint: disable=missing-function-docstring,missing-module-docstring
import pytest
from _pytest.mark import ParameterSet

from pytest_container.container import Container
from pytest_container.container import ContainerBase
from pytest_container.container import DerivedContainer
from pytest_container.pod import Pod
from tests.images import LEAP_URL
from tests.images import LEAP_WITH_MARK

DERIVED_ON_LEAP_WITH_MARK = DerivedContainer(base=LEAP_WITH_MARK)

SECOND_DERIVED_ON_LEAP = DerivedContainer(
    base=DERIVED_ON_LEAP_WITH_MARK, marks=[pytest.mark.othersecretmark]
)

INDEPENDENT_OTHER_LEAP = Container(
    url=LEAP_URL, marks=[pytest.mark.othersecretmark]
)

UNMARKED_POD = Pod(containers=[LEAP_WITH_MARK, INDEPENDENT_OTHER_LEAP])

MARKED_POD = Pod(
    containers=[LEAP_WITH_MARK, INDEPENDENT_OTHER_LEAP],
    marks=[pytest.mark.secretpodmark],
)


def test_marks() -> None:
    assert list(LEAP_WITH_MARK.marks) == [pytest.mark.secretleapmark]
    assert list(DERIVED_ON_LEAP_WITH_MARK.marks) == [
        pytest.mark.secretleapmark
    ]
    assert list(SECOND_DERIVED_ON_LEAP.marks) == [
        pytest.mark.othersecretmark,
        pytest.mark.secretleapmark,
    ]
    assert not DerivedContainer(
        base=LEAP_URL, containerfile="ENV HOME=/root"
    ).marks

    pod_marks = UNMARKED_POD.marks
    assert (
        len(pod_marks) == 2
        and pytest.mark.othersecretmark in pod_marks
        and pytest.mark.secretleapmark in pod_marks
    )

    pod_marks = MARKED_POD.marks
    assert (
        len(pod_marks) == 3
        and pytest.mark.othersecretmark in pod_marks
        and pytest.mark.secretleapmark in pod_marks
        and pytest.mark.secretpodmark in pod_marks
    )


@pytest.mark.parametrize(
    "ctr",
    [
        LEAP_WITH_MARK,
        DERIVED_ON_LEAP_WITH_MARK,
        SECOND_DERIVED_ON_LEAP,
        INDEPENDENT_OTHER_LEAP,
    ],
)
def test_container_is_pytest_param(ctr) -> None:
    assert isinstance(ctr, ParameterSet)
    assert isinstance(ctr, (Container, DerivedContainer))


@pytest.mark.parametrize(
    "ctr",
    [
        LEAP_WITH_MARK,
        DERIVED_ON_LEAP_WITH_MARK,
        SECOND_DERIVED_ON_LEAP,
        INDEPENDENT_OTHER_LEAP,
    ],
)
def test_container_is_truthy(ctr: ContainerBase) -> None:
    """Regression test that we don't accidentally inherit __bool__ from tuple
    and the container is False by default.

    """
    assert ctr


@pytest.mark.parametrize("pd", [MARKED_POD, UNMARKED_POD])
def test_pod_is_pytest_param(pd: Pod) -> None:
    assert isinstance(pd, ParameterSet)
    assert isinstance(pd, Pod)


@pytest.mark.parametrize("pd", [MARKED_POD, UNMARKED_POD])
def test_pod_is_truthy(pd: Pod) -> None:
    assert pd
