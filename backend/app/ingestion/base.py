"""The ``DataIngestion`` interface.

Every source (simulator, serial bridge, HTTP device) exposes the same shape: it
yields ``ReadingIn``-shaped dicts that the API then validates and persists
through one common path. Keeping sources behind this Protocol means the rest of
the system never special-cases where a reading came from — only ``source`` and
``simulated`` distinguish them, and both are stamped by the validator.
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable


@runtime_checkable
class DataIngestion(Protocol):
    """A source of readings.

    Implementations yield mappings matching the ``ReadingIn`` wire contract.
    ``source`` identifies the origin (``simulator`` | ``serial`` | ``http``) so
    the validator can stamp it onto each persisted reading.
    """

    source: str

    def readings(self) -> Iterator[dict[str, Any]]:
        """Yield ReadingIn-shaped dicts, one per emitted reading."""
        ...
