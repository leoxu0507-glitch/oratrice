"""Compatibility import surface for the Oratrice composition root.

The implementation lives in :mod:`core.application`; this module keeps the
``core.bootstrap`` spelling available to frontends during the V1 migration.
"""

from core.application import (
    Application,
    ApplicationRegistry,
    bootstrap,
    bootstrap_application,
    build_application,
    create_application,
)

__all__ = [
    "Application",
    "ApplicationRegistry",
    "bootstrap",
    "bootstrap_application",
    "build_application",
    "create_application",
]
