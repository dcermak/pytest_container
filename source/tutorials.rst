Tutorials
=========


Getting started with ``pytest_container``
-----------------------------------------

.. note::

   The following tutorial demonstrates how to use
   ``pytest_container`` for a Python project and to test the project's
   Command-line interface.


The example uses `poetry <https://python-poetry.org/>`_ to manage the Python
dependencies. If the :file:`pyproject.toml` doesn't already exist, create it
using the :command:`poetry init` command.

Start by adding ``pytest_container`` as a development dependency:

.. code-block:: shell-session

   ❯ poetry add --group dev pytest_container


Add `pytest-xdist
<https://github.com/pytest-dev/pytest-xdist>`_, so that tests can be executed in
parallel:

.. code-block:: shell-session

   ❯ poetry add --group dev pytest-xdist


It is recommended to create a new directory :file:`tests` for your tests to keep
things tidy. Add an empty file called :file:`tests/__init__.py`. Create the
:file:`tests/conftest.py` file with the following contents:

.. code-block:: python

   from pytest_container import auto_container_parametrize


   def pytest_generate_tests(metafunc):
       auto_container_parametrize(metafunc)



The above code snippet ensures that the ``auto_container`` and
``auto_container_per_test`` fixtures work correctly (that is,
they use the images defined in ``CONTAINER_IMAGES``).


We can now implement the actual tests. We will create a simple smoke test where
we install the python wheel of our project inside a container and then check
that the installed command line utility works as expected. For that, we will
start out with the following :file:`Dockerfile`. There we base our image on
openSUSE Tumbleweed, install :command:`pip` into it, copy the wheel of our
python project into the image and install it in the container:

.. code-block:: Dockerfile

   FROM registry.opensuse.org/opensuse/tumbleweed

   RUN zypper -n in python3-pip
   COPY dist/*whl .
   RUN pip install *whl

Plug the :file:`Dockerfile` into ``pytest_container`` using the
:py:class:`~pytest_container.container.DerivedContainer` class as follows:

.. code-block:: python

   from textwrap import dedent
   from pytest_container import DerivedContainer


   TW_WITH_PKG = DerivedContainer(
       base="registry.opensuse.org/opensuse/tumbleweed",
       containerfile=dedent("""
       RUN zypper -n in python3-pip
       COPY dist/*whl .
       RUN pip install *whl
       """)
   )

Note that  the ``FROM`` line is omitted from the
:py:attr:`~pytest_container.container.DerivedContainer.containerfile` parameter,
as ``pytest_container`` includes it automatically.

Add the above snippet to a new file :file:`tests/test_cli.py`, and add
the following test function along with a global variable:

.. code-block:: python

   CONTAINER_IMAGES = [TW_WITH_PKG]

   def test_help_works(auto_container):
       res = auto_container.connection.run_expect([0], "my-binary --help")
       assert "My cool project" in res.stdout


The global variable ``CONTAINER_IMAGES`` instructs ``pytest_container`` to run
all test functions that use the ``auto_container`` or
``auto_container_per_test`` fixtures once for each image defined in that
list. This allows you to have a single file with multiple of tests that to be
executed inside multiple container images, thus avoiding the task of
parametrizing each of the test manually.

The test function receives a
:py:class:`~pytest_container.container.ContainerData` instance, where the
:py:attr:`~pytest_container.container.ContainerData.connection` attribute
provides a ``testinfra`` connection. The `run_expect
<https://testinfra.readthedocs.io/en/latest/modules.html#testinfra.host.Host.run_expect>`_
function is used to execute the binary and check that its exit code is
``0``. Afterwards, we check that a search string is in the standard output.

You can now execute this test via :command:`poetry run pytest`.
