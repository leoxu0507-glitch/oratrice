from typing import Any

from entities.resource import Resource


class Runtime(Resource):
    """Configuration for an executable model runtime."""

    def __init__(
        self,
        resource_id: str,
        name: str,
        executable: str | None = None,
        working_dir: str | None = None,
        args: list[Any] | tuple[Any, ...] | None = None,
        runtime_type: str | None = None,
        type: str | None = None,
        path: str | None = None,
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
        self.executable = executable
        self.working_dir = working_dir
        self.args = list(args) if args is not None else []
        self.runtime_type = runtime_type if runtime_type is not None else type
        # ``type`` is the spelling used by the existing YAML configuration.
        self.type = self.runtime_type
