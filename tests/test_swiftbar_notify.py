"""Tests for src.swiftbar.notify_swiftbar_refresh."""

import importlib

import pytest


class TestNotifyRefresh:
    def test_calls_open_with_url(self, monkeypatch):
        from src import swiftbar
        importlib.reload(swiftbar)
        monkeypatch.delenv("MEETSCRIBE_DISABLE_SWIFTBAR", raising=False)
        captured = []

        class FakeProc:
            returncode = 0

        def fake_run(args, **kwargs):
            captured.append(args)
            return FakeProc()

        monkeypatch.setattr(swiftbar.subprocess, "run", fake_run)
        swiftbar.notify_swiftbar_refresh()
        assert len(captured) == 1
        assert captured[0][0] == "open"
        assert captured[0][1].startswith("swiftbar://refreshplugin?")
        assert "meetscribe" in captured[0][1]

    def test_no_op_when_disabled(self, monkeypatch):
        from src import swiftbar
        importlib.reload(swiftbar)
        monkeypatch.setenv("MEETSCRIBE_DISABLE_SWIFTBAR", "1")
        captured = []

        def fake_run(args, **kwargs):
            captured.append(args)
            return None

        monkeypatch.setattr(swiftbar.subprocess, "run", fake_run)
        swiftbar.notify_swiftbar_refresh()
        assert captured == []

    def test_swallows_exceptions(self, monkeypatch):
        from src import swiftbar
        importlib.reload(swiftbar)
        monkeypatch.delenv("MEETSCRIBE_DISABLE_SWIFTBAR", raising=False)

        def boom(*a, **kw):
            raise OSError("boom")

        monkeypatch.setattr(swiftbar.subprocess, "run", boom)
        swiftbar.notify_swiftbar_refresh()
