"""Tests for `meetscribe cancel` command."""

import importlib

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


def test_cancel_queued(cli_app):
    cli_runner.invoke(cli_app, ["migrate"])
    with state.connection() as conn:
        vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        state.transition_state(conn, vid, "queued")
    result = cli_runner.invoke(cli_app, ["cancel", str(vid)])
    assert result.exit_code == 0
    with state.connection() as conn:
        v = state.get_video(conn, str(vid))
    assert v["state"] == "cancelled"


def test_cancel_processing(cli_app):
    cli_runner.invoke(cli_app, ["migrate"])
    with state.connection() as conn:
        vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        state.start_attempt(conn, vid, "local")
    result = cli_runner.invoke(cli_app, ["cancel", str(vid)])
    assert result.exit_code == 0
    with state.connection() as conn:
        v = state.get_video(conn, str(vid))
    assert v["state"] == "cancelled"


def test_cancel_done_returns_nonzero(cli_app):
    cli_runner.invoke(cli_app, ["migrate"])
    with state.connection() as conn:
        vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        a = state.start_attempt(conn, vid, "local")
        state.complete_attempt(conn, a, vid, "/out")
    result = cli_runner.invoke(cli_app, ["cancel", str(vid)])
    assert result.exit_code != 0


def test_cancel_missing_returns_nonzero(cli_app):
    cli_runner.invoke(cli_app, ["migrate"])
    result = cli_runner.invoke(cli_app, ["cancel", "999"])
    assert result.exit_code != 0
