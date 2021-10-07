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

A simple `pytest <https://pytest.org>`_ plugin to test container images with
python and `testinfra <https://testinfra.readthedocs.io/en/latest/>`_.

This module provides a set of fixtures and helper functions to ease testing of
container images via `testinfra
<https://testinfra.readthedocs.io/en/latest/>`_. For example, the `container`
fixture will automatically create and launch a previously defined container:

.. code-block:: python

   LEAP = Container(url="registry.opensuse.org/opensuse/leap:latest")

   @pytest.mark.parametrize("container", [LEAP], indirect=["container"])
   def test_leap(container):
       assert container.connection.file("/etc/os-release").exists


In the above example we created a
:py:class:`pytest_container.container.Container` object which is just a
container that is directly pulled from `registry.opensuse.org
<https://registry.opensuse.org/>`_. The `container` fixture then receives this
container via pytest's parametrization and returns a
:py:class:`pytest_container.container.ContainerData` to the test function. In
the test function itself, we can leverage testinfra to run some basic tests
inside the container itself.



License
-------

.. image:: https://app.fossa.com/api/projects/git%2Bgithub.com%2Fdcermak%2Fpytest_container.svg?type=large
           :target: https://app.fossa.com/projects/git%2Bgithub.com%2Fdcermak%2Fpytest_container?ref=badge_large
