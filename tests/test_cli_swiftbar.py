"""Integration test for `meetscribe swiftbar` command."""

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


def test_swiftbar_command_outputs_swiftbar_format(cli_app):
    cli_runner.invoke(cli_app, ["migrate"])
    result = cli_runner.invoke(cli_app, ["swiftbar"])
    assert result.exit_code == 0
    assert "---" in result.stdout
    assert "Meetscribe" in result.stdout


def test_swiftbar_command_runs_migrations_if_db_empty(cli_app):
    result = cli_runner.invoke(cli_app, ["swiftbar"])
    assert result.exit_code == 0
