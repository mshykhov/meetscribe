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
        assert "Applied 2" in result.stdout

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


class TestResummarize:
    def _make_folder(self, tmp_path, folder_name: str, transcript: str):
        folder = tmp_path / folder_name
        folder.mkdir()
        (folder / f"{folder_name}-transcript.txt").write_text(transcript)
        (folder / f"{folder_name}-summary.md").write_text("### Summary unavailable\n")
        (folder / f"{folder_name}.mov").write_bytes(b"fake video bytes")
        return folder

    def test_no_transcript_returns_error(self, cli_app, tmp_path):
        empty = tmp_path / "2026-05-13-13.13-meeting"
        empty.mkdir()
        result = cli_runner.invoke(cli_app, ["resummarize", str(empty)])
        assert result.exit_code != 0
        assert "transcript" in result.output.lower()

    def test_bad_folder_name_returns_error(self, cli_app, tmp_path, monkeypatch):
        folder = self._make_folder(tmp_path, "weird-folder-name", "[00:00] SPEAKER_00: hi\n")

        from src import process

        def fake_load_config():
            return {"summary_backend": "openai", "openai_api_key": "x",
                    "openai_summary_model": "gpt-4o-mini"}

        def fake_generate(transcript, cfg):
            return "### Короткое название\nrelease-process\n"

        monkeypatch.setattr(process, "load_config", fake_load_config)
        monkeypatch.setattr(process, "generate_summary", fake_generate)

        result = cli_runner.invoke(cli_app, ["resummarize", str(folder)])
        assert result.exit_code != 0
        assert "parse" in result.output.lower()

    def test_renames_folder_when_topic_changes(self, cli_app, tmp_path, monkeypatch):
        cli_runner.invoke(cli_app, ["migrate"])
        folder = self._make_folder(
            tmp_path, "2026-05-13-13.13-meeting",
            "[00:00] SPEAKER_00: release process walkthrough today\n",
        )

        from src import state
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mov", 1000, 100, 10.0)
            conn.execute(
                "UPDATE videos SET output_path=? WHERE id=?",
                (str(folder), vid),
            )
            conn.commit()

        from src import process

        def fake_load_config():
            return {"summary_backend": "openai", "openai_api_key": "x",
                    "openai_summary_model": "gpt-4o-mini"}

        def fake_generate(transcript, cfg):
            return "### Короткое название\nrelease process\n\n### Тема\nfoo\n"

        monkeypatch.setattr(process, "load_config", fake_load_config)
        monkeypatch.setattr(process, "generate_summary", fake_generate)

        result = cli_runner.invoke(cli_app, ["resummarize", str(folder)])
        assert result.exit_code == 0, result.output

        new_folder = tmp_path / "2026-05-13-13.13-release-process"
        assert new_folder.is_dir()
        assert not folder.exists()
        assert (new_folder / "2026-05-13-13.13-release-process-transcript.txt").exists()
        assert (new_folder / "2026-05-13-13.13-release-process-summary.md").exists()
        assert (new_folder / "2026-05-13-13.13-release-process.mov").exists()

        with state.connection() as conn:
            row = conn.execute(
                "SELECT output_path FROM videos WHERE id=?", (vid,)
            ).fetchone()
        assert row["output_path"] == str(new_folder)

    def test_renames_folder_updates_fts(self, cli_app, tmp_path, monkeypatch):
        cli_runner.invoke(cli_app, ["migrate"])
        folder = self._make_folder(
            tmp_path, "2026-05-13-13.13-meeting",
            "[00:00] SPEAKER_00: release process walkthrough today\n",
        )
        from src import state
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mov", 1000, 100, 10.0)
            conn.execute(
                "UPDATE videos SET output_path=? WHERE id=?",
                (str(folder), vid),
            )
            conn.commit()

        from src import process

        def fake_load_config():
            return {"summary_backend": "openai", "openai_api_key": "x",
                    "openai_summary_model": "gpt-4o-mini"}

        def fake_generate(transcript, cfg):
            return "### Короткое название\nrelease process\n"

        monkeypatch.setattr(process, "load_config", fake_load_config)
        monkeypatch.setattr(process, "generate_summary", fake_generate)

        result = cli_runner.invoke(cli_app, ["resummarize", str(folder)])
        assert result.exit_code == 0, result.output

        with state.connection() as conn:
            rows = state.search_meeting_fts(conn, "release")
        assert any(r["id"] == vid for r in rows)

    def test_no_rename_flag_keeps_folder(self, cli_app, tmp_path, monkeypatch):
        cli_runner.invoke(cli_app, ["migrate"])
        folder = self._make_folder(
            tmp_path, "2026-05-13-13.13-meeting",
            "[00:00] SPEAKER_00: hello\n",
        )

        from src import process

        def fake_load_config():
            return {"summary_backend": "openai", "openai_api_key": "x",
                    "openai_summary_model": "gpt-4o-mini"}

        def fake_generate(transcript, cfg):
            return "### Короткое название\nrelease process\n"

        monkeypatch.setattr(process, "load_config", fake_load_config)
        monkeypatch.setattr(process, "generate_summary", fake_generate)

        result = cli_runner.invoke(
            cli_app, ["resummarize", str(folder), "--no-rename"]
        )
        assert result.exit_code == 0
        assert folder.is_dir()
        summary = (folder / "2026-05-13-13.13-meeting-summary.md").read_text()
        assert "release process" in summary


class TestSearchCommand:
    def test_search_no_matches_prints_message(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        result = cli_runner.invoke(cli_app, ["search", "nothing"])
        assert result.exit_code == 0
        assert "No matches" in result.output

    def test_search_returns_seeded_meeting(self, cli_app):
        cli_runner.invoke(cli_app, ["migrate"])
        from src import state
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mov", 1000, 100, 10.0)
            conn.execute(
                "UPDATE videos SET output_path=?, state='done' WHERE id=?",
                ("/out/2026-05-13-release", vid),
            )
            state.upsert_meeting_fts(
                conn, vid, "2026-05-13-release",
                "SPEAKER_00: release process explanation",
                "Release tutorial",
            )
            conn.commit()
        result = cli_runner.invoke(cli_app, ["search", "release"])
        assert result.exit_code == 0
        assert "2026-05-13-release" in result.output


class TestReindexCommand:
    def test_reindexes_known_folder_into_videos(self, cli_app, tmp_path, monkeypatch):
        cli_runner.invoke(cli_app, ["migrate"])
        out = tmp_path / "out"
        out.mkdir()
        f = out / "2026-05-13-release-process"
        f.mkdir()
        (f / "2026-05-13-release-process-transcript.txt").write_text(
            "SPEAKER_00: release process discussion"
        )
        (f / "2026-05-13-release-process-summary.md").write_text(
            "Release tutorial"
        )

        from src import state
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mov", 1000, 100, 10.0)
            conn.execute(
                "UPDATE videos SET output_path=?, state='done' WHERE id=?",
                (str(f), vid),
            )
            conn.commit()

        from src import process

        def fake_load_config():
            return {"output_dir": out}

        monkeypatch.setattr(process, "load_config", fake_load_config)

        result = cli_runner.invoke(cli_app, ["reindex"])
        assert result.exit_code == 0
        assert "Reindexed 1" in result.output

        with state.connection() as conn:
            rows = state.search_meeting_fts(conn, "release")
        assert len(rows) == 1
        assert str(f) == rows[0]["output_path"]

    def test_reindex_unknown_folder_uses_synthetic_id(self, cli_app, tmp_path, monkeypatch):
        """Folders without a matching videos row still get indexed under a negative id,
        searchable via the raw meeting_fts table (not the JOINed search_meeting_fts)."""
        cli_runner.invoke(cli_app, ["migrate"])
        out = tmp_path / "out"
        out.mkdir()
        f = out / "2026-05-13-orphan"
        f.mkdir()
        (f / "2026-05-13-orphan-transcript.txt").write_text("orphaned meeting bytes")
        (f / "2026-05-13-orphan-summary.md").write_text("summary")

        from src import process
        monkeypatch.setattr(process, "load_config", lambda: {"output_dir": out})

        result = cli_runner.invoke(cli_app, ["reindex"])
        assert result.exit_code == 0
        assert "Reindexed 1" in result.output

        from src import state
        with state.connection() as conn:
            row = conn.execute(
                "SELECT video_id, folder_name FROM meeting_fts WHERE meeting_fts MATCH 'orphan'",
            ).fetchone()
        assert row is not None
        assert row["video_id"] < 0
        assert row["folder_name"] == "2026-05-13-orphan"
