"""Tests for scripts/render_plists.py: template substitution."""

import plistlib
import subprocess
from pathlib import Path


def test_render_produces_valid_plist_with_substituted_paths(tmp_path):
    """End-to-end: invoke render_plists.py via subprocess, parse output plist."""
    install_dir = tmp_path / "install"
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    install_dir.mkdir()
    (install_dir / "scripts" / "plists").mkdir(parents=True)

    # Copy templates from the repo into the fake install_dir.
    repo_root = Path(__file__).resolve().parent.parent
    template_dir = repo_root / "scripts" / "plists"
    for name in ("com.myron.meetscribe.watcher.plist.template",
                 "com.myron.meetscribe.worker.plist.template"):
        (install_dir / "scripts" / "plists" / name).write_text(
            (template_dir / name).read_text()
        )

    output_dir = tmp_path / "agents"
    output_dir.mkdir()

    subprocess.run(
        [
            "python3",
            str(repo_root / "scripts" / "render_plists.py"),
            "--install-dir", str(install_dir),
            "--venv", str(venv_dir),
            "--output-dir", str(output_dir),
        ],
        capture_output=True, text=True, check=True,
    )

    watcher_plist = output_dir / "com.myron.meetscribe.watcher.plist"
    worker_plist = output_dir / "com.myron.meetscribe.worker.plist"
    assert watcher_plist.exists()
    assert worker_plist.exists()

    with watcher_plist.open("rb") as f:
        watcher = plistlib.load(f)
    assert watcher["Label"] == "com.myron.meetscribe.watcher"
    assert watcher["WorkingDirectory"] == str(install_dir)
    assert watcher["ProgramArguments"][0] == str(venv_dir / "bin" / "python")
    assert watcher["KeepAlive"] is True

    with worker_plist.open("rb") as f:
        worker = plistlib.load(f)
    assert worker["Label"] == "com.myron.meetscribe.worker"
    assert worker["KeepAlive"] is False
    assert worker["ProcessType"] == "Interactive"
