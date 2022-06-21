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
