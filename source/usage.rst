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

