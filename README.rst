Pytest container
================

.. image:: https://github.com/dcermak/pytest_container/actions/workflows/ci.yml/badge.svg
           :target: https://github.com/dcermak/pytest_container/actions/workflows/ci.yml

.. image:: https://github.com/dcermak/pytest_container/actions/workflows/codeql-analysis.yml/badge.svg
           :target: https://github.com/dcermak/pytest_container/actions/workflows/codeql-analysis.yml

.. image:: https://codecov.io/gh/dcermak/pytest_container/branch/main/graph/badge.svg?token=D16Q2PGL67
           :target: https://codecov.io/gh/dcermak/pytest_container

.. image:: https://app.fossa.com/api/projects/git%2Bgithub.com%2Fdcermak%2Fpytest_container.svg?type=shield
           :target: https://app.fossa.com/projects/git%2Bgithub.com%2Fdcermak%2Fpytest_container?ref=badge_shield

.. image:: https://img.shields.io/pypi/v/pytest-container
           :alt: PyPI
           :target: https://pypi.org/project/pytest-container/

Find the latest documentation on `dcermak.github.io/pytest_container
<https://dcermak.github.io/pytest_container/>`_.

``pytest_container`` is a `pytest <https://pytest.org>`_ plugin
to test container images via pytest fixtures and `testinfra
<https://testinfra.readthedocs.io/en/latest/>`_. It takes care of all the boring
tasks, like spinning up containers, finding free ports and cleaning up after
tests, and allows you to focus on implementing the actual tests.

The plugin automates the following tasks:

- pull, launch, and stop containers
- build containers using a ``Dockerfile``
- wait for containers to become healthy before executing tests
- bind exposed container ports to free ports on the host
- mount volumes via temporary directories
- parallel test execution through pytest-xdist
- build dependent container images in the correct order
- run the same test on as many container images as necessary
- create, launch and destroy podman pods

``pytest_container`` provides four fixtures that give you everything you need
for testing containers. Spinning up a container image can be as simple as
instantiating a ``Container`` and parametrizing a test function with the
``container`` fixture:

.. code-block:: python

   TW = Container(url="registry.opensuse.org/opensuse/tumbleweed:latest")

   @pytest.mark.parametrize("container", [TW], indirect=["container"])
   def test_etc_os_release_present(container: ContainerData):
       assert container.connection.file("/etc/os-release").exists


The fixture automatically pulls and spins up the container, stops it and removes
it after the test is completed. Your test function receives an instance of
``ContainerData`` with the ``ContainerData.connection`` attribute. The
``ContainerData.connection`` attribute is a `testinfra
<https://testinfra.readthedocs.io/en/latest/>`_ connection object. It can be
used to run basic tests inside the container itself. For example, you can check
whether files are present, packages are installed, etc.


Use cases
---------

1. Run functional tests on operating system container images

2. Verify your software on multiple operating systems
