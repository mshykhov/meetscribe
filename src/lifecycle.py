"""Self-uninstall logic. Removes launchd, plists, symlinks, install dir,
optionally state.db / .env / OUTPUT_DIR."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _bootout(label: str) -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{label}"],
        capture_output=True,
    )


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def _read_output_dir(env_file: Path) -> str | None:
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.startswith("OUTPUT_DIR="):
            return line.split("=", 1)[1].strip()
    return None


_DEFAULT_OUTPUT_DIR = "~/docs/video"


def uninstall(keep_data: bool = True) -> None:
    """Remove the meetscribe install. Idempotent.

    keep_data=True  (default): preserves state.db, .env, OUTPUT_DIR.
    keep_data=False: also removes state.db + .env. Removes OUTPUT_DIR only
                     if its value is the default ~/docs/video (hard guard).
    """
    print("Stopping services...")
    _bootout("com.myron.meetscribe.watcher")
    _bootout("com.myron.meetscribe.worker")

    home = Path(os.environ["HOME"])
    la = home / "Library" / "LaunchAgents"
    for name in ("com.myron.meetscribe.watcher.plist",
                 "com.myron.meetscribe.worker.plist"):
        (la / name).unlink(missing_ok=True)
    print("Removed launchd plists.")

    swiftbar = (
        home / "Library" / "Application Support" / "SwiftBar" / "Plugins"
        / "meetscribe.5s.sh"
    )
    if swiftbar.is_symlink() or swiftbar.exists():
        swiftbar.unlink(missing_ok=True)
        print("Removed SwiftBar plugin symlink.")

    shim = home / ".local" / "bin" / "meetscribe"
    if shim.is_symlink() or shim.exists():
        shim.unlink(missing_ok=True)

    install_root = _xdg_data_home() / "meetscribe"
    for sub in ("install", ".venv"):
        target = install_root / sub
        if target.exists():
            shutil.rmtree(target)
            print(f"Removed {target}.")

    if not keep_data:
        env_file = _xdg_config_home() / "meetscribe" / ".env"
        output_dir_value = _read_output_dir(env_file)
        for path in (
            install_root / "state.db",
            install_root / "state.db-wal",
            install_root / "state.db-shm",
            env_file,
        ):
            path.unlink(missing_ok=True)
        print("Removed state.db and .env.")

        # Hard guard: only auto-delete OUTPUT_DIR if it's the default.
        if output_dir_value == _DEFAULT_OUTPUT_DIR:
            target = Path(output_dir_value).expanduser()
            if target.exists():
                shutil.rmtree(target)
                print(f"Removed default OUTPUT_DIR {target}.")
        elif output_dir_value:
            print(f"Non-default OUTPUT_DIR {output_dir_value!r} kept (delete manually).")

    print("Uninstall complete.")
