from typing import Any

from entities.resource import Resource


class Model(Resource):
    """Configuration for a model and the runtime that serves it."""

    def __init__(
        self,
        resource_id: str,
        name: str,
        runtime: str | None = None,
        runtime_id: str | None = None,
        path: str | None = None,
        ctx_size: int | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
        **extra: Any,
    ):
        super().__init__(
            resource_id=resource_id,
            name=name,
            path=path,
            enabled=enabled,
            metadata=metadata,
            **extra,
        )
        self.runtime = runtime if runtime is not None else runtime_id
        # Alias used by callers that prefer an explicit relationship name.
        self.runtime_id = self.runtime
        self.ctx_size = ctx_size
