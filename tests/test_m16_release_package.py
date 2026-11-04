"""Offline tests for deterministic M16 release packaging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.package_release import (
    ReleaseError,
    _parse_cat_file_batch,
    _validate_source_files,
    assemble_release,
    validate_acceptance,
    validate_ci_url,
    validate_source_path,
)


COMMIT = "1" * 40
TREE = "2" * 40
CI_URL = "https://github.com/leoxu0507-glitch/oratrice/actions/runs/41630344890"
ACCEPTANCE = {
    "overall": "DEFERRED",
    "checks": [
        {
            "name": "fixture-only release package test",
            "status": "PASS",
            "evidence": "tests/test_m16_release_package.py",
        }
    ],
}


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _source_files() -> dict[str, tuple[int, bytes, str]]:
    values = {
        "Start-Oratrice.exe": (0o100755, b"launcher binary"),
        "Start-Oratrice-Pet.cmd": (0o100644, b"@echo off\r\n"),
        "README.md": (0o100644, b"Oratrice\n"),
    }
    return {
        path: (
            mode,
            data,
            _git_blob_sha(data),
        )
        for path, (mode, data) in values.items()
    }


def _package(output: Path):
    return assemble_release(
        version="v0.3.0",
        commit=COMMIT,
        tree=TREE,
        ci_url=CI_URL,
        acceptance=ACCEPTANCE,
        source_files=_source_files(),
        output_dir=output,
    )


def test_release_zip_is_deterministic_and_carries_exact_provenance(tmp_path):
    first = _package(tmp_path / "first")
    second = _package(tmp_path / "second")

    first_zip = first["archive"].read_bytes()
    assert first_zip == second["archive"].read_bytes()
    with zipfile.ZipFile(first["archive"]) as archive:
        assert archive.namelist() == [
            "README.md",
            "Start-Oratrice-Pet.cmd",
            "Start-Oratrice.exe",
            "RELEASE-MANIFEST.json",
        ]
        manifest = json.loads(archive.read("RELEASE-MANIFEST.json"))
        assert archive.read("README.md") == b"Oratrice\n"
        assert archive.read("Start-Oratrice.exe") == b"launcher binary"

    external_manifest = json.loads(first["manifest"].read_text(encoding="utf-8"))
    assert manifest == external_manifest
    assert manifest["source"] == {"commit": COMMIT, "tree": TREE, "file_count": 3}
    assert manifest["acceptance_provenance"] == ACCEPTANCE
    assert manifest["ci_url"] == CI_URL
    sums = first["checksums"].read_text(encoding="ascii")
    assert hashlib.sha256(first_zip).hexdigest() in sums
    assert hashlib.sha256(first["manifest"].read_bytes()).hexdigest() in sums


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "folder/../../secret.txt",
        "/absolute.txt",
        "C:/secret.txt",
        "folder\\secret.txt",
        "folder/CON.txt",
        "config/profiles/local.yaml",
        "config/gateway.local.yaml",
        "credentials.json",
        "config/secrets.env",
        ".env.production",
        "models/private.gguf",
        "work/acceptance.log",
        "cache/model.bin",
        "cache/.pytest_cache/state",
    ],
)
def test_release_rejects_unsafe_or_private_source_paths(path):
    with pytest.raises(ReleaseError):
        validate_source_path(path)


def test_release_rejects_symlink_and_missing_entry_points():
    source = _source_files()
    source["shortcut"] = (0o120000, b"Start-Oratrice.exe", hashlib.sha1(b"blob 18\0Start-Oratrice.exe").hexdigest())
    with pytest.raises(ReleaseError, match="regular file"):
        _validate_source_files(source)

    with pytest.raises(ReleaseError, match="entry points"):
        _validate_source_files({"README.md": _source_files()["README.md"]})


def test_release_rejects_blob_content_mismatch():
    source = _source_files()
    mode, _, sha = source["README.md"]
    source["README.md"] = (mode, b"edited after commit", sha)
    with pytest.raises(ReleaseError, match="does not match"):
        _validate_source_files(source)


def test_release_accepts_public_secrets_architecture_document():
    source = _source_files()
    path = "docs/architecture/SECRETS.md"
    content = b"# Secret handling\nThis public document describes safe credential use.\n"
    source[path] = (0o100644, content, _git_blob_sha(content))

    rows = _validate_source_files(source)

    assert any(row["path"] == path for row in rows)


def test_release_includes_only_empty_tracked_environment_template():
    source = _source_files()
    source["config/secrets.example.env"] = (
        0o100644,
        b"ORATRICE_LITELLM_MASTER_KEY=\nDEEPSEEK_API_KEY=\n",
        _git_blob_sha(b"ORATRICE_LITELLM_MASTER_KEY=\nDEEPSEEK_API_KEY=\n"),
    )
    rows = _validate_source_files(source)
    assert any(row["path"] == "config/secrets.example.env" for row in rows)

    mode, _, sha = source["config/secrets.example.env"]
    populated = b"ORATRICE_LITELLM_MASTER_KEY=real-value\nDEEPSEEK_API_KEY=\n"
    source["config/secrets.example.env"] = (
        mode,
        populated,
        _git_blob_sha(populated),
    )
    with pytest.raises(ReleaseError, match="non-empty value"):
        _validate_source_files(source)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/leoxu0507-glitch/oratrice/actions/runs/1",
        "https://github.com.attacker.invalid/a/b/actions/runs/1",
        "https://github.com/leoxu0507-glitch/oratrice/actions/runs/1?token=x",
        "https://github.com/leoxu0507-glitch/oratrice/actions",
    ],
)
def test_ci_url_must_be_a_github_actions_run(url):
    with pytest.raises(ReleaseError):
        validate_ci_url(url)


def test_acceptance_requires_operator_supplied_status_and_evidence():
    assert validate_acceptance(ACCEPTANCE) == ACCEPTANCE
    for invalid in (
        {},
        {"overall": "PASS", "checks": []},
        {"overall": "UNKNOWN", "checks": [ACCEPTANCE["checks"][0]]},
        {"overall": "PASS", "checks": [{"name": "check", "status": "PASS"}]},
    ):
        with pytest.raises(ReleaseError):
            validate_acceptance(invalid)


def test_cat_file_batch_parser_preserves_binary_and_checks_framing():
    data = b"MZ\x00\xff"
    sha = hashlib.sha1(b"blob 4\0" + data).hexdigest()
    parsed = _parse_cat_file_batch(
        f"{sha} blob 4\n".encode("ascii") + data + b"\n",
        [("Start-Oratrice.exe", 0o100755, sha)],
    )
    assert parsed["Start-Oratrice.exe"] == (0o100755, data, sha)

    with pytest.raises(ReleaseError, match="incomplete"):
        _parse_cat_file_batch(f"{sha} blob 5\n".encode("ascii") + data + b"\n", [("bad", 0o100644, sha)])


def test_release_refuses_to_overwrite_existing_output_directory(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(ReleaseError, match="must not already exist"):
        _package(output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "user data"
