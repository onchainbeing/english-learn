from __future__ import annotations

import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, func, select

from app.core.config import get_settings
from app.db.session import engine, get_session
from app.models import Attempt, Episode, ImportJob, PracticeSession, Sentence, VocabItem, WordError
from app.schemas.requests import (
    ImportYouTubeRequest,
    NextSentenceRequest,
    StartSessionRequest,
    VocabReviewRequest,
)
from app.schemas.responses import (
    AttemptResponse,
    ImportJobResponse,
    NextSentenceResponse,
    SentencePromptResponse,
    SentenceResponse,
)
from app.services.audio_utils import get_audio_duration_seconds
from app.services.feedback import FeedbackService
from app.services.practice import next_sentence_index
from app.services.scoring import compute_score
from app.services.stt import STTService
from app.services.vocab import add_missed_words, review_vocab_item
from app.services.youtube_import import import_youtube_episode

router = APIRouter(prefix="/api")
settings = get_settings()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _set_import_job_progress(
    job_id: int,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress_pct: int | None = None,
    stage_message: str | None = None,
    episode_id: int | None = None,
    error_message: str | None = None,
) -> None:
    with Session(engine) as db:
        job = db.get(ImportJob, job_id)
        if not job:
            return
        if status is not None:
            job.status = status
        if stage is not None:
            job.stage = stage
        if progress_pct is not None:
            job.progress_pct = max(0, min(100, progress_pct))
        if stage_message is not None:
            job.stage_message = stage_message
        if episode_id is not None:
            job.episode_id = episode_id
        if error_message is not None:
            job.error_message = error_message
        job.updated_at = _utc_now()
        db.add(job)
        db.commit()


def _run_import_job(job_id: int, url: str, preferred_lang: str, transcript_mode: str) -> None:
    _set_import_job_progress(
        job_id,
        status="running",
        stage="starting",
        progress_pct=1,
        stage_message="Import started.",
        error_message=None,
    )

    with Session(engine) as db:
        try:
            result = import_youtube_episode(
                db,
                url=url,
                preferred_lang=preferred_lang,
                transcript_mode=transcript_mode,
                progress_callback=lambda stage, message, pct: _set_import_job_progress(
                    job_id,
                    status="running",
                    stage=stage,
                    progress_pct=pct,
                    stage_message=message,
                ),
            )
            _set_import_job_progress(
                job_id,
                status="completed",
                stage="ready",
                progress_pct=100,
                stage_message="Import completed. You can start shadowing now.",
                episode_id=result.episode.id,
                error_message=None,
            )
        except Exception as exc:
            _set_import_job_progress(
                job_id,
                status="failed",
                stage="failed",
                progress_pct=100,
                stage_message="Import failed.",
                error_message=str(exc),
            )


@router.post("/youtube/import", response_model=ImportJobResponse)
def import_youtube(
    payload: ImportYouTubeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
):
    job = ImportJob(
        url=payload.url,
        preferred_lang=payload.preferred_lang,
        status="pending",
        stage="queued",
        progress_pct=0,
        stage_message="Queued. Waiting to start import...",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(
        _run_import_job,
        job.id,
        payload.url,
        payload.preferred_lang,
        payload.transcript_mode,
    )
    return ImportJobResponse(
        id=job.id,
        status=job.status,
        stage=job.stage,
        progress_pct=job.progress_pct,
        stage_message=job.stage_message,
        ready_to_shadow=False,
        episode_id=job.episode_id,
    )


@router.get("/import-jobs/{job_id}", response_model=ImportJobResponse)
def get_import_job(job_id: int, db: Session = Depends(get_session)):
    job = db.get(ImportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    return ImportJobResponse(
        id=job.id,
        status=job.status,
        stage=job.stage,
        progress_pct=job.progress_pct,
        stage_message=job.stage_message,
        ready_to_shadow=(job.status == "completed" and job.episode_id is not None),
        episode_id=job.episode_id,
        error_message=job.error_message,
    )


@router.get("/episodes")
def list_episodes(db: Session = Depends(get_session)):
    rows = db.exec(select(Episode).order_by(Episode.created_at.desc())).all()
    return rows


@router.get("/episodes/{episode_id}/sentences/{idx}", response_model=SentenceResponse)
def get_sentence(episode_id: int, idx: int, db: Session = Depends(get_session)):
    sentence = db.exec(
        select(Sentence).where(Sentence.episode_id == episode_id, Sentence.idx == idx)
    ).first()
    if not sentence:
        raise HTTPException(status_code=404, detail="Sentence not found")

    return SentenceResponse(
        id=sentence.id,
        episode_id=sentence.episode_id,
        idx=sentence.idx,
        text=sentence.text,
        start_ms=sentence.start_ms,
        end_ms=sentence.end_ms,
    )


@router.get("/episodes/{episode_id}/sentences/{idx}/prompt", response_model=SentencePromptResponse)
def get_sentence_prompt(episode_id: int, idx: int, db: Session = Depends(get_session)):
    sentence = db.exec(
        select(Sentence).where(Sentence.episode_id == episode_id, Sentence.idx == idx)
    ).first()
    if not sentence:
        raise HTTPException(status_code=404, detail="Sentence not found")

    return SentencePromptResponse(
        id=sentence.id,
        episode_id=sentence.episode_id,
        idx=sentence.idx,
        start_ms=sentence.start_ms,
        end_ms=sentence.end_ms,
    )


@router.post("/sessions/start")
def start_session(payload: StartSessionRequest, db: Session = Depends(get_session)):
    episode = db.get(Episode, payload.episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    practice_session = PracticeSession(episode_id=episode.id, current_idx=0)
    db.add(practice_session)
    db.commit()
    db.refresh(practice_session)
    return {"session_id": practice_session.id, "episode_id": episode.id, "current_idx": 0}


@router.post("/sessions/{session_id}/next", response_model=NextSentenceResponse)
def next_sentence(
    session_id: int,
    payload: NextSentenceRequest,
    db: Session = Depends(get_session),
):
    practice_session = db.get(PracticeSession, session_id)
    if not practice_session:
        raise HTTPException(status_code=404, detail="Practice session not found")

    next_idx, status = next_sentence_index(
        db=db,
        practice_session=practice_session,
        sentence_idx=payload.sentence_idx,
        score_total=payload.score_total,
    )
    db.commit()

    return NextSentenceResponse(next_idx=next_idx, status=status)


@router.post("/attempts", response_model=AttemptResponse)
async def create_attempt(
    sentence_id: int = Form(...),
    session_id: int | None = Form(default=None),
    audio_file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    sentence = db.get(Sentence, sentence_id)
    if not sentence:
        raise HTTPException(status_code=404, detail="Sentence not found")

    suffix = Path(audio_file.filename or "recording.webm").suffix or ".webm"
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=settings.data_dir) as tmp:
            content = await audio_file.read()
            tmp.write(content)
            temp_path = Path(tmp.name)

        user_duration_s = get_audio_duration_seconds(temp_path)
        target_duration_s = None
        if sentence.end_ms > sentence.start_ms:
            target_duration_s = (sentence.end_ms - sentence.start_ms) / 1000.0

        stt = STTService()
        transcript = stt.transcribe(temp_path)

        score = compute_score(
            reference=sentence.text,
            hypothesis=transcript,
            target_duration_s=target_duration_s,
            user_duration_s=user_duration_s,
        )

        attempt = Attempt(
            session_id=session_id,
            sentence_id=sentence.id,
            reference_text=sentence.text,
            user_text=transcript,
            wer=score.wer_value,
            score_word=score.score_word,
            score_timing=score.score_timing,
            score_total=score.score_total,
            user_duration_s=user_duration_s,
        )
        db.add(attempt)
        db.flush()

        for word in score.missed_words:
            db.add(WordError(attempt_id=attempt.id, word=word.lower(), kind="missed"))
        for word in score.extra_words:
            db.add(WordError(attempt_id=attempt.id, word=word.lower(), kind="extra"))

        add_missed_words(db, score.missed_words, source_sentence_id=sentence.id)

        tip = FeedbackService().generate_tip(
            reference=sentence.text,
            user_text=transcript,
            missed_words=score.missed_words,
            extra_words=score.extra_words,
            score_total=score.score_total,
        )

        db.commit()
        db.refresh(attempt)

        return AttemptResponse(
            attempt_id=attempt.id,
            reference_text=attempt.reference_text,
            user_text=attempt.user_text,
            missed_words=score.missed_words,
            extra_words=score.extra_words,
            score_word=attempt.score_word,
            score_timing=attempt.score_timing,
            score_total=attempt.score_total,
            tip=tip,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if temp_path and temp_path.exists() and not settings.store_attempt_audio:
            temp_path.unlink(missing_ok=True)
        elif temp_path and temp_path.exists() and settings.store_attempt_audio:
            archive = settings.data_dir / "attempt_audio"
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_path), archive / temp_path.name)


@router.get("/vocab/due")
def vocab_due(limit: int = 20, db: Session = Depends(get_session)):
    today = date.today()
    rows = db.exec(
        select(VocabItem)
        .where(VocabItem.due_date <= today)
        .order_by(VocabItem.due_date.asc(), VocabItem.word.asc())
        .limit(limit)
    ).all()
    return rows


@router.post("/vocab/review")
def vocab_review(payload: VocabReviewRequest, db: Session = Depends(get_session)):
    item = db.get(VocabItem, payload.vocab_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Vocab item not found")

    updated = review_vocab_item(db, item, payload.quality)
    db.commit()
    db.refresh(updated)

    return {
        "id": updated.id,
        "word": updated.word,
        "streak": updated.streak,
        "interval_days": updated.interval_days,
        "due_date": updated.due_date,
    }


@router.get("/stats/summary")
def stats_summary(days: int = 7, db: Session = Depends(get_session)):
    since = _utc_now() - timedelta(days=days)

    total_attempts = db.exec(select(func.count(Attempt.id)).where(Attempt.created_at >= since)).one()
    avg_score = db.exec(select(func.avg(Attempt.score_total)).where(Attempt.created_at >= since)).one()

    top_missed = db.exec(
        select(WordError.word, func.count(WordError.id).label("n"))
        .join(Attempt, Attempt.id == WordError.attempt_id)
        .where(Attempt.created_at >= since, WordError.kind == "missed")
        .group_by(WordError.word)
        .order_by(func.count(WordError.id).desc())
        .limit(10)
    ).all()

    due_vocab = db.exec(select(func.count(VocabItem.id)).where(VocabItem.due_date <= date.today())).one()

    return {
        "days": days,
        "attempts": int(total_attempts or 0),
        "average_score": float(avg_score or 0),
        "due_vocab": int(due_vocab or 0),
        "top_missed_words": [{"word": row.word, "count": row.n} for row in top_missed],
    }
