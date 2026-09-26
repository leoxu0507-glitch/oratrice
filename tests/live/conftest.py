"""Defence-in-depth exclusion for explicit live checks.

The root ``pytest.ini`` excludes this directory by default.  This local
configuration also keeps an accidental ``pytest tests/live`` invocation from
collecting files named ``test_*.py`` unless a developer intentionally edits
the command/configuration for a release check.
"""

collect_ignore_glob = ["test_*.py"]
