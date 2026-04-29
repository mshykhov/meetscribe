"""meetscribe CLI - typer entry point. Subcommands: ls, show, migrate, process."""

from datetime import datetime
from pathlib import Path

import typer

from src import state
from src.state import runner

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


if __name__ == "__main__":
    app()
