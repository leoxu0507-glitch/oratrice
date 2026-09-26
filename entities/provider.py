from typing import Any

from entities.resource import Resource


class Provider(Resource):
    """Provider configuration.

    The registry only stores this configuration object.  Provider execution
    remains the responsibility of the provider layer.
    """

    def __init__(
        self,
        resource_id: str,
        name: str,
        provider_type: str | None = None,
        type: str | None = None,
        base_url: str | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        models: list[Any] | tuple[Any, ...] | str | None = None,
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
        self.provider_type = provider_type if provider_type is not None else type
        # ``type`` is retained because it is the conventional config key.
        self.type = self.provider_type
        self.base_url = base_url if base_url is not None else endpoint
        self.endpoint = self.base_url
        self.api_key = api_key
        self.model = model
        if models is None or isinstance(models, str):
            self.models = models
        else:
            self.models = list(models)
