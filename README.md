# eng-learn

Local AI English shadowing coach (CLI + Web UI) for YouTube podcasts.

## MVP defaults
- STT: Local Whisper (`faster-whisper`) on your device
- Transcript mode: `strict_whisper` (full-audio transcription + alignment)
- Feedback: Cloud LLM (DeepSeek via OpenAI-compatible API)
- Subtitles: `en` + `auto-en` fallback from `yt-dlp`
- Storage: SQLite + local episode media/subtitles, no long-term mic audio storage

## Quickstart
1. Install dependencies:
   - `uv sync` (or `pip install -e .[dev]`)
2. Create local config:
   - `cp .env.example .env`
   - Edit `.env` with your keys/options.
3. Run API:
   - `uv run uvicorn app.main:app --reload`
4. Run CLI:
   - `uv run coach --help`

## Main commands
- `coach doctor`
- `coach import-youtube <url> --lang en --transcript-mode strict_whisper`
- `coach rebuild-episode <episode_id> --transcript-mode strict_whisper`
- `coach session start <episode_id>`
- `coach vocab due`
- `coach stats --days 7`

## Notes
- Episode audio and subtitles are stored in `data/media` and `data/subtitles`.
- Uploaded speaking audio is transcribed and deleted immediately by default.
- Local Whisper model files are cached under `data/models/whisper`.
- Practice page includes a clickable transcript list; clicking a line plays that exact audio span.
- First local Whisper transcription will download model weights (one-time).
- `.env` is loaded automatically by `pydantic-settings`.
- Set `DISABLE_DOTENV=1` to ignore `.env` and use only process env vars.
- Transcript modes:
  - `strict_whisper`: transcribe full audio with local Whisper (best alignment, slower import).
  - `youtube_incremental`: rolling-caption incremental parser with dedupe + sentence-first merge-short chunking.
  - `youtube_default`: basic subtitle cue parser (legacy baseline).
- Optional cloud STT fallback:
  - `STT_PROVIDER=openai_whisper`
  - `OPENAI_API_KEY=...`
