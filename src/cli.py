"""meetscribe CLI - typer entry point.

Subcommands: ls, show, migrate, process, retry, skip, reprocess, daemon.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

import typer

from src import state
from src.state import runner
from src.swiftbar import notify_swiftbar_refresh

app = typer.Typer(help="meetscribe - meeting recording processor")


def _fmt_ts(ts: int | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


@app.command()
def migrate() -> None:
    """Apply pending schema migrations."""
    with state.connection() as conn:
        applied = runner.apply_migrations(conn)
    typer.echo(f"Applied {applied} migrations.")


@app.command(name="ls")
def list_cmd(
    state_filter: str = typer.Option(None, "--state", "-s", help="Filter by state"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List videos from state.db."""
    with state.connection() as conn:
        runner.apply_migrations(conn)
        videos = state.list_videos(conn, state=state_filter, limit=limit)
    if not videos:
        typer.echo("No videos.")
        raise typer.Exit(code=0)
    typer.echo(f"{'ID':<4} {'STATE':<12} {'BACKEND':<8} {'ATTEMPTS':<8} {'UPDATED':<19} PATH")
    for v in videos:
        typer.echo(
            f"{v['id']:<4} {v['state']:<12} {(v.get('backend_used') or '-'):<8} "
            f"{v['attempts_count']:<8} {_fmt_ts(v['updated_at']):<19} {v['path']}"
        )


@app.command()
def show(id_or_path: str) -> None:
    """Show full details for one video by id or path."""
    with state.connection() as conn:
        runner.apply_migrations(conn)
        video = state.get_video(conn, id_or_path)
        if video is None:
            typer.echo(f"Video not found: {id_or_path}", err=True)
            raise typer.Exit(code=1)
        attempts = state.get_attempts(conn, video["id"])
        events = state.get_events(conn, video["id"], limit=20)

    typer.echo(f"Video {video['id']}")
    typer.echo(f"  Path:        {video['path']}")
    typer.echo(f"  State:       {video['state']}")
    typer.echo(f"  Detected:    {_fmt_ts(video['detected_at'])}")
    typer.echo(f"  Started:     {_fmt_ts(video.get('started_at'))}")
    typer.echo(f"  Completed:   {_fmt_ts(video.get('completed_at'))}")
    typer.echo(f"  Backend:     {video.get('backend_used') or '-'}")
    typer.echo(f"  Output:      {video.get('output_path') or '-'}")
    typer.echo("")
    typer.echo(f"Attempts ({len(attempts)}):")
    for a in attempts:
        ec = a.get("exit_code")
        ec_str = f"exit {ec}" if ec is not None else "running"
        typer.echo(
            f"  #{a['attempt_num']}  {a['backend']:<7} started {_fmt_ts(a['started_at'])}  "
            f"completed {_fmt_ts(a.get('completed_at'))}  {ec_str}"
        )
        if a.get("error_message"):
            typer.echo(f"      error: {a['error_message']}")
    typer.echo("")
    typer.echo(f"Events (recent first, up to 20):")
    for e in events:
        details = e.get("details") or ""
        typer.echo(f"  {_fmt_ts(e['ts'])}  {e['event_type']:<22} {details}")


@app.command()
def process(video: Path) -> None:
    """Process a video (alias for python -m src.process)."""
    from src.process import process_video
    process_video(str(video))


import time as _time


@app.command()
def retry(id_or_path: str) -> None:
    """Reset video state to 'detected' so daemon will reprocess it."""
    with state.connection() as conn:
        runner.apply_migrations(conn)
        video = state.get_video(conn, id_or_path)
        if video is None:
            typer.echo(f"Video not found: {id_or_path}", err=True)
            raise typer.Exit(code=1)
        state.mark_for_retry(conn, video["id"])
    notify_swiftbar_refresh()
    typer.echo(f"Marked for retry: {video['path']}")


@app.command()
def skip(id_or_path: str) -> None:
    """Mark video as skipped (daemon will not process it again)."""
    with state.connection() as conn:
        runner.apply_migrations(conn)
        video = state.get_video(conn, id_or_path)
        if video is None:
            typer.echo(f"Video not found: {id_or_path}", err=True)
            raise typer.Exit(code=1)
        state.mark_skipped(conn, video["id"], reason="user request")
    notify_swiftbar_refresh()
    typer.echo(f"Skipped: {video['path']}")


@app.command()
def resummarize(
    folder: Path = typer.Argument(..., help="Output folder containing -transcript.txt"),
    rename: bool = typer.Option(
        True, "--rename/--no-rename",
        help="Rename folder + files if new topic differs from current (default: yes)",
    ),
) -> None:
    """Regenerate summary.md from existing transcript.

    Reads <folder>/*-transcript.txt, calls the configured summary backend,
    overwrites *-summary.md. By default also renames the folder + all files
    inside if the new short title differs, and updates videos.output_path in
    state.db. Useful for folders left as `<date>-meeting` after summary failed.
    """
    from src.process import (
        derive_topic_from_transcript,
        extract_topic,
        generate_summary,
        load_config,
        sanitize_filename,
    )

    folder = folder.resolve()
    if not folder.is_dir():
        typer.echo(f"Not a directory: {folder}", err=True)
        raise typer.Exit(code=1)

    transcript_files = list(folder.glob("*-transcript.txt"))
    if not transcript_files:
        typer.echo(f"No *-transcript.txt found in {folder}", err=True)
        raise typer.Exit(code=1)
    if len(transcript_files) > 1:
        typer.echo(
            f"Multiple transcripts in {folder} - ambiguous: "
            f"{[p.name for p in transcript_files]}",
            err=True,
        )
        raise typer.Exit(code=1)
    transcript_path = transcript_files[0]
    transcript = transcript_path.read_text(encoding="utf-8")

    cfg = load_config()
    typer.echo(f"Generating summary via {cfg['summary_backend']}...")
    summary = generate_summary(transcript, cfg)

    new_topic = extract_topic(summary)
    if new_topic in ("", "meeting"):
        new_topic = derive_topic_from_transcript(transcript)

    import re as _re
    base = transcript_path.name.removesuffix("-transcript.txt")
    m = _re.match(r"^(\d{4}-\d{2}-\d{2}(?:-\d{2}\.\d{2})?)-(.+)$", base)
    if m is None:
        typer.echo(
            f"Cannot parse folder name '{base}' - expected "
            "YYYY-MM-DD[-HH.MM]-topic format",
            err=True,
        )
        raise typer.Exit(code=1)
    date_str = m.group(1)
    old_topic = m.group(2)

    summary_path = folder / f"{base}-summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    typer.echo(f"Wrote {summary_path}")

    new_topic_sanitized = sanitize_filename(new_topic) or "meeting"
    if not rename or new_topic_sanitized == sanitize_filename(old_topic):
        with state.connection() as conn:
            runner.apply_migrations(conn)
            row = conn.execute(
                "SELECT id FROM videos WHERE output_path=?", (str(folder),)
            ).fetchone()
            if row is not None:
                state.upsert_meeting_fts(
                    conn, row["id"], folder.name, transcript, summary,
                )
                conn.commit()
        typer.echo("Done.")
        return

    new_base = f"{date_str}-{new_topic_sanitized}"
    new_folder = folder.parent / new_base
    if new_folder.exists():
        for i in range(2, 100):
            candidate = folder.parent / f"{new_base}-{i}"
            if not candidate.exists():
                new_folder = candidate
                new_base = f"{new_base}-{i}"
                break

    new_folder_tmp = folder.parent / f".tmp-rename-{int(_time.time())}-{new_base}"
    folder.rename(new_folder_tmp)
    for p in list(new_folder_tmp.iterdir()):
        if p.name.startswith(base):
            new_name = new_base + p.name[len(base):]
            p.rename(new_folder_tmp / new_name)
    new_folder_tmp.rename(new_folder)
    typer.echo(f"Renamed: {folder.name} -> {new_folder.name}")

    with state.connection() as conn:
        runner.apply_migrations(conn)
        conn.execute(
            "UPDATE videos SET output_path=? WHERE output_path=?",
            (str(new_folder), str(folder)),
        )
        row = conn.execute(
            "SELECT id FROM videos WHERE output_path=?", (str(new_folder),)
        ).fetchone()
        if row is not None:
            state.upsert_meeting_fts(
                conn, row["id"], new_folder.name, transcript, summary,
            )
        conn.commit()
    typer.echo("Updated state.db output_path.")


@app.command()
def reprocess(id_or_path: str) -> None:
    """Archive existing output_dir (rename) and reset state to 'detected'."""
    with state.connection() as conn:
        runner.apply_migrations(conn)
        video = state.get_video(conn, id_or_path)
        if video is None:
            typer.echo(f"Video not found: {id_or_path}", err=True)
            raise typer.Exit(code=1)
        out_path = video.get("output_path")
        if out_path:
            out = Path(out_path)
            if out.exists():
                archived = out.parent / f"{out.name}.archived-{int(_time.time())}"
                out.rename(archived)
                typer.echo(f"Archived old output: {archived}")
        state.mark_for_retry(conn, video["id"])
    notify_swiftbar_refresh()
    typer.echo(f"Reset for reprocessing: {video['path']}")


@app.command()
def swiftbar() -> None:
    """Render SwiftBar plugin output to stdout."""
    from src.swiftbar import render
    with state.connection() as conn:
        runner.apply_migrations(conn)
    typer.echo(render(), nl=False)


@app.command()
def cancel(id_or_path: str) -> None:
    """Cancel currently processing or queued video."""
    with state.connection() as conn:
        runner.apply_migrations(conn)
        video = state.get_video(conn, id_or_path)
        if video is None:
            typer.echo(f"Video not found: {id_or_path}", err=True)
            raise typer.Exit(code=1)
        if video["state"] not in ("queued", "processing"):
            typer.echo(
                f"Cannot cancel video in state '{video['state']}'. "
                "Only 'queued' or 'processing' allowed.",
                err=True,
            )
            raise typer.Exit(code=1)
        state.transition_state(conn, video["id"], "cancelled",
                               extra_event_details={"by": "user"})
    notify_swiftbar_refresh()
    typer.echo(f"Cancelled: {video['path']}")
    typer.echo("Worker will exit current stage and stop processing.")


daemon_app = typer.Typer(help="Watcher daemon management")
app.add_typer(daemon_app, name="daemon")

DAEMON_LABEL = "com.myron.meetscribe.watcher"


def _domain() -> str:
    return f"gui/{os.getuid()}"


@daemon_app.command("status")
def daemon_status() -> None:
    """Show launchd status of meetscribed-watcher."""
    result = subprocess.run(
        ["launchctl", "print", f"{_domain()}/{DAEMON_LABEL}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        typer.echo(result.stdout)
    else:
        typer.echo("Not loaded")


@daemon_app.command("logs")
def daemon_logs(tail_n: int = typer.Option(50, "--tail", "-n")) -> None:
    """Tail watcher.log."""
    project_root = Path(__file__).parent.parent
    log_path = project_root / ".logs" / "watcher.log"
    if not log_path.exists():
        typer.echo(f"Log file does not exist: {log_path}", err=True)
        raise typer.Exit(code=1)
    subprocess.run(["tail", "-n", str(tail_n), str(log_path)])


@daemon_app.command("restart")
def daemon_restart() -> None:
    """Bootout + bootstrap watcher."""
    plist_dst = Path.home() / "Library" / "LaunchAgents" / f"{DAEMON_LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{DAEMON_LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", _domain(), str(plist_dst)], capture_output=True)
    typer.echo("Restarted.")


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Bootout watcher (auto-restart on next system event due to KeepAlive=true)."""
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{DAEMON_LABEL}"], capture_output=True)
    typer.echo("Stopped.")


config_app = typer.Typer(help="Edit and validate .env config")
app.add_typer(config_app, name="config")


@config_app.callback(invoke_without_command=True)
def config_default(ctx: typer.Context) -> None:
    """Open Textual TUI when called without a sub-command."""
    if ctx.invoked_subcommand is not None:
        return
    from src.config_tui import run_config_tui
    from src.paths import env_path as _env_path

    raise typer.Exit(run_config_tui(_env_path()))


@config_app.command("verify")
def config_verify() -> None:
    """Validate current .env. Exits 0 on success, 1 on any error."""
    from src.config_io import read_env
    from src.config_schema import validate_env
    from src.paths import env_path as _env_path

    values = read_env(_env_path())
    errors = validate_env(values)
    if not errors:
        print("OK")
        raise typer.Exit(0)
    for err in errors:
        print(f"ERROR {err.message}")
    raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Argument(..., help="FTS5 query - words, prefixes (foo*), phrases (\"a b\")"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Full-text search across meeting transcripts and summaries."""
    with state.connection() as conn:
        runner.apply_migrations(conn)
        try:
            rows = state.search_meeting_fts(conn, query, limit=limit)
        except Exception as e:
            typer.echo(f"Search failed: {e}", err=True)
            raise typer.Exit(code=1)
    if not rows:
        typer.echo("No matches.")
        raise typer.Exit(code=0)
    for r in rows:
        folder = r.get("output_path") or "-"
        typer.echo(f"[{r['id']}] {folder}")
        snippet = (r.get("transcript_snippet") or "").strip()
        if snippet:
            typer.echo(f"   transcript: {snippet}")
        sm = (r.get("summary_snippet") or "").strip()
        if sm:
            typer.echo(f"   summary:    {sm}")


@app.command("reindex")
def reindex(
    output_dir: Path = typer.Option(
        None, "--output-dir",
        help="Override OUTPUT_DIR root. Default: cfg['output_dir'] from .env",
    ),
) -> None:
    """Backfill FTS5 index from existing transcript/summary files on disk.

    Walks <output_dir>/* looking for <base>-transcript.txt + <base>-summary.md
    pairs. Each match is upserted into meeting_fts. If a matching row exists
    in videos (by output_path), its video_id is reused; otherwise a synthetic
    negative id is generated so the meeting is still searchable.
    """
    import sqlite3 as _sql
    from src.process import load_config

    root = output_dir
    if root is None:
        cfg = load_config()
        root = cfg["output_dir"]
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        typer.echo(f"Not a directory: {root}", err=True)
        raise typer.Exit(code=1)

    with state.connection() as conn:
        runner.apply_migrations(conn)
        indexed = 0
        skipped = 0
        synthetic_next = -1
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            transcripts = list(folder.glob("*-transcript.txt"))
            if not transcripts:
                continue
            tpath = transcripts[0]
            base = tpath.name.removesuffix("-transcript.txt")
            spath = folder / f"{base}-summary.md"
            if not spath.exists():
                skipped += 1
                continue
            transcript = tpath.read_text(encoding="utf-8", errors="replace")
            summary = spath.read_text(encoding="utf-8", errors="replace")
            row = conn.execute(
                "SELECT id FROM videos WHERE output_path=?", (str(folder),)
            ).fetchone()
            if row is not None:
                video_id = row["id"]
            else:
                video_id = synthetic_next
                synthetic_next -= 1
            try:
                state.upsert_meeting_fts(conn, video_id, folder.name, transcript, summary)
                indexed += 1
            except _sql.Error as e:
                typer.echo(f"  skip {folder.name}: {e}", err=True)
                skipped += 1
        conn.commit()
    typer.echo(f"Reindexed {indexed} meetings, skipped {skipped}.")


@app.command("web")
def web(
    port: int = typer.Option(8123, "--port", "-p", help="HTTP port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
) -> None:
    """Start a local-only web UI for searching meeting history."""
    from src.web import serve
    serve(host=host, port=port)


@app.command("self-uninstall")
def self_uninstall(
    keep_data: bool = typer.Option(
        True, "--keep-data/--no-keep-data",
        help="Keep state.db, .env, and default OUTPUT_DIR (default: keep)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove meetscribe install. --no-keep-data also wipes state.db and .env."""
    from src.lifecycle import uninstall as do_uninstall
    if not yes:
        typer.confirm("Remove meetscribe install?", abort=True)
        if not keep_data:
            typer.confirm("Also delete state.db, .env, and default OUTPUT_DIR?",
                          abort=True)
    do_uninstall(keep_data=keep_data)


@app.command("self-update")
def self_update(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Re-run bootstrap.sh to upgrade to the latest main."""
    import subprocess
    if not yes:
        typer.confirm(
            "Download and run bootstrap.sh from main? "
            "(Existing services will be restarted)",
            abort=True,
        )
    subprocess.run(
        "curl -fsSL https://raw.githubusercontent.com/mshykhov/meetscribe/main/"
        "bootstrap.sh | bash",
        shell=True, check=True,
    )


if __name__ == "__main__":
    app()
