# Meeting Pipeline

Automated meeting video processing: transcription with speaker diarization, timestamped transcript, and AI-powered summary with action items. Runs in background on macOS, survives reboots.

## How it works

1. OBS records a meeting to `~/Videos/OBS`
2. launchd detects the new file and triggers processing
3. WhisperX transcribes with word-level timestamps and speaker diarization
4. Claude CLI generates a structured summary with action items
5. Results organized in `~/docs/video/{date}-{topic}/`:

```
docs/video/2026-04-01-sprint-review/
├── 2026-04-01-sprint-review.mp4              # renamed video
├── 2026-04-01-sprint-review-transcript.txt    # full transcript
└── 2026-04-01-sprint-review-summary.md        # summary + action items
```

## Monitoring

- **Menu bar icon** (SwiftBar) - shows processing status, elapsed time, stats
- **macOS notifications** - alerts on start, completion (with duration), and errors
- **Health check** - `./scripts/install.sh health`

## Requirements

- macOS (Apple Silicon recommended)
- Python 3.10+
- ffmpeg
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (uses your subscription)
- [SwiftBar](https://github.com/swiftbar/SwiftBar) (optional, for menu bar)

## Installation

```bash
# Dependencies
brew install python@3.12 ffmpeg terminal-notifier
brew install --cask swiftbar  # optional, for menu bar icon

# Project
cd ~/projects/meeting-pipeline
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -e .

# Configuration
cp .env.example .env
# Fill in HF_TOKEN from huggingface.co/settings/tokens
# Accept model licenses:
#   huggingface.co/pyannote/speaker-diarization-community-1
#   huggingface.co/pyannote/segmentation-3.0

# Install service + menu bar plugin
./scripts/install.sh install
```

## Usage

**Automatic:** Just record with OBS to `~/Videos/OBS`. Pipeline starts automatically when recording stops.

**Manual:**
```bash
.venv/bin/python -m src.process /path/to/video.mp4
```

**Management:**
```bash
./scripts/install.sh health     # check everything is working
./scripts/install.sh status     # launchd service status
./scripts/install.sh logs       # tail logs
./scripts/install.sh uninstall  # remove service
```

## Configuration (.env)

| Variable | Description | Default |
|---|---|---|
| `HF_TOKEN` | HuggingFace token for pyannote diarization | required |
| `CLAUDE_CLI` | Path to claude CLI | `claude` |
| `WATCH_DIR` | Folder to watch for new recordings | `~/Videos/OBS` |
| `OUTPUT_DIR` | Output folder for processed meetings | `~/docs/video` |
| `WHISPER_MODEL` | Whisper model (tiny/base/small/medium/large-v2/large-v3) | `large-v2` |
| `LANGUAGE` | Language code or empty for auto-detect | auto |
| `MAX_SPEAKERS` | Max speakers for diarization (0 = auto) | `0` |
| `CLAUDE_MODEL` | Claude model for summarization | `claude-sonnet-4-6` |

## Stack

| Component | Tool |
|---|---|
| Folder watch | launchd WatchPaths (native macOS, survives reboots) |
| Transcription | WhisperX (faster-whisper + pyannote.audio) |
| Speaker diarization | pyannote.audio 3.x |
| Summarization | Claude CLI |
| Menu bar | SwiftBar |
| Notifications | terminal-notifier |

## Querying your meetings with AI

All processed meetings are stored in `~/docs/video/` as plain text files. Any AI tool (Claude Code, etc.) can search and read them directly.

**Example queries:**
```
"Find where we discussed API authorization"     → grep across transcripts
"What are my action items from last week?"       → read recent summary.md files
"What was decided on the April 1st meeting?"     → read specific summary
"When did someone mention the deadline for X?"   → grep transcript, get timestamp, find in video
```

**Output structure per meeting:**
```
~/docs/video/2026-04-01-sprint-review/
├── 2026-04-01-sprint-review.mp4              # video
├── 2026-04-01-sprint-review-transcript.txt   # timestamped transcript with speakers
└── 2026-04-01-sprint-review-summary.md       # structured summary + action items
```

Transcripts include timestamps (`[01:30:45] SPEAKER_00: ...`) so you can jump to the exact moment in the video.

## Notes

- MPS (Metal GPU) is not supported by CTranslate2 - runs on CPU with int8 quantization
- Processing speed: ~5-10x realtime on Apple Silicon (1h video = 6-12 min)
- Supports any video format that ffmpeg can decode (mkv, mp4, mov, webm, avi, flv)
- Script waits for OBS to finish recording (lsof check) before processing
- Duplicate processing prevented via lock file + processed log
