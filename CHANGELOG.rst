Next Release
------------

Breaking changes:


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
