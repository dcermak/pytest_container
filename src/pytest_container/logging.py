import logging
from typing import Union


_logger = logging.getLogger("pytest_container")


def set_internal_logging_level(
    level: Union[str, int] = logging.INFO,
) -> None:
    """Set the verbosity of the internal logger to the specified level."""
    _logger.setLevel(level)
