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
- [HuggingFace](https://huggingface.co/settings/tokens) account (free, for speaker diarization model)

## Installation

```bash
# Dependencies
brew install python@3.12 ffmpeg terminal-notifier
brew install --cask swiftbar  # optional, for menu bar status

# Project
git clone https://github.com/mshykhov/meetscribe.git && cd meetscribe
python3.12 -m venv .venv
.venv/bin/pip install -e .

# Configuration
cp .env.example .env
# Edit .env: set HF_TOKEN, adjust WATCH_DIR/OUTPUT_DIR if needed

# HuggingFace setup (required for speaker diarization):
# 1. Create token: https://huggingface.co/settings/tokens
# 2. Accept license: https://huggingface.co/pyannote/speaker-diarization-community-1
# 3. Accept license: https://huggingface.co/pyannote/segmentation-3.0

# Install service (survives reboots)
./scripts/install.sh install
```

## Usage

**Automatic:** drop any video into your watch folder (default `~/Videos/OBS`). Processing starts automatically. You'll see a menu bar indicator and get macOS notifications.

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

## Monitoring

- **Menu bar** (SwiftBar) - shows current file, processing step (1/4 Transcribing, 2/4 Aligning, etc.), elapsed time
- **macOS notifications** - alerts on detection, start with ETA, completion with duration, errors
- **Health check** - `./scripts/install.sh health` verifies all components

## Configuration

All settings in `.env` (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `HF_TOKEN` | HuggingFace token for speaker diarization | required |
| `WATCH_DIR` | Folder to monitor for new recordings | `~/Videos/OBS` |
| `OUTPUT_DIR` | Where processed meetings go | `~/docs/video` |
| `WHISPER_MODEL` | Model size (see table below) | `medium` |
| `LANGUAGE` | Language code or empty for auto-detect | auto |
| `CLAUDE_MODEL` | Model for summary generation | `claude-sonnet-4-6` |
| `CLAUDE_CLI` | Path to claude CLI | `claude` |

### Model speed vs quality

| Model | 2min video | 1h video | Quality | Recommendation |
|---|---|---|---|---|
| `tiny` | ~20s | ~3-5m | Basic | Testing only |
| `small` | ~1m | ~8-10m | Good | Fast processing |
| `medium` | ~2-3m | ~15-20m | Great | **Recommended** |
| `large-v2` | ~10m | ~60m | Best | When quality matters most |

## Stack

- **WhisperX** - transcription + word-level timestamps + speaker diarization
- **Claude CLI** - AI summary generation (uses your subscription)
- **launchd** WatchPaths - native macOS background service, survives reboots
- **SwiftBar** - menu bar processing indicator with real-time status
- **terminal-notifier** - macOS notifications with custom icon

## Reliability

- Atomic lock prevents parallel processing (one video at a time)
- Failed files retry up to 3 times, then skip
- Safe video move: copy + verify + delete (no data loss on crash)
- Transcript saved before summary (if Claude fails, transcript is preserved)
- Survives reboots (`RunAtLoad` in launchd)
- Orphaned temp files auto-cleaned
- Process logs rotated (keeps last 20)
- Max video length: 4 hours

## Notes

- Runs on CPU with int8 quantization (Metal GPU not supported by CTranslate2)
- All models cached locally after first download - works offline (except Claude summary)
- Supports any format ffmpeg can decode (mp4, mkv, mov, webm, avi, flv)
- Videos are moved from watch folder to output after processing
