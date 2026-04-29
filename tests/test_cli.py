"""Integration tests for src.cli using typer.testing.CliRunner."""

import importlib

import pytest
from typer.testing import CliRunner

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


class TestMigrate:
    def test_applies_initial_on_fresh_db(self, cli_app):
        result = cli_runner.invoke(cli_app, ["migrate"])
        assert result.exit_code == 0
        assert "Applied 1" in result.stdout

    def test_noop_on_already_migrated(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        result = cli_runner.invoke(cli_app, ["migrate"])
        assert result.exit_code == 0
        assert "Applied 0" in result.stdout


class TestLs:
    def test_empty_db_message(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        result = cli_runner.invoke(cli_app, ["ls"])
        assert result.exit_code == 0
        assert "No videos" in result.stdout

    def test_lists_videos(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        from src import state
        with state.connection() as conn:
            state.record_video_seen(conn, "/tmp/a.mp4", 1000, 100, 10.0)
            state.record_video_seen(conn, "/tmp/b.mp4", 2000, 200, 20.0)
        result = cli_runner.invoke(cli_app, ["ls"])
        assert result.exit_code == 0
        assert "/tmp/a.mp4" in result.stdout
        assert "/tmp/b.mp4" in result.stdout

    def test_filter_by_state(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        from src import state
        with state.connection() as conn:
            state.record_video_seen(conn, "/tmp/a.mp4", 1000, 100, 10.0)
        result = cli_runner.invoke(cli_app, ["ls", "--state", "done"])
        assert result.exit_code == 0
        assert "No videos" in result.stdout


class TestShow:
    def test_show_by_id(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        from src import state
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/a.mp4", 1000, 100, 10.0)
            state.start_attempt(conn, vid, "local")
        result = cli_runner.invoke(cli_app, ["show", str(vid)])
        assert result.exit_code == 0
        assert "/tmp/a.mp4" in result.stdout
        assert "processing" in result.stdout
        assert "Attempts" in result.stdout

    def test_show_by_path(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        from src import state
        with state.connection() as conn:
            state.record_video_seen(conn, "/tmp/a.mp4", 1000, 100, 10.0)
        result = cli_runner.invoke(cli_app, ["show", "/tmp/a.mp4"])
        assert result.exit_code == 0
        assert "/tmp/a.mp4" in result.stdout

    def test_show_missing_returns_nonzero(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        result = cli_runner.invoke(cli_app, ["show", "999"])
        assert result.exit_code != 0
