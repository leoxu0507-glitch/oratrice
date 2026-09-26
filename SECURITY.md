# Security Policy

## Supported versions

Security fixes are currently applied to the latest code on `main`. The project
is pre-1.0, so older snapshots are not maintained as separate security lines.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's
private vulnerability reporting or a private repository security advisory when
available. If neither option is available, contact the primary maintainer via
the GitHub profile listed in `AUTHORS.md` before sharing technical details.

Include a concise impact statement, affected version or commit, reproduction
steps, and any suggested mitigation. Remove credentials, private prompts,
model data, local usernames, and unrelated system information from evidence.

## Security expectations

- Default services bind to `127.0.0.1` and are not intended for direct public
  network exposure.
- Cloud use is opt-in; local-only routing must not silently fall back to cloud.
- Secrets belong in process environment variables or a secret manager and must
  not be persisted in repository configuration or logs.
- Model weights, runtime binaries, local logs, and generated output are not part
  of the source distribution.

