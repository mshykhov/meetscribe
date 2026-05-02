"""Textual Pilot tests for src/config_tui.py."""

from pathlib import Path

import pytest


@pytest.fixture
def env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "HF_TOKEN=hf_abc\n"
        "OPENAI_API_KEY=\n"
        "CLAUDE_CLI=claude\n"
        f"WATCH_DIR={tmp_path}\n"
        f"OUTPUT_DIR={tmp_path}\n"
        "TRANSCRIBE_BACKEND=local\n"
        "WHISPER_MODEL=medium\n"
        "OPENAI_TRANSCRIBE_MODEL=whisper-1\n"
        "LANGUAGE=\n"
        "MAX_SPEAKERS=0\n"
        "CLAUDE_MODEL=claude-sonnet-4-6\n"
    )
    return p


async def test_app_loads_existing_env_values(env_file):
    from src.config_tui import ConfigApp
    app = ConfigApp(env_file)
    async with app.run_test() as pilot:
        hf_input = app.query_one("#field-HF_TOKEN")
        assert hf_input.value == "hf_abc"
        whisper_select = app.query_one("#field-WHISPER_MODEL")
        assert whisper_select.value == "medium"


async def test_app_save_writes_modified_value(env_file):
    from src.config_tui import ConfigApp
    from src.config_io import read_env

    app = ConfigApp(env_file)
    async with app.run_test() as pilot:
        hf_input = app.query_one("#field-HF_TOKEN")
        hf_input.value = "hf_new"
        await pilot.press("f2")
    assert read_env(env_file)["HF_TOKEN"] == "hf_new"


async def test_app_save_blocks_on_invalid_input(env_file):
    """Setting HF_TOKEN to an invalid prefix must block save."""
    from src.config_tui import ConfigApp
    from src.config_io import read_env

    app = ConfigApp(env_file)
    async with app.run_test() as pilot:
        hf_input = app.query_one("#field-HF_TOKEN")
        hf_input.value = "no-hf-prefix"
        await pilot.press("f2")
        assert "hf_" in app.last_error or "HF_TOKEN" in app.last_error
    assert read_env(env_file)["HF_TOKEN"] == "hf_abc"


async def test_app_quit_does_not_write(env_file):
    from src.config_tui import ConfigApp
    from src.config_io import read_env

    app = ConfigApp(env_file)
    async with app.run_test() as pilot:
        hf_input = app.query_one("#field-HF_TOKEN")
        hf_input.value = "hf_modified"
        await pilot.press("f10")
    assert read_env(env_file)["HF_TOKEN"] == "hf_abc"
