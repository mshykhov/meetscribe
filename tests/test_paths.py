"""Tests for src/paths.py: XDG resolution with dev-mode fallback."""

from pathlib import Path


def test_install_dir_uses_xdg_when_present(monkeypatch, tmp_path):
    install = tmp_path / "share" / "meetscribe" / "install"
    install.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    from src import paths
    assert paths.install_dir() == install


def test_install_dir_falls_back_to_project_root(monkeypatch, tmp_path):
    """When XDG install dir is absent, return the project root (the dev source tree)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))  # nothing there
    from src import paths
    result = paths.install_dir()
    # Dev fallback: parent of src/
    assert (result / "src" / "paths.py").exists()


def test_env_path_uses_xdg_when_present(monkeypatch, tmp_path):
    cfg = tmp_path / "config" / "meetscribe"
    cfg.mkdir(parents=True)
    (cfg / ".env").write_text("HF_TOKEN=hf_xdg\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from src import paths
    assert paths.env_path() == cfg / ".env"


def test_env_path_falls_back_to_project_root(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from src import paths
    result = paths.env_path()
    # Dev fallback: project root .env (may or may not exist)
    assert result.name == ".env"
    assert result.parent == Path(__file__).resolve().parent.parent


def test_venv_python_uses_xdg_when_present(monkeypatch, tmp_path):
    bin_dir = tmp_path / "share" / "meetscribe" / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/sh\n")
    py.chmod(0o755)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    from src import paths
    assert paths.venv_python() == py


def test_venv_python_falls_back_to_dev_or_sys_executable(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    from src import paths
    result = paths.venv_python()
    # Either dev .venv/bin/python or sys.executable; both are absolute Path objects.
    assert result.is_absolute()
