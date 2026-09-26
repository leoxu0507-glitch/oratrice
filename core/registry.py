from collections.abc import Mapping
from pathlib import Path
from typing import Any, Type

import yaml

from entities.app import App
from entities.model import Model
from entities.provider import Provider
from entities.resource import Resource
from entities.runtime import Runtime
from entities.service import Service


class ResourceRegistry:
    """Load typed resources and provide deterministic lookup operations."""

    _CATEGORY_ALIASES = {
        "runtime": "runtimes",
        "runtimes": "runtimes",
        "model": "models",
        "models": "models",
        "provider": "providers",
        "providers": "providers",
        "service": "services",
        "services": "services",
        "app": "apps",
        "apps": "apps",
        "system": "system",
        "systems": "system",
    }
    _CATEGORY_TYPES: dict[str, Type[Resource]] = {
        "runtimes": Runtime,
        "models": Model,
        "providers": Provider,
        "services": Service,
        "apps": App,
        "system": Resource,
    }

    def __init__(self):
        # ``resources`` remains a category -> list mapping for existing
        # consumers.  ``_by_id`` gives stable, O(1) global lookups.
        self.resources: dict[str, list[Resource]] = {}
        self._by_id: dict[str, Resource] = {}

    @classmethod
    def _canonical_category(cls, category: Any) -> str:
        key = str(category).strip().lower()
        return cls._CATEGORY_ALIASES.get(key, key)

    @staticmethod
    def _items(raw_items: Any, category: str):
        if raw_items is None:
            return ()
        if isinstance(raw_items, Mapping):
            return raw_items.items()
        if isinstance(raw_items, list):
            return enumerate(raw_items)
        raise ValueError(
            f"Resources category '{category}' must be a mapping or list"
        )

    def load(self, config_path: str | Path):
        config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)

        if data is None:
            data = {}
        if not isinstance(data, Mapping):
            raise ValueError("Resource config root must be a mapping")

        raw_resources = data.get("resources", {})
        if raw_resources is None:
            raw_resources = {}
        if not isinstance(raw_resources, Mapping):
            raise ValueError("'resources' must be a mapping")

        loaded: dict[str, list[Resource]] = {}
        by_id: dict[str, Resource] = {}

        for raw_category, raw_items in raw_resources.items():
            category = self._canonical_category(raw_category)
            target_type = self._CATEGORY_TYPES.get(category, Resource)
            category_resources = loaded.setdefault(category, [])

            for item_key, raw_info in self._items(raw_items, category):
                if raw_info is None:
                    raw_info = {}
                if not isinstance(raw_info, Mapping):
                    raise ValueError(
                        f"Resource '{item_key}' in '{category}' must be a mapping"
                    )

                info = dict(raw_info)
                resource_id = info.pop("id", None)
                if resource_id is None or not str(resource_id).strip():
                    raise ValueError(
                        f"Resource '{item_key}' in '{category}' is missing a non-empty 'id'"
                    )
                resource_id = str(resource_id)
                if resource_id in by_id:
                    previous = by_id[resource_id]
                    raise ValueError(
                        f"Duplicate resource id '{resource_id}' "
                        f"(already used by {previous.__class__.__name__})"
                    )

                name = info.pop("name", None) or resource_id
                path = info.pop("path", None)
                enabled = info.pop("enabled", True)
                resource = target_type(
                    resource_id=resource_id,
                    name=name,
                    path=path,
                    enabled=enabled,
                    **info,
                )
                category_resources.append(resource)
                by_id[resource_id] = resource

        # Commit only after the complete file validates.  A failed reload does
        # not leave callers with a partially replaced registry.
        self.resources = loaded
        self._by_id = by_id
        return self

    def list_category(self, category: str) -> list[Resource]:
        return list(self.resources.get(self._canonical_category(category), ()))

    def list_models(self):
        return self.list_category("models")

    def list_runtimes(self):
        return self.list_category("runtimes")

    def list_providers(self):
        return self.list_category("providers")

    def list_services(self):
        return self.list_category("services")

    def list_apps(self):
        return self.list_category("apps")

    def list_system(self):
        return self.list_category("system")

    def get(self, resource_id: str, category: str | None = None):
        key = str(resource_id)
        if category is None:
            return self._by_id.get(key)

        for resource in self.list_category(category):
            if resource.id == key:
                return resource
        return None

    def exists(self, resource_id: str, category: str | None = None) -> bool:
        return self.get(resource_id, category=category) is not None

    def print_summary(self):
        print("\n========== Oratrice Resource Registry ==========\n")

        for category, items in self.resources.items():
            print(f"[{category.upper()}]")
            if not items:
                print("  (empty)\n")
                continue

            for resource in items:
                status = "[OK]" if resource.enabled else "[OFF]"
                print(f"  {status} {resource.name}")
                print(f"      id : {resource.id}")
            print()

        print("===============================================\n")
