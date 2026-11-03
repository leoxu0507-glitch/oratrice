"""Build a deterministic Oratrice source release from one committed Git tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit
import zipfile
import shutil


MANIFEST_NAME = "RELEASE-MANIFEST.json"
CHECKSUMS_NAME = "SHA256SUMS.txt"
ARCHIVE_SUFFIX = "-source.zip"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_ACCEPTANCE_BYTES = 1024 * 1024
REQUIRED_ENTRYPOINTS = frozenset({"Start-Oratrice.exe", "Start-Oratrice-Pet.cmd"})
SAFE_ENV_EXAMPLE = "config/secrets.example.env"
_VERSION = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_FULL_COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
_RUN_URL = re.compile(r"^/[^/]+/[^/]+/actions/runs/[0-9]+$")
_DENIED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        ".gateway-venv",
        ".cache",
        "cache",
        "caches",
        "venv",
        "env",
        "work",
        "log",
        "logs",
        "outputs",
        "build",
        "dist",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)
_DENIED_SUFFIXES = frozenset(
    {
        ".env",
        ".pem",
        ".key",
        ".pfx",
        ".p12",
        ".gguf",
        ".ggml",
        ".safetensors",
        ".onnx",
        ".pt",
        ".pth",
        ".weights",
        ".log",
        ".pid",
        ".tmp",
    }
)
_WINDOWS_RESERVED = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
_SECRET_NAME = re.compile(r"(?:^|[._-])(?:credential|credentials|secret|secrets)(?:[._-]|$)", re.IGNORECASE)
_SECRET_DATA_SUFFIXES = frozenset(
    {".json", ".json5", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".env", ".token", ".csv", ".tsv", ".xml"}
)
_SAFE_ENV_NAMES = frozenset({"ORATRICE_LITELLM_MASTER_KEY", "DEEPSEEK_API_KEY"})
_PRIVATE_VALIDATION_PATHS = frozenset(
    {
        "docs/validation/m7-03-litellm-audit.md",
        "docs/validation/m7-05-preflight.md",
        "docs/validation/m7-07a-gpt-smoke.md",
        "docs/validation/m7-07b-gemma-smoke.md",
        "docs/validation/m7-07c-litellm-smoke.md",
        "docs/validation/m7-07d-core-api-smoke.md",
        "docs/validation/m7-08-real-chain.md",
        "docs/validation/m7-release-summary.md",
    }
)


class ReleaseError(ValueError):
    """The requested revision or release artifact violates the package contract."""


class GitCommand(Protocol):
    def __call__(self, arguments: list[str], *, input_bytes: bytes | None = None) -> bytes: ...


class GitTree(Protocol):
    commit: str
    tree: str

    def files(self) -> Mapping[str, tuple[int, bytes, str]]: ...


class GitRepository:
    """Read committed blobs only; subprocess access is isolated to this CLI adapter."""

    def __init__(
        self,
        root: Path,
        *,
        command: GitCommand | None = None,
    ) -> None:
        self.root = root.resolve()
        self._command = command or self._run_git

    def _run_git(self, arguments: list[str], *, input_bytes: bytes | None = None) -> bytes:
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=self.root,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise ReleaseError("Git could not be started from the repository root.") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
            message = detail[0][:240] if detail else "Git command failed."
            raise ReleaseError(message)
        return result.stdout

    def read_tree(self, revision: str) -> Mapping[str, object]:
        if not _FULL_COMMIT.fullmatch(revision):
            raise ReleaseError("--commit must be a full 40-character commit SHA.")
        commit = self._command(["rev-parse", "--verify", f"{revision.lower()}^{{commit}}"]).decode().strip()
        if commit != revision.lower():
            raise ReleaseError("The selected commit SHA did not resolve exactly.")
        tree = self._command(["rev-parse", f"{commit}^{{tree}}"]).decode().strip()
        listing = self._command(["ls-tree", "-rz", "-r", "--full-tree", commit])

        records: list[tuple[str, int, str]] = []
        for record in listing.split(b"\0"):
            if not record:
                continue
            try:
                header, raw_path = record.split(b"\t", 1)
                mode_text, object_type, object_sha = header.decode("ascii").split(" ")
                path = raw_path.decode("utf-8", errors="strict")
                mode = int(mode_text, 8)
            except (UnicodeDecodeError, ValueError) as exc:
                raise ReleaseError("The selected Git tree has an invalid entry.") from exc
            if object_type != "blob" or mode not in {0o100644, 0o100755}:
                raise ReleaseError(f"Unsupported non-regular Git entry: {path!r}.")
            validate_source_path(path)
            records.append((path, mode, object_sha))

        batch = self._command(
            ["cat-file", "--batch"],
            input_bytes=("".join(f"{object_sha}\n" for _, _, object_sha in records)).encode("ascii"),
        )
        files = _parse_cat_file_batch(batch, records)
        return {"commit": commit, "tree": tree, "files": files}


def _parse_cat_file_batch(
    output: bytes,
    records: list[tuple[str, int, str]],
) -> dict[str, tuple[int, bytes, str]]:
    files: dict[str, tuple[int, bytes, str]] = {}
    cursor = 0
    for path, mode, expected_sha in records:
        separator = output.find(b"\n", cursor)
        if separator < 0:
            raise ReleaseError("Git returned an incomplete blob header.")
        try:
            object_sha, object_type, size_text = output[cursor:separator].decode("ascii").split(" ")
            size = int(size_text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ReleaseError("Git returned an invalid blob header.") from exc
        if object_sha != expected_sha or object_type != "blob" or size < 0:
            raise ReleaseError("Git returned a blob that does not match its tree entry.")
        start = separator + 1
        end = start + size
        if end >= len(output) or output[end:end + 1] != b"\n":
            raise ReleaseError("Git returned an incomplete blob body.")
        files[path] = (mode, output[start:end], object_sha)
        cursor = end + 1
    if cursor != len(output):
        raise ReleaseError("Git returned unexpected trailing blob data.")
    return files


def validate_source_path(path: str) -> None:
    """Reject unsafe ZIP members and paths containing local/private artifacts."""
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
        raise ReleaseError("A source path is empty or uses an invalid separator.")
    pure = PurePosixPath(path)
    parts = path.split("/")
    if pure.is_absolute() or pure.as_posix() != path or any(part in {"", ".", ".."} for part in parts):
        raise ReleaseError(f"Unsafe source path: {path!r}.")
    if ":" in path or any(char in part for part in parts for char in '<>"|?*'):
        raise ReleaseError(f"Source path is not safe to extract on Windows: {path!r}.")
    if any(part.endswith((" ", ".")) or _WINDOWS_RESERVED.fullmatch(part) for part in parts):
        raise ReleaseError(f"Source path is reserved on Windows: {path!r}.")

    lowered = [part.casefold() for part in parts]
    if any(part in _DENIED_PARTS for part in lowered):
        raise ReleaseError(f"Private or generated source path is excluded: {path!r}.")
    leaf = lowered[-1]
    if (
        leaf.startswith(".env")
        or (Path(leaf).suffix.casefold() in _DENIED_SUFFIXES and path != SAFE_ENV_EXAMPLE)
        or (
            _SECRET_NAME.search(leaf)
            and Path(leaf).suffix.casefold() in _SECRET_DATA_SUFFIXES
            and path != SAFE_ENV_EXAMPLE
        )
    ):
        raise ReleaseError(f"Secret, model, or runtime artifact is excluded: {path!r}.")
    if leaf in {"local.yaml", "gateway.local.yaml", "project-summary.md"}:
        raise ReleaseError(f"Private local configuration or report is excluded: {path!r}.")
    if path.casefold() in _PRIVATE_VALIDATION_PATHS:
        raise ReleaseError(f"Machine-specific validation path is excluded: {path!r}.")


def _validate_source_files(
    source_files: Mapping[str, tuple[int, bytes, str]],
) -> list[dict[str, object]]:
    if not source_files:
        raise ReleaseError("The source tree contains no files.")
    seen: dict[str, str] = {}
    rows: list[dict[str, object]] = []
    for path in sorted(source_files):
        validate_source_path(path)
        normalized = path.casefold()
        if normalized in seen:
            raise ReleaseError(f"Windows path collision: {seen[normalized]!r} and {path!r}.")
        seen[normalized] = path
        mode, data, object_sha = source_files[path]
        if mode not in {0o100644, 0o100755} or not isinstance(data, bytes):
            raise ReleaseError(f"Source entry is not a regular file: {path!r}.")
        if path == SAFE_ENV_EXAMPLE:
            _validate_empty_env_example(data)
        if not re.fullmatch(r"[0-9a-f]{40}", object_sha):
            raise ReleaseError(f"Git blob SHA is invalid: {path!r}.")
        git_blob_sha = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if object_sha != git_blob_sha:
            raise ReleaseError(f"Git blob content does not match its object ID: {path!r}.")
        rows.append(
            {
                "path": path,
                "mode": "100755" if mode == 0o100755 else "100644",
                "bytes": len(data),
                "git_blob": object_sha,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    names = {row["path"] for row in rows}
    missing = REQUIRED_ENTRYPOINTS.difference(names)
    if missing:
        raise ReleaseError("Required Windows entry points are missing: " + ", ".join(sorted(missing)))
    if MANIFEST_NAME in names or CHECKSUMS_NAME in names:
        raise ReleaseError("The selected source tree already contains generated release metadata.")
    return rows


def _validate_empty_env_example(data: bytes) -> None:
    """Allow only the tracked public template, with known names and empty values."""
    try:
        lines = data.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise ReleaseError("The tracked environment example is not UTF-8.") from exc
    names: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if not separator or name not in _SAFE_ENV_NAMES or value:
            raise ReleaseError("The tracked environment example contains an unknown name or non-empty value.")
        if name in names:
            raise ReleaseError("The tracked environment example repeats a variable.")
        names.add(name)
    if names != _SAFE_ENV_NAMES:
        raise ReleaseError("The tracked environment example is missing a documented variable.")


def validate_ci_url(ci_url: str) -> str:
    parsed = urlsplit(ci_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "github.com"
        or parsed.query
        or parsed.fragment
        or not _RUN_URL.fullmatch(parsed.path)
    ):
        raise ReleaseError("--ci-url must be a GitHub Actions run URL.")
    return ci_url


def validate_acceptance(acceptance: object) -> dict[str, object]:
    if not isinstance(acceptance, dict) or not acceptance:
        raise ReleaseError("Acceptance provenance must be a non-empty JSON object supplied by the operator.")
    overall = acceptance.get("overall")
    checks = acceptance.get("checks")
    allowed_statuses = {"PASS", "DEGRADED", "DEFERRED", "BLOCKED"}
    if not isinstance(overall, str) or overall not in allowed_statuses or not isinstance(checks, list) or not checks:
        raise ReleaseError("Acceptance provenance needs an overall status and a non-empty checks list.")
    for item in checks:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
            or not isinstance(item.get("status"), str)
            or item["status"] not in allowed_statuses
            or not isinstance(item.get("evidence"), str)
            or not item["evidence"].strip()
        ):
            raise ReleaseError("Each acceptance check needs a name, recorded status, and evidence reference.")
    try:
        encoded = json.dumps(acceptance, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReleaseError("Acceptance provenance must be valid UTF-8 JSON.") from exc
    if len(encoded) > MAX_ACCEPTANCE_BYTES:
        raise ReleaseError("Acceptance provenance exceeds the 1 MiB limit.")
    return acceptance


def assemble_release(
    *,
    version: str,
    commit: str,
    tree: str,
    ci_url: str,
    acceptance: object,
    source_files: Mapping[str, tuple[int, bytes, str]],
    output_dir: Path,
) -> dict[str, Path]:
    """Create deterministic source ZIP, manifest, and checksum file from Git blobs."""
    if not _VERSION.fullmatch(version):
        raise ReleaseError("Version must use the vMAJOR.MINOR.PATCH form.")
    if not _FULL_COMMIT.fullmatch(commit) or not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise ReleaseError("Source commit and tree must be full SHA-1 identifiers.")
    ci_url = validate_ci_url(ci_url)
    acceptance_payload = validate_acceptance(acceptance)
    rows = _validate_source_files(source_files)
    archive_path = output_dir / f"Oratrice-{version}{ARCHIVE_SUFFIX}"
    manifest_path = output_dir / MANIFEST_NAME
    checksums_path = output_dir / CHECKSUMS_NAME
    outputs = (archive_path, manifest_path, checksums_path)
    if output_dir.exists() or output_dir.is_symlink():
        raise ReleaseError("The release output directory must not already exist.")

    manifest = {
        "format": "oratrice-source-release",
        "manifest_version": 1,
        "version": version,
        "source": {"commit": commit.lower(), "tree": tree, "file_count": len(rows)},
        "ci_url": ci_url,
        "acceptance_provenance": acceptance_payload,
        "files": rows,
        "artifacts": {
            "archive": archive_path.name,
            "manifest": MANIFEST_NAME,
            "checksums": CHECKSUMS_NAME,
        },
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=".oratrice-release-", dir=output_dir.parent))
    staged_archive = staging_dir / archive_path.name
    staged_manifest = staging_dir / MANIFEST_NAME
    staged_checksums = staging_dir / CHECKSUMS_NAME
    try:
        with zipfile.ZipFile(staged_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for row in rows:
                path = str(row["path"])
                mode, data, _ = source_files[path]
                info = zipfile.ZipInfo(path, date_time=ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                unix_mode = stat.S_IFREG | (0o755 if mode == 0o100755 else 0o644)
                info.external_attr = unix_mode << 16
                info.flag_bits |= 0x800
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            info = zipfile.ZipInfo(MANIFEST_NAME, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits |= 0x800
            archive.writestr(info, manifest_bytes, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

        archive_bytes = staged_archive.read_bytes()
        checksums = (
            f"{hashlib.sha256(archive_bytes).hexdigest()}  {archive_path.name}\n"
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  {MANIFEST_NAME}\n"
        ).encode("ascii")
        _write_new_file(staged_manifest, manifest_bytes)
        _write_new_file(staged_checksums, checksums)
        os.rename(staging_dir, output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return {"archive": archive_path, "manifest": manifest_path, "checksums": checksums_path}


def _write_new_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)


def _load_acceptance(path: Path) -> dict[str, object]:
    if path.stat().st_size > MAX_ACCEPTANCE_BYTES:
        raise ReleaseError("Acceptance provenance exceeds the 1 MiB limit.")

    def pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseError("Acceptance provenance contains duplicate object keys.")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ReleaseError(f"Invalid JSON constant: {value}.")

    try:
        parsed = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs_without_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError("Could not read valid UTF-8 JSON acceptance provenance.") from exc
    return validate_acceptance(parsed)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package a deterministic Oratrice source release from a committed Git tree.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--commit", required=True, help="Full 40-character Git commit SHA")
    parser.add_argument("--version", required=True, help="Release version such as v0.3.0")
    parser.add_argument("--ci-url", required=True, help="GitHub Actions run URL for the exact source commit")
    parser.add_argument("--acceptance-json", required=True, type=Path, help="Operator-supplied acceptance provenance JSON")
    parser.add_argument("--output-dir", required=True, type=Path, help="New output directory for ZIP, manifest, and checksum")
    return parser


def main(argv: list[str] | None = None, *, repository_factory: Callable[[Path], GitTree] = GitRepository) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        repository = repository_factory(args.repo_root)
        source = repository.read_tree(args.commit)
        outputs = assemble_release(
            version=args.version,
            commit=str(source["commit"]),
            tree=str(source["tree"]),
            ci_url=args.ci_url,
            acceptance=_load_acceptance(args.acceptance_json),
            source_files=source["files"],  # type: ignore[arg-type]
            output_dir=args.output_dir,
        )
    except (OSError, ReleaseError) as exc:
        parser.error(str(exc))
    for kind, path in outputs.items():
        print(f"{kind}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
