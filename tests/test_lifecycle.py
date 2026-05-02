"""Tests for src/lifecycle.py: uninstall removes expected paths."""

from pathlib import Path
from unittest.mock import patch

import pytest


def _mklayout(tmp_path: Path) -> dict[str, Path]:
    """Build a minimal XDG layout that uninstall() should touch."""
    home = tmp_path
    install_root = home / ".local/share/meetscribe"
    venv = install_root / ".venv"
    install = install_root / "install"
    state_db = install_root / "state.db"
    config_dir = home / ".config/meetscribe"
    env_file = config_dir / ".env"
    la = home / "Library/LaunchAgents"
    swiftbar = home / "Library/Application Support/SwiftBar/Plugins"
    bin_dir = home / ".local/bin"

    for d in (venv, install, config_dir, la, swiftbar, bin_dir):
        d.mkdir(parents=True)
    state_db.write_bytes(b"")
    env_file.write_text("HF_TOKEN=hf_x\nOUTPUT_DIR=~/docs/video\n")
    (la / "com.myron.meetscribe.watcher.plist").write_text("<plist/>")
    (la / "com.myron.meetscribe.worker.plist").write_text("<plist/>")
    (swiftbar / "meetscribe.5s.sh").symlink_to(install)
    (bin_dir / "meetscribe").symlink_to(venv / "bin" / "meetscribe")

    return {
        "home": home, "install_root": install_root,
        "venv": venv, "install": install, "state_db": state_db,
        "env_file": env_file, "la": la, "swiftbar": swiftbar,
        "bin_dir": bin_dir,
    }


@pytest.fixture
def fake_layout(tmp_path, monkeypatch):
    layout = _mklayout(tmp_path)
    monkeypatch.setenv("HOME", str(layout["home"]))
    monkeypatch.setenv("XDG_DATA_HOME", str(layout["home"] / ".local/share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(layout["home"] / ".config"))
    return layout


def test_uninstall_keep_data_removes_install_keeps_state(fake_layout):
    """Default --keep-data: removes install/.venv/plists/symlinks; keeps state.db + .env."""
    from src import lifecycle
    with patch("src.lifecycle.subprocess.run") as mock_run:
        lifecycle.uninstall(keep_data=True)

    # launchctl bootout was called for both labels.
    assert mock_run.call_count == 2
    args_first = mock_run.call_args_list[0].args[0]
    assert "launchctl" in args_first[0]
    assert "bootout" in args_first

    # Plists removed.
    assert not (fake_layout["la"] / "com.myron.meetscribe.watcher.plist").exists()
    assert not (fake_layout["la"] / "com.myron.meetscribe.worker.plist").exists()

    # SwiftBar symlink removed.
    assert not (fake_layout["swiftbar"] / "meetscribe.5s.sh").exists()

    # bin shim removed.
    assert not (fake_layout["bin_dir"] / "meetscribe").exists()

    # install/ and .venv/ removed.
    assert not fake_layout["install"].exists()
    assert not fake_layout["venv"].exists()

    # state.db preserved.
    assert fake_layout["state_db"].exists()
    assert fake_layout["env_file"].exists()


def test_uninstall_no_keep_data_removes_state_and_env(fake_layout):
    """--no-keep-data also removes state.db + .env."""
    from src import lifecycle
    with patch("src.lifecycle.subprocess.run"):
        lifecycle.uninstall(keep_data=False)

    assert not fake_layout["state_db"].exists()
    assert not fake_layout["env_file"].exists()


def test_uninstall_no_keep_data_does_not_delete_nondefault_output_dir(
    fake_layout, monkeypatch
):
    """OUTPUT_DIR=~/Custom/Path must NOT be deleted (only default ~/docs/video is)."""
    custom_output = fake_layout["home"] / "Custom" / "Path"
    custom_output.mkdir(parents=True)
    fake_layout["env_file"].write_text(f"OUTPUT_DIR={custom_output}\n")
    from src import lifecycle
    with patch("src.lifecycle.subprocess.run"):
        lifecycle.uninstall(keep_data=False)
    # custom_output preserved - only default path is auto-deleted.
    assert custom_output.exists()


def test_uninstall_idempotent_when_no_install_present(tmp_path, monkeypatch):
    """Running uninstall on a clean machine (nothing installed) is a no-op."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local/share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    from src import lifecycle
    with patch("src.lifecycle.subprocess.run"):
        lifecycle.uninstall(keep_data=True)  # Must not raise
