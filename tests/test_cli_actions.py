"""Tests for CLI action commands: retry, skip, reprocess."""

import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src import state

cli_runner = CliRunner()


@pytest.fixture
def cli_app(tmp_path, monkeypatch):
    target = tmp_path / "state.db"
    monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
    from src.state import db
    importlib.reload(db)
    from src import cli
    importlib.reload(cli)
    return cli.app


class TestRetry:
    def test_resets_failed_to_detected(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
            a = state.start_attempt(conn, vid, "local")
            state.fail_attempt(conn, a, vid, "boom", "transcribe")
        result = cli_runner.invoke(cli_app, ["retry", str(vid)])
        assert result.exit_code == 0
        with state.connection() as conn:
            v = state.get_video(conn, str(vid))
        assert v["state"] == "detected"

    def test_retry_by_path(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        with state.connection() as conn:
            state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        result = cli_runner.invoke(cli_app, ["retry", "/tmp/v.mp4"])
        assert result.exit_code == 0

    def test_retry_missing_returns_nonzero(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        result = cli_runner.invoke(cli_app, ["retry", "999"])
        assert result.exit_code != 0


class TestSkip:
    def test_marks_as_skipped(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        result = cli_runner.invoke(cli_app, ["skip", str(vid)])
        assert result.exit_code == 0
        with state.connection() as conn:
            v = state.get_video(conn, str(vid))
        assert v["state"] == "skipped"


class TestReprocess:
    def test_archives_output_and_resets(self, cli_app, tmp_path):
        cli_runner.invoke(cli_app, ["migrate"])
        out = tmp_path / "out"
        out.mkdir()
        (out / "transcript.txt").write_text("hello")
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
            a = state.start_attempt(conn, vid, "local")
            state.complete_attempt(conn, a, vid, str(out))

        result = cli_runner.invoke(cli_app, ["reprocess", str(vid)])
        assert result.exit_code == 0

        archived = list(tmp_path.iterdir())
        assert any(p.name.startswith("out.archived-") for p in archived)
        assert not out.exists()

        with state.connection() as conn:
            v = state.get_video(conn, str(vid))
        assert v["state"] == "detected"
        assert v["output_path"] is None

    def test_reprocess_without_output_just_resets(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        result = cli_runner.invoke(cli_app, ["reprocess", str(vid)])
        assert result.exit_code == 0
        with state.connection() as conn:
            v = state.get_video(conn, str(vid))
        assert v["state"] == "detected"
