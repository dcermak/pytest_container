Fixtures
========


Container class handling
------------------------

Containers are defined as instances of
:py:class:`~pytest_container.container.Container` and
:py:class:`~pytest_container.container.DerivedContainer`. These class instances
are then "passed" via pytest's parametrization to the fixtures which expose the
class instances via the
:py:attr:`~pytest_container.container.ContainerData.container` attribute.

The class instance exposed via this attribute is not guaranteed to be the
**exact same** object as the one with which this test function was parametrized!
The fixtures *might* only return copies, to prevent accidental mutation to
cross-influence tests.

For example, the following code is not guaranteed to work:

.. code-block:: python

   CTR = Container(url="registry.opensuse.org/opensuse/tumbleweed:latest")

   @pytest.mark.parametrize("container", [CTR], indirect=True)
   def test_tw_ids(container: ContainerData) -> None:
       # this might or might not fail
       assert id(CTR) == id(container.container)


Handling Healthcheck
--------------------

Container images can define a ``HEALTHCHECK`` option which the container runtime
will use to determine whether the container can be considered "healthy". The
container fixtures will by default infer the maximum time a healthcheck can be
run before the container would be considered unhealthy and use that as the
startup timeout. The user can provide their own timeout or disable it
completely.

In principle there is nothing else to do when it comes to managing containers
with a ``HEALTHCHECK``, the container will become available once it is healthy.

In certain cases it makes sense to not wait for the healthcheck or to
explicitly ignore it. In that case set the attribute
:py:attr:`~pytest_container.container.ContainerBase.healthcheck_timeout` to a
negative timedelta. The container launch fixtures will then treat this container
as if it had no ``HEALTHCHECK`` attribute at all.

It is also possible to check the container health via the container runtime
using the function
:py:meth:`~pytest_container.runtime.OciRuntimeABC.get_container_health`:

.. code-block:: python

   CONTAINER_WITH_HEALTHCHECK = DerivedContainer(
       base="registry.opensuse.org/opensuse/leap:latest",
       containerfile="HEALTHCHECK CMD true",
       healthcheck_timeout=timedelta(seconds=-1),  # don't check the container's health
   )

   @pytest.mark.parametrize("container", [CONTAINER_WITH_HEALTHCHECK], indirect=True)
   def test_leap(container, container_runtime):
       assert (
           container_runtime.get_container_health(container.container_id)
           == ContainerHealth.STARTING
       )

There is also a small catch when building containers with ``HEALTHCHECK``: this
directive is only supported for docker images. While this is the default with
:command:`docker`, :command:`buildah` will by default build images in the
``OCIv1`` format which does **not** support ``HEALTHCHECK``. To ensure that your
created container includes the ``HEALTHCHECK``, set the attribute
:py:attr:`~pytest_container.container.DerivedContainer.image_format` to
:py:attr:`~pytest_container.container.ImageFormat.DOCKER`.
