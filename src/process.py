#!/usr/bin/env python3
"""Process a meeting video: transcribe, diarize, summarize, organize."""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import whisperx
from dotenv import load_dotenv
from whisperx.diarize import DiarizationPipeline

# Use cached models without network check (faster startup, works offline)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

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

MAX_TRANSCRIPT_CHARS = 600_000
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
    }


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


def transcribe(video_path: str, cfg: dict) -> dict:
    duration = get_audio_duration(video_path)
    duration_min = int(duration // 60)

    if duration > MAX_VIDEO_DURATION_SEC:
        raise ValueError(
            f"Video too long: {duration_min}m (max {MAX_VIDEO_DURATION_SEC // 60}m). "
            f"Split the video first."
        )

    est_min = max(1, int(duration / 60 * 0.2))
    print(f"Video duration: {duration_min}m, estimated processing: ~{est_min}m")

    # Set timeout for entire transcription
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(WHISPERX_TIMEOUT_SEC)

    try:
        print(f"[1/4] Loading model: {cfg['whisper_model']}...")
        model = whisperx.load_model(
            cfg["whisper_model"],
            device="cpu",
            compute_type="int8",
            language=cfg["language"],
        )

        print(f"[2/4] Transcribing: {video_path}")
        audio = whisperx.load_audio(video_path)
        result = model.transcribe(audio, batch_size=4, print_progress=True)
        language = result["language"]
        print(f"       Detected language: {language}")

        # Free model memory before alignment
        del model

        print("[3/4] Aligning words...")
        align_model, metadata = whisperx.load_align_model(
            language_code=language, device="cpu"
        )
        result = whisperx.align(
            result["segments"], align_model, metadata, audio, device="cpu",
            print_progress=True,
        )

        # Free alignment model before diarization
        del align_model

        print("[4/4] Diarizing speakers...")
        diarize_pipeline = DiarizationPipeline(
            token=cfg["hf_token"], device="cpu"
        )
        diarize_kwargs = {}
        if cfg["max_speakers"]:
            diarize_kwargs["max_speakers"] = cfg["max_speakers"]
        diarize_segments = diarize_pipeline(audio, **diarize_kwargs)
        result = whisperx.assign_word_speakers(diarize_segments, result)

        # Free audio and diarization pipeline
        del audio, diarize_pipeline

    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    return result


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


def call_claude(prompt: str, cfg: dict, timeout: int = 600) -> str:
    result = subprocess.run(
        [cfg["claude_cli"], "-p", "-", "--model", cfg["claude_model"]],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr}")
    return result.stdout.strip()


def generate_summary(transcript: str, cfg: dict) -> str:
    if len(transcript) <= MAX_TRANSCRIPT_CHARS:
        return call_claude(SUMMARY_PROMPT + transcript, cfg)

    print(f"Transcript too long ({len(transcript)} chars), splitting into chunks...")
    lines = transcript.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        if current_len + len(line) > MAX_TRANSCRIPT_CHARS and current_chunk:
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
        partial = call_claude(chunk_prompt, cfg)
        partial_summaries.append(partial)

    print("  Merging chunk summaries into final...")
    merge_prompt = (
        SUMMARY_PROMPT
        + "ОБЪЕДИНЕННЫЕ САММАРИ ЧАСТЕЙ ВСТРЕЧИ:\n\n"
        + "\n\n---\n\n".join(
            f"=== Часть {i + 1} ===\n{s}" for i, s in enumerate(partial_summaries)
        )
    )
    return call_claude(merge_prompt, cfg)


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


def process_video(video_path: str) -> Path:
    cfg = load_config()
    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"Processing: {video_path}")
    print("=" * 60)

    result = transcribe(video_path, cfg)
    transcript = build_transcript(result)

    print(f"\nTranscript: {len(result['segments'])} segments")

    tmp_transcript = cfg["output_dir"] / f".tmp-{date_str}-transcript.txt"
    tmp_transcript.parent.mkdir(parents=True, exist_ok=True)
    tmp_transcript.write_text(transcript, encoding="utf-8")

    print("Generating summary with Claude...")
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

    print("=" * 60)
    print(f"Done! Output: {output_dir}")
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Process meeting video")
    parser.add_argument("video", help="Path to video file")
    args = parser.parse_args()

    if not Path(args.video).exists():
        print(f"Error: file not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    process_video(args.video)


if __name__ == "__main__":
    main()
