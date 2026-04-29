"""Tests for CLI daemon subcommand group."""

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


class FakeProc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class TestDaemonStatus:
    def test_runs_launchctl_print(self, cli_app, monkeypatch):
        from src import cli as cli_mod
        captured = []

        def fake_run(args, **kwargs):
            captured.append(args)
            return FakeProc(0, "service status output")

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        result = cli_runner.invoke(cli_app, ["daemon", "status"])
        assert result.exit_code == 0
        joined = " ".join(" ".join(c) for c in captured)
        assert "launchctl" in joined
        assert "print" in joined

    def test_not_loaded(self, cli_app, monkeypatch):
        from src import cli as cli_mod
        monkeypatch.setattr(cli_mod.subprocess, "run", lambda *a, **kw: FakeProc(1, ""))
        result = cli_runner.invoke(cli_app, ["daemon", "status"])
        assert result.exit_code == 0
        assert "Not loaded" in result.stdout


class TestDaemonRestart:
    def test_calls_bootout_and_bootstrap(self, cli_app, monkeypatch):
        from src import cli as cli_mod
        called = []

        def fake_run(args, **kwargs):
            called.append(args)
            return FakeProc(0, "")

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        result = cli_runner.invoke(cli_app, ["daemon", "restart"])
        assert result.exit_code == 0
        joined = " ".join(" ".join(c) for c in called)
        assert "bootout" in joined
        assert "bootstrap" in joined


class TestDaemonStop:
    def test_calls_bootout(self, cli_app, monkeypatch):
        from src import cli as cli_mod
        called = []

        def fake_run(args, **kwargs):
            called.append(args)
            return FakeProc(0, "")

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        result = cli_runner.invoke(cli_app, ["daemon", "stop"])
        assert result.exit_code == 0
        joined = " ".join(" ".join(c) for c in called)
        assert "bootout" in joined
