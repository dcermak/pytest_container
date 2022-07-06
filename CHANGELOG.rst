Next Release
------------

Breaking changes:

- ``ContainerBase.healtcheck_timeout_ms`` got renamed to
  py:attr:`~pytest_container.ContainerBase.healtcheck_timeout` and was changed
  as follows: it is now a `timedelta` with the default value being ``None`` and
  implies that ``pytest_container`` figures the maximum timeout out itself. If a
  positive timedelta is provided, then that timeout is used instead of the
  inferred default and if it is negative, then no timeout is applied.


Improvements and new features:

- Add support for automatically exposing ports in containers via the
  :py:attr:`ContainerBase.forwarded_ports` attribute: Container Images can now
  define which ports they want to publish automatically and let the
  `container_*` fixtures automatically find the next free port for them. This
  allows the user to launch multiple containers from Container Images exposing
  the same ports in parallel without marking them as ``singleton=True``.

Documentation:


Internal changes:


0.0.2 (01 February 2022)
------------------------

Breaking changes:


Improvements and new features:

 - Support healthcheck in Container images
 - Add support for internal logging and make the level user configurable
 - Allow for singleton container images
 - Add support for passing run & build arguments via the pytest CLI to podman/docker
 - Add support for adding environment variables into containers

Documentation:

 - treat unresolved references as errors
 - enable intersphinx

Internal changes:

 - Provide a better error message in auto_container_parametrize
 - Add support for using pytest.param instead of Container classes
