Contributing
------------

You will need the following tools to start contributing code:

- Python 3.6 or later
- `poetry <https://python-poetry.org/>`_
- `nox <https://nox.thea.codes/en/stable/index.html>`_
- `nox-poetry <https://nox-poetry.readthedocs.io/>`_

Before submitting your changes, please ensure that:

- your code is properly formatted via :command:`nox -s format`
- it passes the test suite (:command:`nox -s py`)
- the documentation can be build (:command:`nox -s doc`)
- it passes the mypy and pylint checks (:command:`nox -s lint`)
