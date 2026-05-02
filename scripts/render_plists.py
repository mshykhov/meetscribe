"""Render plist templates with concrete paths into ~/Library/LaunchAgents/."""

import argparse
import os
from pathlib import Path


def render(template_path: Path, output_path: Path, **fields: str) -> None:
    text = template_path.read_text()
    for key, value in fields.items():
        text = text.replace("{" + key + "}", value)
    text = text.replace("__HOME__", os.environ["HOME"])
    output_path.write_text(text)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--install-dir", required=True)
    p.add_argument("--venv", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--logs-dir",
                   default=str(Path.home() / ".local/share/meetscribe/logs"))
    args = p.parse_args()

    install_dir = Path(args.install_dir).resolve()
    venv_python = Path(args.venv).resolve() / "bin" / "python"
    logs_dir = Path(args.logs_dir).resolve()
    output_dir = Path(args.output_dir).expanduser()

    logs_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    template_dir = install_dir / "scripts" / "plists"
    fields = {
        "install_dir": str(install_dir),
        "venv_python": str(venv_python),
        "logs_dir": str(logs_dir),
    }
    for name in ("com.myron.meetscribe.watcher.plist",
                 "com.myron.meetscribe.worker.plist"):
        render(
            template_dir / f"{name}.template",
            output_dir / name,
            **fields,
        )


if __name__ == "__main__":
    main()
