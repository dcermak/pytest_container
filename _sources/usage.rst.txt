Usage Tips
==========

Adding global build, run or pod create arguments
------------------------------------------------

Sometimes it is necessary to customize the build, run or pod create parameters
of the container runtime globally, e.g. to use the host's network with docker
via ``--network=host``.

The :py:meth:`~pytest_container.container.ContainerBaseABC.prepare_container`
and :py:meth:`~pytest_container.container.ContainerBase.get_launch_cmd` methods
support passing such additional arguments/flags, but this is rather cumbersome
to use in practice. The ``*container*`` and ``pod*`` fixtures will therefore
automatically collect such additional arguments from the CLI that were passed
alongside the invocation of :command:`pytest` via the flags
``--extra-run-args``, ``--extra-build-args`` and
``--extra-pod-create-args``. This requires that you call the function
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


.. _controlling-image-pulling-behavior:

Controlling the image pulling behavior
--------------------------------------

``pytest_container`` will by default pull all container images from the defined
registry before launching containers for tests. This is to ensure that stale
images are not used by accident. The downside is, that tests take longer to
execute, as the container runtime will try to pull images before every test.

This behavior can be configured via the environment variable
``PULL_ALWAYS``. Setting it to ``0`` results in ``pytest_container`` relying on
the image cache and only pulling images if they are not present in the local
container storage.


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
:py:class:`~pytest_container.inspect.PortForwarding` instances that have the
property :py:attr:`~pytest_container.inspect.PortForwarding.host_port` set to
the port that ``pytest_container`` used to expose the container's port:

.. code-block:: python

   def test_port_forward_set_up(auto_container: ContainerData, host):
       res = host.run_expect(
           [0],
           f"curl localhost:{auto_container.forwarded_ports[0].host_port}",
       ).stdout.strip()


Setting up bind mounts or container volumes
-------------------------------------------

Some tests require that containers are launched with a bind mount or a container
volume attached to the container. While this can be achieved by adding the
respective mount command line arguments to
:py:attr:`~pytest_container.container.ContainerBase.extra_launch_args`, this
approach can quickly cause problems for concurrent tests (multiple containers
could be accessing the a volume at the same time) and poses challenges to
correctly clean up after the test runs and not leave stray volumes on the test
runner.

``pytest_container`` offers a convenience class for creating bind mounts and
container volumes via :py:class:`~pytest_container.container.BindMount` and
:py:class:`~pytest_container.container.ContainerVolume`, respectively. Instances
of either of these two classes can be added to the list
:py:attr:`~pytest_container.container.ContainerBase.volume_mounts` and will be
automatically configured and mounted into the respective container. The volumes
will also be cleaned up after the test run.

`Container volumes <https://docs.docker.com/storage/volumes/>`_ are created
using the :py:class:`~pytest_container.container.ContainerVolume` class. For the
most basic use case, provide a mount point in the container as a parameter to
the class. The ``*container*`` fixtures will then create a volume for you and
remove it after the test finishes. Additionally, they set the attribute
:py:attr:`~pytest_container.container.ContainerVolume.volume_id` to the id of
the newly created volume. You can also add mount flags to the volume via
:py:attr:`~pytest_container.container.ContainerVolumeBase.flags` and specify
whether the volume can be shared between containers or not via
:py:attr:`~pytest_container.container.ContainerVolumeBase.shared`. Note that the
:py:attr:`~pytest_container.container.ContainerVolumeBase.shared` attribute only
affects whether the SELinux mount flag ``Z`` or ``z`` will be used. It will not
result in the same volume being available to multiple containers.

`Bind mounts <https://docs.docker.com/storage/bind-mounts/>`_ are setup using
:py:class:`~pytest_container.container.BindMount`. The user can either specify
the :py:attr:`~pytest_container.container.BindMount.host_path` themselves with
the caveat that the directory must be created manually beforehand and your tests
must be able to handle concurrency (if using `pytest-xdist
<https://github.com/pytest-dev/pytest-xdist>`_). You can also omit the
:py:attr:`~pytest_container.container.BindMount.host_path` attribute, in case an
ephemeral directory is sufficient. Then the ``*container*`` fixtures will create
a unique temporary directory before the test and clean it up afterwards. The
path to the temporary director is accessible via the
:py:attr:`~pytest_container.container.BindMount.host_path` attribute during the
test. Flags can be added similarly to container volumes via
:py:attr:`~pytest_container.container.ContainerVolumeBase.flags` as well as
configuring sharing via
:py:attr:`~pytest_container.container.ContainerVolumeBase.shared`.

.. important::

   If you are using a bind mount with an existing directory on the host and want
   to run tests in parallel, then you **must** set the attribute
   :py:attr:`~pytest_container.container.ContainerVolumeBase.shared` to
   ``True``. Otherwise the directory will be relabeled to permit mounting from a
   single container only and will cause SELinux errors when two containers try
   to mount it at the same time.

The following snippet illustrates the usage of container volumes and bind
mounts:

.. code-block:: python

   NGINX = DerivedContainer(
       base="docker.io/library/nginx",
       containerfile=""" # snip
       EXPOSE 80
       """,
       volume_mounts=[
           BindMount(
               "/etc/nginx/templates",
               host_path="/path/to/templates"
           ),
           BindMount(
               "/etc/nginx/nginx.conf",
               host_path="/path/to/nginx.conf",
               flags=[VolumeFlag.READ_ONLY]
           ),
           ContainerVolume("/var/log/"),
           BindMount("/var/cache/nginx"),
       ]
   )

   @pytest.mark.parametrize("container_per_test", [NGINX], indirect=True)
   def check_nginx_cache(container_per_test: ContainerData):
       cache_on_host = container_per_test.container.volume_mounts[-1].host_path
       # cache_on_host is a temporary directory that was just created

       # var_log is a ContainerVolume and received a unique volume id
       # it will be destroyed once the test finishes
       var_log = container_per_test.container.volume_mounts[-2]
       assert var_log.volume_id


Create and manage pods
----------------------

Podman supports the creation of pods, a collection of containers that share the
same network and port forwards. ``pytest_container`` can automatically create
pods, launch all containers in the pod and remove the pod after the test via the
:py:func:`~pytest_container.plugin.pod` and
:py:func:`~pytest_container.plugin.pod_per_test` fixtures. Both fixtures require
to be parametrized with an instance of :py:class:`~pytest_container.pod.Pod` as
follows:

.. code-block:: python

   NGINX_PROXY = DerivedContainer(
       base="docker.io/library/nginx",
       containerfile=r"""RUN echo 'server { \n\
       listen 80; \n\
       server_name  localhost; \n\
       location / { \n\
           proxy_pass http://localhost:8000/; \n\
       } \n\
   }' > /etc/nginx/conf.d/default.conf
   """,
   )

   WEB_SERVER = DerivedContainer(
       base="registry.opensuse.org/opensuse/tumbleweed",
       containerfile="""
   RUN zypper -n in python3 && echo "Hello Green World!" > index.html
   ENTRYPOINT ["/usr/bin/python3", "-m", "http.server"]
   """,
   )

   PROXY_POD = Pod(
       containers=[WEB_SERVER, NGINX_PROXY],
       port_forwardings=[PortForwarding(container_port=80)],
   )

   @pytest.mark.parametrize("pod_per_test", [PROXY_POD], indirect=True)
   def test_proxy_pod(pod_per_test: PodData, host) -> None:
       assert pod_per_test.pod_id

       port_80_on_host = pod_per_test.forwarded_ports[0].host_port

.. important:

   Pods can only be created via :command:`podman`. The
   :py:func:`~pytest_container.plugin.pod` and
   :py:func:`~pytest_container.plugin.pod_per_test` fixtures will therefore
   automatically skip the tests if the selected container runtime is not
   :command:`podman`.


Entrypoint, launch command and stop signal handling
---------------------------------------------------

``pytest_container`` will by default (when
:py:attr:`~pytest_container.container.ContainerBase.entry_point` is set to
:py:attr:`~pytest_container.container.EntrypointSelection.AUTO`) try to
automatically pick the correct entrypoint for your container:

1. If :py:attr:`~pytest_container.container.ContainerBase.custom_entry_point` is
   set, then that binary will be used.

2. If the container image defines a ``CMD`` or an ``ENTRYPOINT``, then it will
   be launched without specifying an entrypoint.

3. Use :file:`/bin/bash` otherwise.


This behavior can be customized via the attribute
:py:attr:`~pytest_container.container.ContainerBase.entry_point` to either force
the entrypoint to :file:`/bin/bash`
(:py:attr:`~pytest_container.container.EntrypointSelection.BASH`) or launch the
image without specifying one
(:py:attr:`~pytest_container.container.EntrypointSelection.IMAGE`).


The container under test is launched by default with no further
arguments. Additional arguments can be passed to the entrypoint via the
parameter
:py:attr:`~pytest_container.container.ContainerBase.extra_entrypoint_args`. The
list of arguments/parameters is appended to the container launch command line
after the container image.


Changing the container entrypoint can have a catch with respect to the
``STOPSIGNAL`` defined by a container image. Container images that have
non-shell entry points sometimes use a different signal for stopping the main
process. However, a shell might not react to such a signal at all. This is not a
problem, as the container runtime will eventually resort to sending ``SIGKILL``
to the container if it does not stop. But it slows the tests needlessly down, as
the container runtime waits for 10 seconds before sending
``SIGKILL``. Therefore, ``pytest_container`` sets the stop signal to
``SIGTERM``, if used :file:`/bin/bash` as the entrypoint.
