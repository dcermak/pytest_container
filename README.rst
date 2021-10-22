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
via pytest fixtures and `testinfra <https://testinfra.readthedocs.io/en/latest/>`_.

This module provides a set of fixtures and helper functions to ease testing of
container images leveraging `testinfra
<https://testinfra.readthedocs.io/en/latest/>`_. Assuming you want to
automatically spin up a container for a test, then the `container` will do
exactly that (plus it will cleanup after itself):

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
inside the container itself, e.g. check whether files are there, packages are
installed, etc.pp.

You can also customize the container to be used, e.g. build it from a
``Containerfile`` or specify an entry point:

.. code-block:: python

   BUSYBOX_WITH_ENTRYPOINT = Container(
       url="registry.opensuse.org/opensuse/busybox:latest",
       custom_entry_point="/bin/sh",
   )

   @pytest.mark.parametrize(
       "container", [BUSYBOX_WITH_ENTRYPOINT], indirect=["container"]
   )
   def test_custom_entry_point(container):
       container.connection.run_expect([0], "true")
