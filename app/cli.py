from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import typer
from sqlmodel import Session, delete, func, select

from app.core.config import get_settings
from app.db.session import engine, init_db
from app.models import Attempt, Episode, PracticeSession, Sentence, VocabItem, WordError
from app.services.practice import next_sentence_index
from app.services.strict_transcript import transcribe_audio_to_sentence_cues
from app.services.subtitle_parser import parse_subtitle_file
from app.services.vocab import review_vocab_item
from app.services.youtube_import import (
    TRANSCRIPT_MODE_STRICT_WHISPER,
    TRANSCRIPT_MODE_YOUTUBE_DEFAULT,
    import_youtube_episode,
    normalize_transcript_mode,
)

app = typer.Typer(help="Local English shadowing coach")
session_app = typer.Typer(help="Practice session commands")
vocab_app = typer.Typer(help="Vocabulary commands")
app.add_typer(session_app, name="session")
app.add_typer(vocab_app, name="vocab")


def _doctor_check(
    status: str,
    message: str,
    counters: dict[str, int],
) -> None:
    normalized = status.lower()
    if normalized not in {"pass", "warn", "fail"}:
        normalized = "fail"

    counters[normalized] = counters.get(normalized, 0) + 1
    typer.echo(f"[{normalized.upper()}] {message}")


def _is_writable_directory(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    return os.access(path, os.W_OK)


@app.command("import-youtube")
def import_youtube(
    url: str,
    lang: str = "en",
    transcript_mode: str = typer.Option(
        "strict_whisper",
        help=f"Transcript mode: {TRANSCRIPT_MODE_STRICT_WHISPER} or {TRANSCRIPT_MODE_YOUTUBE_DEFAULT}",
    ),
):
    init_db()
    settings = get_settings()
    resolved_mode = normalize_transcript_mode(transcript_mode, settings.default_transcript_mode)
    with Session(engine) as db:
        result = import_youtube_episode(
            db,
            url=url,
            preferred_lang=lang,
            transcript_mode=resolved_mode,
        )
        typer.echo(
            f"Imported episode {result.episode.id}: {result.episode.title} "
            f"(sentences={result.sentence_count}, mode={resolved_mode})"
        )


@app.command("rebuild-episode")
def rebuild_episode(
    episode_id: int,
    transcript_mode: str = typer.Option(
        "strict_whisper",
        help=f"Transcript mode: {TRANSCRIPT_MODE_STRICT_WHISPER} or {TRANSCRIPT_MODE_YOUTUBE_DEFAULT}",
    ),
):
    init_db()
    settings = get_settings()
    resolved_mode = normalize_transcript_mode(transcript_mode, settings.default_transcript_mode)

    with Session(engine) as db:
        episode = db.get(Episode, episode_id)
        if not episode:
            raise typer.BadParameter(f"Episode {episode_id} not found")

        if resolved_mode == TRANSCRIPT_MODE_STRICT_WHISPER:
            audio_path = Path(episode.audio_path)
            if not audio_path.exists():
                raise typer.BadParameter(f"Audio file not found: {audio_path}")
            cues = transcribe_audio_to_sentence_cues(audio_path=audio_path, language=episode.language or "en")
            if not cues:
                raise typer.BadParameter(f"No cues produced by strict mode from audio: {audio_path}")
            source_hint = str(audio_path)
        else:
            if not episode.subtitle_path:
                raise typer.BadParameter(f"Episode {episode_id} has no subtitle path")
            subtitle_path = Path(episode.subtitle_path)
            if not subtitle_path.exists():
                raise typer.BadParameter(f"Subtitle file not found: {subtitle_path}")
            cues = parse_subtitle_file(subtitle_path)
            if not cues:
                raise typer.BadParameter(f"No cues parsed from subtitle: {subtitle_path}")
            source_hint = str(subtitle_path)

        db.exec(delete(Sentence).where(Sentence.episode_id == episode_id))
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
        db.commit()
        typer.echo(
            f"Rebuilt episode {episode_id}: title='{episode.title}', "
            f"sentences={len(cues)}, mode={resolved_mode}, source='{source_hint}'"
        )


@session_app.command("start")
def session_start(episode_id: int):
    init_db()
    with Session(engine) as db:
        episode = db.get(Episode, episode_id)
        if not episode:
            raise typer.BadParameter(f"Episode {episode_id} not found")

        session = PracticeSession(episode_id=episode_id, current_idx=0)
        db.add(session)
        db.commit()
        db.refresh(session)
        typer.echo(f"Session started: id={session.id}, episode={episode.title}")


@session_app.command("status")
def session_status(session_id: int):
    init_db()
    with Session(engine) as db:
        session = db.get(PracticeSession, session_id)
        if not session:
            raise typer.BadParameter(f"Session {session_id} not found")

        sentence = db.exec(
            select(Sentence).where(
                Sentence.episode_id == session.episode_id,
                Sentence.idx == session.current_idx,
            )
        ).first()

        typer.echo(
            json.dumps(
                {
                    "session_id": session.id,
                    "episode_id": session.episode_id,
                    "status": session.status,
                    "current_idx": session.current_idx,
                    "sentence": sentence.text if sentence else None,
                },
                ensure_ascii=True,
                indent=2,
            )
        )


@session_app.command("next")
def session_next(session_id: int, sentence_idx: int, score_total: float):
    init_db()
    with Session(engine) as db:
        session = db.get(PracticeSession, session_id)
        if not session:
            raise typer.BadParameter(f"Session {session_id} not found")

        next_idx, status = next_sentence_index(db, session, sentence_idx=sentence_idx, score_total=score_total)
        db.commit()
        typer.echo(f"next_idx={next_idx} status={status}")


@vocab_app.command("due")
def vocab_due(limit: int = 20):
    init_db()
    with Session(engine) as db:
        rows = db.exec(
            select(VocabItem).where(VocabItem.due_date <= func.current_date()).order_by(VocabItem.word).limit(limit)
        ).all()
        for row in rows:
            typer.echo(f"{row.id}\t{row.word}\tdue={row.due_date}\tstreak={row.streak}")


@vocab_app.command("review")
def vocab_review(vocab_item_id: int, quality: int):
    init_db()
    with Session(engine) as db:
        item = db.get(VocabItem, vocab_item_id)
        if not item:
            raise typer.BadParameter(f"Vocab item {vocab_item_id} not found")

        updated = review_vocab_item(db, item, quality)
        db.commit()
        typer.echo(
            f"Reviewed '{updated.word}': next_due={updated.due_date}, interval={updated.interval_days}, streak={updated.streak}"
        )


@app.command("stats")
def stats(days: int = 7):
    init_db()
    with Session(engine) as db:
        total_attempts = db.exec(select(func.count(Attempt.id))).one()
        avg_score = db.exec(select(func.avg(Attempt.score_total))).one()
        top_missed = db.exec(
            select(WordError.word, func.count(WordError.id).label("n"))
            .where(WordError.kind == "missed")
            .group_by(WordError.word)
            .order_by(func.count(WordError.id).desc())
            .limit(10)
        ).all()

        typer.echo(f"Attempts: {int(total_attempts or 0)}")
        typer.echo(f"Avg score: {float(avg_score or 0):.3f}")
        typer.echo(f"Window days arg (for API parity): {days}")
        typer.echo("Top missed words:")
        for row in top_missed:
            typer.echo(f"- {row.word}: {row.n}")


@app.command("doctor")
def doctor(strict: bool = typer.Option(False, help="Exit non-zero if warnings exist.")):
    """
    Validate local runtime prerequisites and configuration.
    """
    counters = {"pass": 0, "warn": 0, "fail": 0}
    settings = get_settings()

    if sys.version_info >= (3, 11):
        _doctor_check("pass", f"Python version {sys.version.split()[0]}", counters)
    else:
        _doctor_check("fail", "Python 3.11+ is required.", counters)

    try:
        init_db()
        _doctor_check("pass", f"Database initialized at {settings.db_url}", counters)
    except Exception as exc:
        _doctor_check("fail", f"Database init failed: {exc}", counters)

    for dir_path in [settings.data_dir, settings.media_dir, settings.subtitles_dir, settings.models_dir]:
        try:
            writable = _is_writable_directory(dir_path)
            if writable:
                _doctor_check("pass", f"Writable directory: {dir_path}", counters)
            else:
                _doctor_check("fail", f"Directory is not writable: {dir_path}", counters)
        except Exception as exc:
            _doctor_check("fail", f"Directory check failed for {dir_path}: {exc}", counters)

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if ffmpeg_path:
        _doctor_check("pass", f"ffmpeg found: {ffmpeg_path}", counters)
    else:
        _doctor_check("fail", "ffmpeg not found in PATH.", counters)

    if ffprobe_path:
        _doctor_check("pass", f"ffprobe found: {ffprobe_path}", counters)
    else:
        _doctor_check("fail", "ffprobe not found in PATH.", counters)

    try:
        yt_dlp_version = subprocess.run(
            ["yt-dlp", "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        _doctor_check("pass", f"yt-dlp available: {yt_dlp_version}", counters)
    except FileNotFoundError:
        _doctor_check("fail", "yt-dlp binary not found in PATH.", counters)
    except subprocess.CalledProcessError as exc:
        _doctor_check("fail", f"yt-dlp check failed: {exc}", counters)

    provider = settings.stt_provider.strip().lower()
    if provider == "local_whisper":
        _doctor_check("pass", "STT provider: local_whisper", counters)
        try:
            from faster_whisper import WhisperModel  # noqa: F401

            _doctor_check("pass", "faster-whisper import OK", counters)
        except Exception as exc:
            _doctor_check("fail", f"faster-whisper import failed: {exc}", counters)

        cache_root = settings.models_dir / "whisper"
        has_model_cache = cache_root.exists() and any(cache_root.iterdir())
        if has_model_cache:
            _doctor_check("pass", f"Whisper cache found: {cache_root}", counters)
        else:
            _doctor_check(
                "warn",
                f"No Whisper model cache in {cache_root} (first transcription will download model).",
                counters,
            )
    elif provider in {"openai_whisper", "cloud_whisper"}:
        _doctor_check("pass", f"STT provider: {provider}", counters)
        if settings.whisper_api_key:
            _doctor_check("pass", "OPENAI_API_KEY / WHISPER_API_KEY is set", counters)
        else:
            _doctor_check("fail", "STT provider is cloud, but OPENAI_API_KEY/WHISPER_API_KEY is missing", counters)
    else:
        _doctor_check("fail", f"Unsupported STT_PROVIDER: {settings.stt_provider}", counters)

    if settings.llm_api_key:
        _doctor_check("pass", f"LLM config set ({settings.llm_model} @ {settings.llm_base_url})", counters)
    else:
        _doctor_check("warn", "LLM_API_KEY missing (feedback falls back to rule-based tips).", counters)

    try:
        with Session(engine) as db:
            episode_count = db.exec(select(func.count(Episode.id))).one()
            _doctor_check("pass", f"Episodes in DB: {int(episode_count or 0)}", counters)
    except Exception as exc:
        _doctor_check("fail", f"Database query failed: {exc}", counters)

    typer.echo(
        f"Summary: PASS={counters['pass']} WARN={counters['warn']} FAIL={counters['fail']}"
    )

    if counters["fail"] > 0:
        raise typer.Exit(code=1)
    if strict and counters["warn"] > 0:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
