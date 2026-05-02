"""Textual TUI for editing .env."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import (
    Footer, Header, Input, Label, Select, Static, TabbedContent, TabPane,
)

from src.config_io import read_env, write_env
from src.config_schema import ENV_KEYS, _ENUMS, validate_env


_SECRET_KEYS = {"HF_TOKEN", "OPENAI_API_KEY", "GROQ_API_KEY"}
_TAB_LAYOUT: list[tuple[str, list[str]]] = [
    ("Secrets", ["HF_TOKEN", "OPENAI_API_KEY", "GROQ_API_KEY"]),
    ("Paths", ["CLAUDE_CLI", "WATCH_DIR", "OUTPUT_DIR"]),
    ("Transcribe", ["TRANSCRIBE_BACKEND", "WHISPER_MODEL",
                    "OPENAI_TRANSCRIBE_MODEL", "GROQ_TRANSCRIBE_MODEL",
                    "LANGUAGE"]),
    ("Pipeline", ["SUMMARY_BACKEND", "CLAUDE_MODEL",
                  "OPENAI_SUMMARY_MODEL", "GROQ_SUMMARY_MODEL",
                  "MAX_SPEAKERS"]),
]


def _enum_for(key: str) -> tuple[str, ...] | None:
    if key == "TRANSCRIBE_BACKEND":
        return tuple(sorted(_ENUMS["transcribe_backend"]))
    if key == "WHISPER_MODEL":
        return tuple(sorted(_ENUMS["whisper_model"]))
    if key == "SUMMARY_BACKEND":
        return tuple(sorted(_ENUMS["summary_backend"]))
    return None


class ConfigApp(App):
    BINDINGS = [
        ("f2", "save", "Save"),
        ("f10", "quit", "Quit"),
    ]
    TITLE = "meetscribe config"

    def __init__(self, env_path: Path):
        super().__init__()
        self._env_path = env_path
        self._values: dict[str, str] = read_env(env_path)
        self._saved: bool = False
        self.last_error: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            for tab_name, keys in _TAB_LAYOUT:
                with TabPane(tab_name, id=f"tab-{tab_name.lower()}"):
                    for key in keys:
                        yield Label(key)
                        yield from self._build_widget(key)
        yield Static("", id="status")
        yield Footer()

    def _build_widget(self, key: str):
        value = self._values.get(key, "")
        choices = _enum_for(key)
        if choices is not None:
            yield Select(
                [(c, c) for c in choices],
                value=value if value in choices else choices[0],
                id=f"field-{key}",
                allow_blank=False,
            )
        else:
            yield Input(
                value=value,
                password=(key in _SECRET_KEYS),
                id=f"field-{key}",
            )

    def _collect_values(self) -> dict[str, str]:
        out: dict[str, str] = dict(self._values)
        for key in ENV_KEYS:
            widget = self.query_one(f"#field-{key}")
            out[key] = str(widget.value) if widget.value is not None else ""
        return out

    def action_save(self) -> None:
        values = self._collect_values()
        errors = validate_env(values)
        status = self.query_one("#status", Static)
        if errors:
            self.last_error = errors[0].message
            status.update(f"⚠ {errors[0].message}")
            return
        self.last_error = ""
        write_env(self._env_path, values)
        self._saved = True
        self.exit(0)

    def action_quit(self) -> None:
        self.exit(1)


def run_config_tui(env_path: Path) -> int:
    """Launch the TUI. Returns 0 on save, 1 on quit-without-save."""
    app = ConfigApp(env_path)
    return app.run() or 0
