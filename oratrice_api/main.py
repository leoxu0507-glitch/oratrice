"""Uvicorn entry point for the optional Oratrice API process."""

from __future__ import annotations

import os
from pathlib import Path

from .app import create_api
from providers.external_readiness import ExternalEndpointReadinessProvider


# Uvicorn convention (`oratrice_api.main:app`); retain `api` as a friendly
# alias for callers that use the factory's terminology.  The launcher starts
# services from the live profile, so the API must compose the same graph.  An
# explicit environment override keeps standalone/development deployments
# configurable without embedding provider/model identities in Python.
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "profiles" / "live.yaml"
)
CONFIG_PATH = os.environ.get("ORATRICE_CONFIG", str(DEFAULT_CONFIG_PATH))
READINESS_PROVIDER = ExternalEndpointReadinessProvider(CONFIG_PATH)
app = create_api(config_path=CONFIG_PATH, readiness_provider=READINESS_PROVIDER)
api = app


__all__ = [
    "CONFIG_PATH",
    "DEFAULT_CONFIG_PATH",
    "READINESS_PROVIDER",
    "app",
    "api",
    "create_api",
]
