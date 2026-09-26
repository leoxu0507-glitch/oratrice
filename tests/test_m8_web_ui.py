"""Offline contract tests for the shipped same-origin Oratrice web UI."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from oratrice_api import create_api


WEB_ROOT = Path(__file__).resolve().parents[1] / "frontends" / "web"


def test_web_ui_and_assets_are_served_without_application_startup():
    factory_calls: list[dict[str, object]] = []

    def factory(**kwargs):
        factory_calls.append(dict(kwargs))
        raise AssertionError("static UI access must not construct the application")

    # Inject an inert externally-owned value so entering TestClient's
    # lifespan cannot exercise the normal lazy application factory.  Static
    # asset access should remain independent of the Core composition graph.
    api = create_api(application=object(), application_factory=factory)
    with TestClient(api, raise_server_exceptions=False) as client:
        root = client.get("/ui")
        entry = client.get("/ui/")
        script = client.get("/ui/app.js")
        styles = client.get("/ui/styles.css")

    assert root.status_code in {200, 307, 308}
    assert entry.status_code == 200
    assert "Oratrice" in entry.text
    assert script.status_code == 200
    assert "ENDPOINTS" in script.text
    assert styles.status_code == 200
    assert "--bg" in styles.text
    assert factory_calls == []


def test_web_ui_javascript_is_same_origin_and_has_no_unsafe_or_stateful_hooks():
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    absolute_paths = set(re.findall(r"[\"'](/[^\"']*)[\"']", source))
    assert absolute_paths == {"/live", "/ready", "/chat"}
    assert "/route" not in source

    forbidden = (
        "innerHTML",
        "insertAdjacentHTML",
        "eval(",
        "localStorage",
        "sessionStorage",
        "console.",
    )
    for token in forbidden:
        assert token not in source

    for filename in ("index.html", "app.js", "styles.css"):
        content = (WEB_ROOT / filename).read_text(encoding="utf-8")
        assert not re.search(r"(?<!\d)(?:4000|8080|8082|8090)(?!\d)", content)
        assert "gpt-oss" not in content.lower()
        assert "qwen" not in content.lower()
        assert "deepseek" not in content.lower()
