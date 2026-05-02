#!/usr/bin/env python3
"""Process a meeting video: transcribe, diarize, summarize, organize."""

import argparse
import gc
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import whisperx_mlx
from dotenv import load_dotenv

from src import state
from src.notify import notify_event
from src.sidecar import SidecarError, load_sidecar
from src.state import runner as _state_runner
from src.swiftbar import notify_swiftbar_refresh

_log = logging.getLogger(__name__)

# Use cached models, skip update checks
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "true")
# Prevent OMP conflicts between torch and CoreML in senko subprocess
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def _patch_senko_python_path():
    """Fix whisperx-mlx senko backend: use venv Python, not system Python."""
    try:
        from whisperx_mlx.diarization import senko_backend
        original = senko_backend.SenkoDiarizationPipeline._run_senko_subprocess

        def patched(self, audio_path, min_speakers, max_speakers):
            import tempfile
            script_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', delete=False
            )
            script_file.write(senko_backend.SENKO_SUBPROCESS_SCRIPT)
            script_file.close()
            try:
                env = os.environ.copy()
                env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
                env["OMP_NUM_THREADS"] = "1"
                result = subprocess.run(
                    [sys.executable, script_file.name, audio_path,
                     str(min_speakers), str(max_speakers), self._device],
                    capture_output=True, text=True, timeout=3600, env=env,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"Senko subprocess failed (exit {result.returncode}): "
                        f"{result.stderr[-500:]}"
                    )
                import json
                return json.loads(result.stdout)
            finally:
                os.unlink(script_file.name)

        senko_backend.SenkoDiarizationPipeline._run_senko_subprocess = patched
    except (ImportError, AttributeError):
        pass


_patch_senko_python_path()

SUMMARY_PROMPT = """Ты - ассистент для анализа записей встреч.

Проанализируй транскрипцию встречи и создай структурированное саммари на русском языке:

## Формат ответа

### Короткое название
2-4 слова на английском для имени файла (например: "sprint review", "api design", "onboarding sync").

### Тема встречи
Одно предложение.

### Участники
Список спикеров (SPEAKER_00, SPEAKER_01 и т.д.) - если можно определить роли из контекста, укажи.

### Ключевые решения
- Пронумерованный список принятых решений

### Action Items (задачи для Myron)
- Конкретные задачи, которые нужно выполнить, с дедлайнами если упомянуты
- Выдели особо задачи, адресованные напрямую мне (Myron/Мирон)

### Важные моменты
- Ключевая информация, цифры, даты, ссылки упомянутые на встрече

### Краткое содержание
2-3 абзаца с основным содержанием встречи.

---

Транскрипция:

"""

MAX_VIDEO_DURATION_SEC = 4 * 3600  # 4 hours hard limit
WHISPERX_TIMEOUT_SEC = 3600  # 1 hour max for transcription


class TranscriptionTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise TranscriptionTimeout("Transcription timed out")


def load_config() -> dict:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    return {
        "hf_token": os.environ["HF_TOKEN"],
        "output_dir": Path(os.environ.get("OUTPUT_DIR", "~/docs/video")).expanduser(),
        "whisper_model": os.environ.get("WHISPER_MODEL", "large-v2"),
        "language": os.environ.get("LANGUAGE", "") or None,
        "max_speakers": int(os.environ.get("MAX_SPEAKERS", "0")) or None,
        "claude_model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
        "claude_cli": os.environ.get("CLAUDE_CLI", "claude"),
        "transcribe_backend": os.environ.get("TRANSCRIBE_BACKEND", "local"),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "openai_transcribe_model": os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1"),
        "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
        "groq_transcribe_model": os.environ.get("GROQ_TRANSCRIBE_MODEL", "whisper-large-v3"),
        "summary_backend": os.environ.get("SUMMARY_BACKEND", "claude_code"),
        "openai_summary_model": os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4o-mini"),
        "groq_summary_model": os.environ.get("GROQ_SUMMARY_MODEL", "llama-3.3-70b-versatile"),
    }


def get_recording_date(video_path: str) -> str:
    """Get recording datetime from video metadata, file mtime, or current time."""
    # Try creation_time from video metadata (stored in UTC)
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format_tags=creation_time",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True,
    )
    ts = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
    if ts and "T" in ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d-%H.%M")
        except ValueError:
            return ts[:10]

    # Fallback: file modification time (already local)
    try:
        mtime = Path(video_path).stat().st_mtime
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d-%H.%M")
    except OSError:
        pass

    return datetime.now().strftime("%Y-%m-%d-%H.%M")


def get_audio_duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _run_step(step_script: str, tmp_dir: Path, timeout: int = WHISPERX_TIMEOUT_SEC) -> None:
    """Run a pipeline step in an isolated subprocess to guarantee memory release."""
    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", step_script],
        timeout=timeout, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Pipeline step failed with exit code {result.returncode}")


def transcribe(video_path: str, cfg: dict, video_id: int | None = None) -> dict:
    duration = get_audio_duration(video_path)
    duration_min = int(duration // 60)

    if duration > MAX_VIDEO_DURATION_SEC:
        raise ValueError(
            f"Video too long: {duration_min}m (max {MAX_VIDEO_DURATION_SEC // 60}m). "
            f"Split the video first."
        )

    est_min = max(1, int(duration / 60 * 0.2))
    print(f"Video duration: {duration_min}m, estimated processing: ~{est_min}m")

    # Resume support: load existing partial_data if any
    partial_data, partial_stage = _load_partial(video_id)
    if partial_stage is not None:
        print(f"Resuming from after stage: {partial_stage}")

    import tempfile
    tmp_dir = Path(tempfile.mkdtemp(prefix="meetscribe-"))
    data_file = tmp_dir / "pipeline_data.json"

    try:
        backend = cfg.get("transcribe_backend", "local")
        if backend in ("openai", "groq"):
            if partial_stage is None:
                _check_cancelled(video_id)
                if video_id is not None:
                    _safe_state(state.set_current_stage, video_id, "transcribe")
                    notify_swiftbar_refresh()
                api_key_cfg = "groq_api_key" if backend == "groq" else "openai_api_key"
                model_cfg = "groq_transcribe_model" if backend == "groq" else "openai_transcribe_model"
                print(f"[1/4] Transcribing via {backend} ({cfg[model_cfg]})...")
                from src.openai_transcribe import transcribe_via_openai
                data = transcribe_via_openai(
                    Path(video_path),
                    backend=backend,
                    api_key=cfg[api_key_cfg],
                    model=cfg[model_cfg],
                    language=cfg.get("language"),
                )
                data_file.write_text(json.dumps(data))
                print(f"       Detected language: {data['language']}")
                _write_partial(video_id, data, "align")
            else:
                data = partial_data
                data_file.write_text(json.dumps(data))
                print(f"       Detected language: {data.get('language', '?')} (from partial)")
        else:
            # Local backend: stage 1 (transcribe) - skip if resuming
            if partial_stage is None:
                _check_cancelled(video_id)
                if video_id is not None:
                    _safe_state(state.set_current_stage, video_id, "transcribe")
                    notify_swiftbar_refresh()
                print(f"[1/4] Transcribing ({cfg['whisper_model']}, MLX GPU)...")
                _run_step(f"""
import json
from pathlib import Path
import whisperx_mlx

result = whisperx_mlx.transcribe(
    {video_path!r},
    model={cfg['whisper_model']!r},
    backend="mlx",
    compute_type="float16",
    batch_size=16,
    language={cfg['language']!r},
    print_progress=True,
)
Path({str(data_file)!r}).write_text(json.dumps({{
    "segments": result["segments"],
    "language": result["language"],
}}))
""", tmp_dir)
                data = json.loads(data_file.read_text())
                _write_partial(video_id, data, "transcribe")
            else:
                data = partial_data
                data_file.write_text(json.dumps(data))

            language = data["language"]
            print(f"       Detected language: {language}")

            # Stage 2: Align - skip if resuming from align or later
            if partial_stage in (None, "transcribe"):
                _check_cancelled(video_id)
                if video_id is not None:
                    _safe_state(state.set_current_stage, video_id, "align")
                    notify_swiftbar_refresh()
                print("[2/4] Aligning words...")
                _run_step(f"""
import json
from pathlib import Path
import whisperx_mlx

data = json.loads(Path({str(data_file)!r}).read_text())
audio = whisperx_mlx.audio.load_audio({video_path!r})
align_model, metadata = whisperx_mlx.load_align_model(
    language_code=data["language"], device="cpu"
)
result = whisperx_mlx.align(
    data["segments"], align_model, metadata, audio, device="cpu",
    print_progress=True,
)
Path({str(data_file)!r}).write_text(json.dumps({{
    "segments": result["segments"],
    "language": data["language"],
}}))
""", tmp_dir)
                data = json.loads(data_file.read_text())
                _write_partial(video_id, data, "align")

        # Stage 3: Diarize - skip if resuming from diarize
        if partial_stage != "diarize":
            _check_cancelled(video_id)
            if video_id is not None:
                _safe_state(state.set_current_stage, video_id, "diarize")
                notify_swiftbar_refresh()
            print("[3/4] Diarizing speakers...")
            max_diarize_attempts = 3
            diarize_ok = False
            for attempt in range(1, max_diarize_attempts + 1):
                try:
                    _run_step(f"""
import json, os, sys, subprocess, tempfile
from pathlib import Path

# Patch senko to use venv Python
try:
    from whisperx_mlx.diarization import senko_backend
    def _patched_senko(self, audio_path, min_speakers, max_speakers):
        sf = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
        sf.write(senko_backend.SENKO_SUBPROCESS_SCRIPT)
        sf.close()
        try:
            env = os.environ.copy()
            env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
            env["OMP_NUM_THREADS"] = "1"
            r = subprocess.run(
                [sys.executable, sf.name, audio_path,
                 str(min_speakers), str(max_speakers), self._device],
                capture_output=True, text=True, timeout=3600, env=env,
            )
            if r.returncode != 0:
                raise RuntimeError(f"Senko subprocess failed (exit {{r.returncode}}): {{r.stderr[-500:]}}")
            return json.loads(r.stdout)
        finally:
            os.unlink(sf.name)
    senko_backend.SenkoDiarizationPipeline._run_senko_subprocess = _patched_senko
except (ImportError, AttributeError):
    pass

import whisperx_mlx

data = json.loads(Path({str(data_file)!r}).read_text())
audio = whisperx_mlx.audio.load_audio({video_path!r})
diarize_pipeline = whisperx_mlx.DiarizationPipeline(
    use_auth_token={cfg['hf_token']!r},
    backend="senko",
)
diarize_segments = diarize_pipeline(audio{', max_speakers=' + str(cfg['max_speakers']) if cfg['max_speakers'] else ''})
result = whisperx_mlx.assign_word_speakers(diarize_segments, {{"segments": data["segments"]}})
Path({str(data_file)!r}).write_text(json.dumps({{
    "segments": result["segments"],
    "language": data["language"],
}}))
""", tmp_dir)
                    diarize_ok = True
                    data = json.loads(data_file.read_text())
                    break
                except Exception as e:
                    if attempt < max_diarize_attempts:
                        print(f"WARNING: Diarization attempt {attempt}/{max_diarize_attempts} failed: {e}")
                        print(f"         Retrying...")
                    else:
                        print(f"WARNING: Diarization failed after {max_diarize_attempts} attempts, continuing without speakers: {e}")
            _write_partial(video_id, data, "diarize")

        return {"segments": data["segments"], "language": data["language"]}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def build_transcript(result: dict) -> str:
    lines = []
    for seg in result["segments"]:
        ts = format_timestamp(seg["start"])
        speaker = seg.get("speaker", "Unknown")
        text = seg["text"].strip()
        lines.append(f"[{ts}] {speaker}: {text}")
    return "\n".join(lines)


def _safe_state(callable_, *args, **kwargs):
    """Run a state.db write callable, swallowing exceptions.

    State writes are observability, not critical path. If the db is unwritable,
    pipeline must still complete. Errors are logged.
    """
    try:
        with state.connection() as conn:
            _state_runner.apply_migrations(conn)
            return callable_(conn, *args, **kwargs)
    except Exception as e:
        _log.warning("state.db write failed: %s", e)
        return None


class CancelledError(Exception):
    """Raised when video has been cancelled by user mid-pipeline."""


def _check_cancelled(video_id: int | None) -> None:
    """Raise CancelledError if state.db says video was cancelled."""
    if video_id is None:
        return
    try:
        with state.connection() as conn:
            row = conn.execute("SELECT state FROM videos WHERE id=?", (video_id,)).fetchone()
    except Exception:
        return
    if row and row["state"] == "cancelled":
        raise CancelledError(f"video {video_id} cancelled by user")


def _write_partial(video_id: int | None, partial_data: dict, partial_stage: str) -> None:
    """Persist partial pipeline output to state.db for resume on crash."""
    if video_id is None:
        return
    blob = json.dumps(partial_data).encode("utf-8")
    try:
        with state.connection() as conn:
            conn.execute(
                "UPDATE videos SET partial_data=?, partial_stage=?, "
                "updated_at=strftime('%s','now') WHERE id=?",
                (blob, partial_stage, video_id),
            )
            state.record_event(conn, video_id, "partial_saved", {"stage": partial_stage})
    except Exception as e:
        _log.warning("failed to write partial_data: %s", e)


def _load_partial(video_id: int | None) -> tuple[dict | None, str | None]:
    """Return (partial_data, partial_stage) from db; (None, None) if no partial."""
    if video_id is None:
        return None, None
    try:
        with state.connection() as conn:
            row = conn.execute(
                "SELECT partial_data, partial_stage FROM videos WHERE id=?",
                (video_id,)
            ).fetchone()
    except Exception:
        return None, None
    if row is None or row["partial_data"] is None:
        return None, None
    return json.loads(row["partial_data"]), row["partial_stage"]


def generate_summary(transcript: str, cfg: dict) -> str:
    from src.summarize import call_summary_provider, max_transcript_chars

    threshold = max_transcript_chars(cfg)
    if len(transcript) <= threshold:
        return call_summary_provider(SUMMARY_PROMPT + transcript, cfg)

    print(f"Transcript too long ({len(transcript)} chars), splitting into chunks...")
    lines = transcript.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        if current_len + len(line) > threshold and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(line)
        current_len += len(line) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    print(f"Split into {len(chunks)} chunks, summarizing each...")
    partial_summaries = []
    for i, chunk in enumerate(chunks):
        print(f"  Summarizing chunk {i + 1}/{len(chunks)}...")
        chunk_prompt = (
            f"Суммаризируй часть {i + 1} из {len(chunks)} транскрипции встречи. "
            f"Выдели ключевые решения, action items для Myron, важные моменты.\n\n"
            f"Транскрипция (часть {i + 1}):\n\n{chunk}"
        )
        partial = call_summary_provider(chunk_prompt, cfg)
        partial_summaries.append(partial)

    print("  Merging chunk summaries into final...")
    merge_prompt = (
        SUMMARY_PROMPT
        + "ОБЪЕДИНЕННЫЕ САММАРИ ЧАСТЕЙ ВСТРЕЧИ:\n\n"
        + "\n\n---\n\n".join(
            f"=== Часть {i + 1} ===\n{s}" for i, s in enumerate(partial_summaries)
        )
    )
    return call_summary_provider(merge_prompt, cfg)


def extract_topic(summary: str) -> str:
    lines = summary.split("\n")
    for i, line in enumerate(lines):
        if "короткое название" in line.lower() or "short name" in line.lower():
            for next_line in lines[i + 1 : i + 3]:
                text = next_line.strip().strip("#").strip("-").strip()
                text = text.strip('"').strip("'").strip("`")
                if text:
                    return sanitize_filename(text)
    return "meeting"


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}


def sanitize_filename(name: str) -> str:
    name = name.lower().strip()
    name = "".join(_TRANSLIT.get(c, c) for c in name)
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")[:50]


def organize_files(
    video_path: str, transcript: str, summary: str, date_str: str, cfg: dict,
) -> Path:
    video = Path(video_path)
    topic = extract_topic(summary)
    folder_name = f"{date_str}-{topic}"

    # Avoid overwriting existing output (e.g. duplicate video name)
    output_dir = cfg["output_dir"] / folder_name
    if output_dir.exists():
        for i in range(2, 100):
            candidate = cfg["output_dir"] / f"{folder_name}-{i}"
            if not candidate.exists():
                output_dir = candidate
                folder_name = f"{folder_name}-{i}"
                break
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = folder_name
    video_dest = output_dir / f"{base_name}{video.suffix}"
    transcript_dest = output_dir / f"{base_name}-transcript.txt"
    summary_dest = output_dir / f"{base_name}-summary.md"

    transcript_dest.write_text(transcript, encoding="utf-8")
    print(f"Saved transcript: {transcript_dest}")

    summary_dest.write_text(summary, encoding="utf-8")
    print(f"Saved summary: {summary_dest}")

    # Safe move: copy first, delete after success
    print(f"Moving video to {video_dest}")
    shutil.copy2(str(video), str(video_dest))
    video.unlink()

    return output_dir


def process_video(video_path: str, video_id: int | None = None) -> Path:
    cfg = load_config()
    try:
        cfg.update(load_sidecar(Path(video_path)))
    except SidecarError as e:
        if video_id is not None:
            with state.connection() as conn:
                state.transition_state(
                    conn, video_id, "invalid",
                    extra_event_details={"reason": str(e)},
                )
            notify_swiftbar_refresh()
        notify_event("invalid", video_id=video_id, video_path=Path(video_path))
        raise
    date_str = get_recording_date(video_path)

    print(f"Processing: {video_path}")
    print("=" * 60)

    abs_path = str(Path(video_path).resolve())
    backend = cfg.get("transcribe_backend", "local")

    if video_id is None:
        def _start(conn):
            size_bytes = Path(video_path).stat().st_size if Path(video_path).exists() else None
            duration_sec = get_audio_duration(video_path) if Path(video_path).exists() else None
            vid = state.record_video_seen(
                conn, path=abs_path, detected_at=int(time.time()),
                size_bytes=size_bytes, duration_sec=duration_sec,
            )
            attempt_id = state.start_attempt(conn, vid, backend)
            return vid, attempt_id

        started = _safe_state(_start)
        video_id, attempt_id = (started if started is not None else (None, None))
    else:
        attempt_id = _safe_state(lambda conn: state.start_attempt(conn, video_id, backend))

    stage_reached = "transcribe"
    try:
        result = transcribe(video_path, cfg, video_id=video_id)
        stage_reached = "diarize"
        transcript = build_transcript(result)

        print(f"\nTranscript: {len(result['segments'])} segments")

        tmp_transcript = cfg["output_dir"] / f".tmp-{date_str}-transcript.txt"
        tmp_transcript.parent.mkdir(parents=True, exist_ok=True)
        tmp_transcript.write_text(transcript, encoding="utf-8")

        if video_id is not None:
            _safe_state(state.set_current_stage, video_id, "summary")
            notify_swiftbar_refresh()
        print(f"[4/4] Generating summary via {cfg['summary_backend']}...")
        stage_reached = "summary"
        try:
            summary = generate_summary(transcript, cfg)
        except Exception as e:
            print(f"WARNING: Summary generation failed: {e}")
            summary = (
                "### Короткое название\nmeeting\n\n"
                f"### Summary unavailable\n\nError: {e}\n\n"
                "Transcript was saved successfully."
            )

        output_dir = organize_files(video_path, transcript, summary, date_str, cfg)
        tmp_transcript.unlink(missing_ok=True)

        if attempt_id is not None and video_id is not None:
            def _clear_partial(conn):
                conn.execute(
                    "UPDATE videos SET partial_data=NULL, partial_stage=NULL WHERE id=?",
                    (video_id,),
                )
            _safe_state(_clear_partial)
            _safe_state(state.complete_attempt, attempt_id, video_id, str(output_dir))
            notify_swiftbar_refresh()

        print("=" * 60)
        print(f"Done! Output: {output_dir}")
        return output_dir
    except CancelledError:
        print("Pipeline cancelled by user")
        if attempt_id is not None and video_id is not None:
            def _cancel_attempt(conn):
                conn.execute(
                    "UPDATE attempts SET completed_at=strftime('%s','now'), exit_code=130, "
                    "stage_reached=?, error_message='cancelled by user' WHERE id=?",
                    (stage_reached, attempt_id),
                )
            _safe_state(_cancel_attempt)
            notify_swiftbar_refresh()
        raise
    except Exception as e:
        # Rate limit special-case: video stays queued, backend paused, worker auto-resumes.
        from src.openai_transcribe import RateLimitedError as _RLE
        if isinstance(e, _RLE):
            until_ts = int(time.time()) + e.retry_after_seconds
            print(f"Rate-limited on {e.backend} until {datetime.fromtimestamp(until_ts).strftime('%H:%M')}")
            if video_id is not None:
                def _record_rate_limit(conn):
                    state.set_rate_limit(conn, e.backend, until_ts, e.reason)
                    state.set_video_next_attempt(conn, video_id, until_ts)
                    state.transition_state(conn, video_id, "queued",
                                           extra_event_details={"reason": "rate_limited",
                                                                "backend": e.backend,
                                                                "until_ts": until_ts})
                    if attempt_id is not None:
                        conn.execute(
                            "UPDATE attempts SET completed_at=strftime('%s','now'), exit_code=2, "
                            "stage_reached=?, error_message=? WHERE id=?",
                            (stage_reached, f"rate_limited:{e.backend}", attempt_id),
                        )
                _safe_state(_record_rate_limit)
                notify_swiftbar_refresh()
            notify_event(
                "rate_limited",
                video_id=video_id,
                backend=e.backend,
                retry_after=e.retry_after_seconds,
            )
            raise
        # Generic exception: mark failed
        if attempt_id is not None and video_id is not None:
            _safe_state(state.fail_attempt, attempt_id, video_id, str(e), stage_reached)
            notify_swiftbar_refresh()
        raise


def main():
    parser = argparse.ArgumentParser(description="Process meeting video")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--video-id", type=int, default=None,
                        help="Existing state.db video id (worker mode)")
    args = parser.parse_args()

    if not Path(args.video).exists():
        print(f"Error: file not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    process_video(args.video, video_id=args.video_id)


if __name__ == "__main__":
    main()
