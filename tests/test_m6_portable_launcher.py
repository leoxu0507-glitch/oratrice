from __future__ import annotations

from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "launcher" / "windows" / "Start-Oratrice.cs"


def test_windows_launcher_python_discovery_contract_is_portable():
    source = SOURCE.read_text(encoding="utf-8")

    # The bootstrap must not encode this machine's checkout or user profile.
    assert r"D:\AI" not in source
    assert r"C:\Users" not in source

    configured = source.index('Environment.GetEnvironmentVariable("ORATRICE_PYTHON")')
    project_venv = source.index('Path.Combine(root, @".venv\\Scripts\\python.exe")')
    infrastructure_venv = source.index('..\\..\\infrastructure\\litellm\\.venv\\Scripts\\python.exe')
    path_fallback = source.index('FindOnPath("python.exe")')

    assert configured < project_venv < infrastructure_venv < path_fallback
    assert "IsAbsolutePath(configured)" in source
    assert "ORATRICE_PYTHON must be an absolute path" in source
    assert "ORATRICE_PYTHON does not exist" in source
    assert "File.Exists(projectPython)" in source
    assert "File.Exists(infrastructurePython)" in source
    assert "Environment.GetEnvironmentVariable(\"PATH\")" in source
    assert "Path.PathSeparator" in source
