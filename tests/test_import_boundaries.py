"""Static import-lint checks for the V1 architecture baseline.

These tests inspect source ASTs only; importing production modules is not
required.  That makes the dependency direction check safe in a machine with
no provider SDK, model, or network access.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRANSPORTS = {
    "httpx",
    "litellm",
    "requests",
    "socket",
    "subprocess",
    "urllib.request",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def test_frontends_depend_on_composition_root_not_transports():
    for relative in ("cli.py", "main.py"):
        imports = _imports(ROOT / relative)
        assert not any(_matches(name, "providers") for name in imports), relative
        assert not imports & FORBIDDEN_TRANSPORTS, (relative, imports & FORBIDDEN_TRANSPORTS)


def test_facade_has_only_provider_contract_imports():
    imports = _imports(ROOT / "core" / "ai_service.py")
    concrete = {
        name
        for name in imports
        if _matches(name, "providers") and name != "providers.base"
    }
    assert not concrete
    assert not imports & FORBIDDEN_TRANSPORTS


def test_router_and_entities_are_side_effect_free_boundaries():
    for path in (ROOT / "router").glob("*.py"):
        imports = _imports(path)
        assert not imports & FORBIDDEN_TRANSPORTS, path.name
        assert not any(_matches(name, "providers") for name in imports), path.name

    for path in (ROOT / "entities").glob("*.py"):
        imports = _imports(path)
        forbidden = {
            name
            for name in imports
            if any(_matches(name, prefix) for prefix in ("core", "providers", "config", "router"))
        }
        assert not forbidden, (path.name, forbidden)


def test_only_adapters_and_runtime_lifecycle_import_transports():
    # RuntimeManager is the lifecycle boundary and intentionally owns the
    # process/readiness imports.  Provider adapters own HTTP clients; all
    # other production packages must remain transport-free.
    production = [
        path
        for package in ("core", "router", "entities")
        for path in (ROOT / package).glob("*.py")
        if path.name != "runtime_manager.py"
    ]
    offenders = {
        str(path.relative_to(ROOT)): sorted(_imports(path) & FORBIDDEN_TRANSPORTS)
        for path in production
        if _imports(path) & FORBIDDEN_TRANSPORTS
    }
    assert not offenders, offenders
