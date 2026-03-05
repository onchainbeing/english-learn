from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Episode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    youtube_video_id: str = Field(index=True)
    title: str
    source_url: str
    audio_path: str
    subtitle_path: str | None = None
    language: str = "en"
    created_at: datetime = Field(default_factory=utc_now)


class Sentence(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key="episode.id", index=True)
    idx: int = Field(index=True)
    text: str
    start_ms: int = 0
    end_ms: int = 0
    created_at: datetime = Field(default_factory=utc_now)


class ImportJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    preferred_lang: str = "en"
    status: str = Field(default="pending", index=True)
    stage: str = Field(default="queued", index=True)
    progress_pct: int = 0
    stage_message: str | None = None
    episode_id: int | None = Field(default=None, index=True)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PracticeSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key="episode.id", index=True)
    current_idx: int = 0
    status: str = Field(default="active", index=True)
    revisit_queue_json: str = "[]"
    retry_counts_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Attempt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int | None = Field(default=None, foreign_key="practicesession.id", index=True)
    sentence_id: int = Field(foreign_key="sentence.id", index=True)
    reference_text: str
    user_text: str
    wer: float
    score_word: float
    score_timing: float
    score_total: float
    user_duration_s: float | None = None
    created_at: datetime = Field(default_factory=utc_now)


class WordError(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    attempt_id: int = Field(foreign_key="attempt.id", index=True)
    word: str = Field(index=True)
    kind: str = Field(index=True)
    count: int = 1


class VocabItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    word: str = Field(index=True)
    meaning: str | None = None
    source_sentence_id: int | None = Field(default=None, foreign_key="sentence.id", index=True)
    interval_days: int = 1
    ease_factor: float = 2.5
    streak: int = 0
    due_date: date = Field(default_factory=date.today, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class VocabReview(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    vocab_item_id: int = Field(foreign_key="vocabitem.id", index=True)
    quality: int
    next_due_date: date
    reviewed_at: datetime = Field(default_factory=utc_now)
