Usage Tips
==========

Adding global build and run arguments
-------------------------------------

Sometimes it is necessary to customize the build and run parameters of the
container runtime globally, e.g. to use the host's network with docker via
``--network=host``.

The :py:meth:`~pytest_container.container.ContainerBaseABC.prepare_container`
and :py:meth:`~pytest_container.container.ContainerBase.get_launch_cmd` methods
support passing such additional arguments/flags, but this is rather cumbersome
to use in practice. The ``*_container`` fixtures will therefore automatically
collect such additional arguments from the CLI that were passed alongside the
invocation of :command:`pytest` via the flags ``--extra-run-args`` and
``--extra-build-args``, respectively. This requires that you call the function
:py:func:`~pytest_container.helpers.add_extra_run_and_build_args_options` in the
``pytest_addoption`` function in your :file:`conftest.py` as follows:

.. code-block:: python
   :caption: conftest.py

   from pytest_container import add_extra_run_and_build_args_options


   def pytest_addoption(parser):
       add_extra_run_and_build_args_options(parser)


Then pass any extra arguments to your pytest invocation as follows:

.. code-block:: shell-session

   $ pytest --extra-build-args="--network=host" --extra-build-args="--no-cache"

Note that multiple arguments have to be passed individually as shown in the
example above.

**Caution:** The :py:class:`~pytest_container.build.MultiStageBuild` class also
supports additional build flags, but these are **not** collected
automatically. If you wish to use these, you have to inject them manually as
follows:

.. code-block:: python
   :caption: test_multistage.py

   from pytest_container import get_extra_build_args

   from test_data import MULTI_STAGE_BUILD


   def test_multistage_build(tmp_path, pytestconfig, container_runtime):
       MULTI_STAGE_BUILD.build(
           tmp_path,
           pytestconfig,
           container_runtime,
           # the flags are added here:
           extra_build_args=get_extra_build_args(pytestconfig),
       )


Configuring logging
-------------------

The plugin uses python's internal logging module to log debugging messages. You
can set the logging level in your own module by calling the function
:py:func:`~pytest_container.logging.set_internal_logging_level`. This needs to
happen before any tests are run, preferably in a pytest hook,
e.g. `pytest_configure
<https://docs.pytest.org/en/latest/reference/reference.html#_pytest.hookspec.pytest_configure>`_.

Sometimes it makes sense to allow the end users to configure the logging
level. You can accomplish this via the
:py:func:`~pytest_container.helpers.add_logging_level_options` function, which
adds an option to the pytest CLI flags. To actually implement this setting, call
:py:func:`~pytest_container.helpers.set_logging_level_from_cli_args` in a hook
function of your choice in :file:`conftest.py`, e.g. as follows:

.. code-block:: python
   :caption: conftest.py

   def pytest_addoption(parser):
       add_logging_level_options(parser)


   def pytest_configure(config):
       set_logging_level_from_cli_args(config)


Testing local images
--------------------

Sometimes it is necessary to run your tests against a locally build image
instead of a remote one. For such a case, you can use the following
syntax for the Container's url, which is inspired by skopeo's syntax:

.. code-block:: python

   local = Container(url="containers-storage:my/local/image/name")

A Container defined in this way can be used like any other Container
instance.


Copying files into containers
-----------------------------

Sometimes we need to have files available in the container image to e.g. execute
some script in an integration test. This can be achieved in two ways:


1. Copy the files at build time
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can include the desired files by creating a
:py:class:`~pytest_container.container.DerivedContainer` and insert the file
using the ``COPY`` or ``ADD`` instruction in the :file:`Dockerfile` (``COPY`` is
the recommended default nowadays, for a comparison of both instructions please
refer to e.g. `<https://phoenixnap.com/kb/docker-add-vs-copy>`_):

.. code-block:: python

   DIR = "path/to/testfile"
   FILE = "test.py"
   CDIR = "/dir/in/container"
   DOCKERFILE = f"""
   ...
   COPY {DIR}/{FILE} {CDIR}
   ...
   """
   CONTAINER1 = DerivedContainer(
     base=some_base_image,
     containerfile=DOCKERFILE,
   )

The path to :file:`test.py` is saved in the variable ``DIR`` and must be
relative to the root directory from which you execute pytest.

The object ``CONTAINER1`` can now be used as any other container:

.. code-block:: python

   @pytest.mark.parametrize(
       "container_per_test",
       [CONTAINER1],
       indirect=True
   )
   def test_my_script(container_per_test, ...):
       container_per_test.connection.run_expect(
           [0], f"python3 {CDIR}/{FILE}"
       )


2. Copy the files at runtime into the running container
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is also possible to copy files into a container via :command:`podman cp` or
:command:`docker cp`. In contrast to the first method, this has the disadvantage
that the copy has to be executed for every test and it cannot be cached during
the image build. However, it allows us to dynamically create files for each
test, which is not that easily possible with the first approach.

To successfully copy files, we need to undertake the following steps:

1. Request the following fixtures: any of the ``(auto)_container_per_test``,
   ``host``, ``container_runtime``.
2. Obtain the running container's hash.
3. Use :command:`podman|docker cp command`, via testinfra's host fixture.

The above steps could be implemented as follows:

.. code-block:: python

   DIR = "path/to/testfile"
   FILE = "test.py"
   CDIR = "/dir/in/container"

   def test_my_script(auto_container_per_test, host, container_runtime):
       host.run_expect(
         [0],
         f"{container_runtime.runner_binary} cp {DIR}/{FILE} {auto_container_per_test.container_id}:{CDIR}"
       )

Note that the same file location restrictions apply as when including the files
in the container image directly.
