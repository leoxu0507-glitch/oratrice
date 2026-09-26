"""Pytest defaults for the offline contract suite.

The repository is intentionally runnable from any working directory.  Adding
the project root to ``sys.path`` keeps imports stable without installing the
package or reading a developer's global configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
