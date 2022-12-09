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


Container Runtime version
-------------------------

Sometimes it is necessary to implement tests differently depending on the
version of the container runtime. The subclasses of
:py:class:`~pytest_container.runtime.OciRuntimeBase` have the property
:py:attr:`~pytest_container.runtime.OciRuntimeABC.version` which returns the
runtime version of the respective runtime, e.g. of :command:`podman`.

The returned object is an instance of
:py:class:`~pytest_container.runtime.Version` and supports comparison to for
instance skip certain tests:

.. code-block:: python

   @pytest.mark.skipif(
       get_selected_runtime().version < Version(4, 0),
       reason="This check requires at least Podman 4.0",
   )
   def test_modern_podman_feature(auto_container):
       # test $new_feature here


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


Exposing ports from containers
------------------------------

Exposing ports from containers is a tricky topic when tests are run in parallel,
as one can no longer set the port on the host because it would be used by
multiple containers. To remedy this, you can add the ports that shall be exposed
to the :py:attr:`~pytest_container.container.ContainerBase.forwarded_ports`
attribute as follows:

.. code-block:: python

   WEB_SERVER = DerivedContainer(
       containerfile="""
   # snip
   EXPOSE 8000
   """,
       forwarded_ports=[PortForwarding(container_port=8000)],
   )


When such a container image is requested via any of the ``container_*``
fixtures, then the resulting data passed into the test function will have the
attribute ``forwarded_ports`` set as well. This is a list of
:py:class:`~pytest_container.container.PortForwarding` instances that have the
property :py:attr:`~pytest_container.container.PortForwarding.host_port` set to
the port that ``pytest_container`` used to expose the container's port:

.. code-block:: python

   def test_port_forward_set_up(auto_container: ContainerData, host):
       res = host.run_expect(
           [0],
           f"curl localhost:{auto_container.forwarded_ports[0].host_port}",
       ).stdout.strip()


Setting up bind mounts
----------------------

Some tests require that containers are launched with a bind-mounted
volume. While this can be easily achieved by adding the bind mount command line
arguments to
:py:attr:`~pytest_container.container.ContainerBase.extra_launch_args`, this
approach can quickly cause problems for concurrent tests (multiple containers
could be accessing the a volume at the same time).

``pytest_container`` offers a convenience class for abstracting away the
creation of bind mounts via the
:py:attr:`~pytest_container.container.ContainerBase.volume_mounts` attribute
using the :py:class:`~pytest_container.container.ContainerVolume` class. It
allows you to automatically create temporary directories on the host, mounts
them in the container and cleans everything up after the test run.

The following snippet illustrates how to mount

.. code-block:: python

   NGINX = DerivedContainer(
       base="docker.io/library/nginx",
       containerfile=""" # snip
       EXPOSE 80
       """,
       volume_mounts=[
           ContainerVolume("/etc/nginx/templates", "/path/to/templates"),
           ContainerVolume("/etc/nginx/nginx.conf", "/path/to/nginx.conf", flags=[VolumeFlag.READ_ONLY]),
           ContainerVolume("/var/cache/nginx")
       ]
   )

   def check_nginx_cache(container_per_test: ContainerData):
       cache_on_host = container_per_test.container.volume_mounts.host_path
       # cache_on_host is a temporary directory that was just created
