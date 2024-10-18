from typing import TYPE_CHECKING

# mypy will try to import cached_property but fail to find its types
# since we run mypy with the most recent python version, we can simply import
# cached_property from stdlib and we'll be fine
if TYPE_CHECKING:  # pragma: no cover
    from functools import cached_property
else:
    try:
        from functools import cached_property
    except ImportError:
        from cached_property import cached_property


__all__ = ["cached_property"]
