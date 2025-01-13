Contributing
------------

You will need the following tools to start contributing code:

- Python 3.6 or later
- `tox <https://pypi.org/project/tox/>`_
- `podman <https://podman.io/>`_ or `docker <https://docs.docker.com/engine/>`_

Before submitting your changes, please ensure that:

- your code is properly formatted via :command:`tox -e format`
- it passes the test suite (:command:`tox -e py312`, or any other python
  version)
- the documentation can be build (:command:`tox -e doc`)
- it passes the mypy, pylint, twine and ruff checks (:command:`tox -e lint`)
