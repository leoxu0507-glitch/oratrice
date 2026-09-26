from pathlib import Path
from collections.abc import Mapping
from typing import Any


class Resource:
    """Base class shared by all resources loaded by Oratrice."""

    def __init__(
        self,
        resource_id: str,
        name: str,
        path: str | Path | None = None,
        enabled: bool = True,
        metadata: Mapping[str, Any] | None = None,
        **extra: Any,
    ):
        self.id = resource_id
        # ``resource_id`` is kept as an alias for callers that use the
        # constructor's argument name rather than the historical ``id``.
        self.resource_id = resource_id
        self.name = name
        self.path = Path(path) if path else None
        self.enabled = enabled

        # Unknown configuration keys remain available through this extension
        # point instead of being discarded by typed resource constructors.
        self.metadata = dict(metadata or {})
        self.metadata.update(extra)

    def get(self, key: str, default: Any = None) -> Any:
        """Return a configured field while preserving the old ``get`` API."""

        if hasattr(self, key):
            return getattr(self, key)
        return self.metadata.get(key, default)

    def __str__(self) -> str:
        return f"{self.name} ({self.id})"

    def __repr__(self) -> str:
        return self.__str__()
