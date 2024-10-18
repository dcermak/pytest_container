Prerequisites
=============

`pytest_container` works with Python 3.6 and later and requires `pytest
<https://pytest.org/>`_. Additionally, for python 3.6, you'll need
the `dataclasses <https://pypi.org/project/dataclasses/>`_ module.

Tests leveraging `pytest_container` need to have access to a container
runtime. Currently the following ones are supported:

- `podman <https://podman.io/>`_ and `buildah <https://buildah.io/>`_
- `docker <https://www.docker.com/>`_

.. _runtime selection rules:

The fixtures will default to using :command:`podman` (and optionally
:command:`buildah` for building or fallback to :command:`podman`), if they are
installed and work, otherwise :command:`docker` will be used. You can also
customize which runtime will be used via the environment variable
``CONTAINER_RUNTIME`` [#]_.

.. [#] When running tests with `tox <http://tox.readthedocs.org/>`_ keep in mind
       to put the environment variable ``CONTAINER_RUNTIME`` into the
       ``passenv`` list.
