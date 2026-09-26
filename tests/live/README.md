# Explicit live checks

`tests/live/` is intentionally excluded by the ordinary pytest configuration.
The checks are driven by `scripts/live_verify.py`, which has three safe modes:

```powershell
# No profile, endpoint, credentials, image bytes, or network are needed.
python scripts/live_verify.py --help
python scripts/live_verify.py --dry-run --component runtime-gpt,core-text
python scripts/live_verify.py --fake --component qwen-vision
```

Only `--live` performs HTTP requests, and it never starts a runtime process.
Cloud checks additionally require `--allow-cloud`.  See
`docs/architecture/LIVE_TESTING.md` for profile fields, environment variable
overrides, redaction guarantees, and exit codes.
