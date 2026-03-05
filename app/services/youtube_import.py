from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re

from sqlmodel import Session, select
import yt_dlp

from app.core.config import get_settings
from app.models import Episode, Sentence
from app.services.subtitle_parser import Cue, parse_subtitle_file_basic, parse_subtitle_file_incremental
from app.services.strict_transcript import transcribe_audio_to_sentence_cues

TRANSCRIPT_MODE_YOUTUBE_DEFAULT = "youtube_default"
TRANSCRIPT_MODE_YOUTUBE_INCREMENTAL = "youtube_incremental"
TRANSCRIPT_MODE_STRICT_WHISPER = "strict_whisper"


@dataclass
class ImportResult:
    episode: Episode
    sentence_count: int


def normalize_transcript_mode(mode: str | None, default_mode: str) -> str:
    raw = (mode or default_mode).strip().lower()
    if raw in {"youtube", "subtitle", "subtitles", "youtube_basic", "basic", TRANSCRIPT_MODE_YOUTUBE_DEFAULT}:
        return TRANSCRIPT_MODE_YOUTUBE_DEFAULT
    if raw in {"youtube_incremental", "rolling", "incremental", TRANSCRIPT_MODE_YOUTUBE_INCREMENTAL}:
        return TRANSCRIPT_MODE_YOUTUBE_INCREMENTAL
    if raw in {"strict", "whisper", TRANSCRIPT_MODE_STRICT_WHISPER}:
        return TRANSCRIPT_MODE_STRICT_WHISPER
    raise RuntimeError(
        f"Unsupported transcript_mode='{mode}'. "
        f"Use '{TRANSCRIPT_MODE_YOUTUBE_DEFAULT}', '{TRANSCRIPT_MODE_YOUTUBE_INCREMENTAL}', "
        f"or '{TRANSCRIPT_MODE_STRICT_WHISPER}'."
    )


def _mode_token(mode: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", mode.strip().lower())
    token = token.strip("-")
    return token or "mode"


def _find_subtitle_file(video_id: str, search_dir: Path, mode_token: str | None = None) -> Path | None:
    patterns: list[str]
    if mode_token:
        patterns = [f"{video_id}.{mode_token}*.vtt", f"{video_id}.{mode_token}*.srt"]
    else:
        patterns = [f"{video_id}*.vtt", f"{video_id}*.srt"]

    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(sorted(search_dir.glob(pattern)))
    return candidates[0] if candidates else None


def _find_audio_file(video_id: str, search_dir: Path, mode_token: str | None = None) -> Path | None:
    pattern = f"{video_id}.{mode_token}.*" if mode_token else f"{video_id}.*"
    candidates = [p for p in sorted(search_dir.glob(pattern)) if p.suffix.lower() not in {".vtt", ".srt", ".json"}]
    return candidates[0] if candidates else None


def _persist_sentences(db: Session, episode_id: int, cues: list[Cue]) -> int:
    for idx, cue in enumerate(cues):
        db.add(
            Sentence(
                episode_id=episode_id,
                idx=idx,
                text=cue.text,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
            )
        )
    return len(cues)


def _resolve_subtitle_file(video_id: str, mode_token: str) -> Path | None:
    settings = get_settings()
    subtitle_file = _find_subtitle_file(video_id, settings.media_dir, mode_token=mode_token)
    if not subtitle_file:
        subtitle_file = _find_subtitle_file(video_id, settings.subtitles_dir, mode_token=mode_token)
    if not subtitle_file:
        # Backward-compatible fallback for older imports without mode suffix.
        subtitle_file = _find_subtitle_file(video_id, settings.media_dir)
    if not subtitle_file:
        subtitle_file = _find_subtitle_file(video_id, settings.subtitles_dir)
    if not subtitle_file:
        return None

    destination_sub = settings.subtitles_dir / subtitle_file.name
    if subtitle_file.parent != settings.subtitles_dir:
        shutil.move(str(subtitle_file), destination_sub)
    return destination_sub


def _resolve_sentence_cues(
    transcript_mode: str,
    preferred_lang: str,
    audio_file: Path,
    subtitle_file: Path | None,
) -> list[Cue]:
    if transcript_mode == TRANSCRIPT_MODE_STRICT_WHISPER:
        cues = transcribe_audio_to_sentence_cues(audio_file=audio_file, language=preferred_lang)
        if not cues:
            raise RuntimeError("Strict transcript mode produced no sentence cues.")
        return cues

    if transcript_mode == TRANSCRIPT_MODE_YOUTUBE_INCREMENTAL:
        if not subtitle_file:
            raise RuntimeError("No subtitles found (manual or auto) for youtube_incremental transcript mode.")
        cues = parse_subtitle_file_incremental(subtitle_file)
        if not cues:
            raise RuntimeError("Incremental subtitle parsing returned no valid cues")
        return cues

    if transcript_mode == TRANSCRIPT_MODE_YOUTUBE_DEFAULT:
        if not subtitle_file:
            raise RuntimeError("No subtitles found (manual or auto) for youtube_default transcript mode.")
        cues = parse_subtitle_file_basic(subtitle_file)
        if not cues:
            raise RuntimeError("Basic subtitle parsing returned no valid cues")
        return cues

    raise RuntimeError(f"Unsupported transcript mode: {transcript_mode}")


def import_youtube_episode(
    db: Session,
    url: str,
    preferred_lang: str = "en",
    transcript_mode: str | None = None,
    progress_callback: Callable[[str, str, int], None] | None = None,
) -> ImportResult:
    settings = get_settings()
    resolved_mode = normalize_transcript_mode(transcript_mode, settings.default_transcript_mode)
    mode_token = _mode_token(resolved_mode)

    def emit(stage: str, message: str, progress_pct: int) -> None:
        if progress_callback:
            progress_callback(stage, message, progress_pct)

    last_download_pct = -1

    def on_download_progress(data: dict) -> None:
        nonlocal last_download_pct
        status = str(data.get("status", ""))
        if status == "downloading":
            downloaded = float(data.get("downloaded_bytes") or 0.0)
            total = float(data.get("total_bytes") or data.get("total_bytes_estimate") or 0.0)
            if total > 0:
                ratio = max(0.0, min(1.0, downloaded / total))
                pct = 5 + int(ratio * 25)
                if pct > last_download_pct:
                    last_download_pct = pct
                    emit("downloading", f"Downloading audio/subtitles... {int(ratio * 100)}%", pct)
            else:
                if last_download_pct < 8:
                    last_download_pct = 8
                    emit("downloading", "Downloading audio/subtitles...", 8)
        elif status == "finished":
            if last_download_pct < 35:
                last_download_pct = 35
                emit("processing_media", "Download finished. Processing media files...", 35)

    emit("downloading", "Downloading audio and subtitles from YouTube...", 5)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(settings.media_dir / f"%(id)s.{mode_token}.%(ext)s"),
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [f"{preferred_lang}.*", preferred_lang],
        "subtitlesformat": "vtt/srt/best",
        "noprogress": False,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [on_download_progress],
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    emit("processing_media", "Processing imported audio files...", 35)

    video_id = info.get("id")
    title = info.get("title", video_id)
    if not video_id:
        raise RuntimeError("Unable to parse YouTube video id")

    existing = db.exec(
        select(Episode).where(
            Episode.youtube_video_id == video_id,
            Episode.transcript_mode == resolved_mode,
        )
    ).first()
    if existing:
        sentence_count = db.exec(select(Sentence).where(Sentence.episode_id == existing.id)).all()
        return ImportResult(episode=existing, sentence_count=len(sentence_count))

    audio_file = _find_audio_file(video_id, settings.media_dir, mode_token=mode_token)
    if not audio_file:
        # Backward-compatible fallback for older import filenames without mode suffix.
        audio_file = _find_audio_file(video_id, settings.media_dir)
    if not audio_file:
        raise RuntimeError("Audio file not found after yt-dlp import")
    subtitle_file = _resolve_subtitle_file(video_id, mode_token)

    if resolved_mode == TRANSCRIPT_MODE_STRICT_WHISPER:
        emit("transcribing", "Transcribing full audio with local Whisper...", 55)
        cues = transcribe_audio_to_sentence_cues(
            audio_path=audio_file,
            language=preferred_lang,
            progress_callback=lambda pct, msg: emit("transcribing", msg, pct),
        )
        if not cues:
            raise RuntimeError("Strict transcript mode produced no sentence cues.")
    elif resolved_mode == TRANSCRIPT_MODE_YOUTUBE_INCREMENTAL:
        emit("segmenting", "Building sentence cues with incremental subtitle parser...", 60)
        cues = _resolve_sentence_cues(
            transcript_mode=resolved_mode,
            preferred_lang=preferred_lang,
            audio_file=audio_file,
            subtitle_file=subtitle_file,
        )
    else:
        emit("segmenting", "Building sentence cues with basic subtitle parser...", 60)
        cues = _resolve_sentence_cues(
            transcript_mode=resolved_mode,
            preferred_lang=preferred_lang,
            audio_file=audio_file,
            subtitle_file=subtitle_file,
        )

    emit("saving", "Saving episode and sentence cues...", 88)

    episode = Episode(
        youtube_video_id=video_id,
        transcript_mode=resolved_mode,
        title=title,
        source_url=url,
        audio_path=str(audio_file),
        subtitle_path=str(subtitle_file) if subtitle_file else None,
        language=preferred_lang,
    )
    db.add(episode)
    db.flush()

    sentence_count = _persist_sentences(db, episode.id, cues)
    db.add(episode)
    db.commit()
    db.refresh(episode)
    emit("ready", "Import completed. You can start shadowing now.", 100)

    return ImportResult(episode=episode, sentence_count=sentence_count)
