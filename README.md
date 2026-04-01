# Meetscribe

Automated meeting video processing on macOS. Records go in, transcripts and summaries come out.

**What it does:** watches a folder for new video files, transcribes with speaker diarization (who said what), generates an AI summary with action items, and organizes everything into clean folders.

## Output

Each processed meeting produces:

```
{output_dir}/{date}-{topic}/
├── {date}-{topic}.mp4                # renamed video
├── {date}-{topic}-transcript.txt     # [00:15] SPEAKER_00: text...
└── {date}-{topic}-summary.md         # structured summary + action items
```

Transcripts include timestamps and speaker labels. Summaries include meeting topic, key decisions, action items, and a content overview. All plain text - searchable by any tool or AI.

## Requirements

- macOS (Apple Silicon recommended)
- Python 3.10+
- ffmpeg
- [Claude Code](https://claude.ai/code) CLI (requires subscription)
- terminal-notifier (for macOS notifications)
- [SwiftBar](https://github.com/swiftbar/SwiftBar) (optional, menu bar status)

## Installation

```bash
brew install python@3.12 ffmpeg terminal-notifier
brew install --cask swiftbar  # optional

git clone <repo-url> && cd meetscribe
python3.12 -m venv .venv
.venv/bin/pip install -e .

cp .env.example .env
# Edit .env: set HF_TOKEN, adjust paths if needed
# Accept HuggingFace model licenses (see .env.example for URLs)

./scripts/install.sh install
```

## Usage

**Automatic:** record with OBS (or any app) to your watch folder. Processing starts when recording stops.

**Manual:**
```bash
.venv/bin/python -m src.process /path/to/video.mp4
```

**Management:**
```bash
./scripts/install.sh health      # verify everything works
./scripts/install.sh logs        # tail logs
./scripts/install.sh retry       # reset failed files for retry
./scripts/install.sh reprocess /path/to/video.mp4  # reprocess specific file
./scripts/install.sh uninstall   # remove service
```

## Configuration

All settings in `.env` (see `.env.example`). Key options:

- `HF_TOKEN` - HuggingFace token for speaker diarization (required for identifying who speaks)
- `WATCH_DIR` - folder to monitor for new recordings
- `OUTPUT_DIR` - where processed meetings go
- `WHISPER_MODEL` - model size (tiny/base/small/medium/large-v2/large-v3)
- `LANGUAGE` - language code or empty for auto-detect
- `CLAUDE_MODEL` - model for summary generation

## Stack

- **launchd** WatchPaths - native macOS, survives reboots
- **WhisperX** - transcription + word-level timestamps + speaker diarization
- **Claude CLI** - AI summary generation (uses your subscription)
- **SwiftBar** - menu bar processing indicator
- **terminal-notifier** - macOS notifications

## Notes

- Runs on CPU with int8 quantization (Metal GPU not supported by CTranslate2)
- 1h video processes in ~6-12 min on Apple Silicon
- Max video length: 4 hours
- Failed files retry up to 3 times, then skip
- Supports any format ffmpeg can decode
