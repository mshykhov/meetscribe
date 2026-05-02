"""Resolve filesystem paths for both standalone install and dev mode.

Resolution order:
  1. XDG_DATA_HOME / "meetscribe" / ... (if present)
  2. Project root next to src/ (dev mode fallback)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def _project_root() -> Path:
    """Repo root in dev mode (parent of the src/ directory containing this file)."""
    return Path(__file__).resolve().parent.parent


def install_dir() -> Path:
    """Return the install location. XDG when present, else project root."""
    xdg = _xdg_data_home() / "meetscribe" / "install"
    if xdg.exists():
        return xdg
    return _project_root()


def env_path() -> Path:
    """Path to .env. XDG_CONFIG_HOME first, then project root."""
    xdg = _xdg_config_home() / "meetscribe" / ".env"
    if xdg.exists():
        return xdg
    return _project_root() / ".env"


def venv_python() -> Path:
    """Python interpreter to use. XDG venv first, then dev .venv, then sys.executable."""
    xdg_venv = _xdg_data_home() / "meetscribe" / ".venv" / "bin" / "python"
    if xdg_venv.exists():
        return xdg_venv
    dev_venv = _project_root() / ".venv" / "bin" / "python"
    if dev_venv.exists():
        return dev_venv
    return Path(sys.executable)
