from datetime import date

from pydantic import BaseModel


class ImportJobResponse(BaseModel):
    id: int
    status: str
    stage: str
    progress_pct: int
    stage_message: str | None = None
    ready_to_shadow: bool = False
    episode_id: int | None = None
    error_message: str | None = None


class SentenceResponse(BaseModel):
    id: int
    episode_id: int
    idx: int
    text: str
    start_ms: int
    end_ms: int


class SentencePromptResponse(BaseModel):
    id: int
    episode_id: int
    idx: int
    start_ms: int
    end_ms: int


class AttemptResponse(BaseModel):
    attempt_id: int
    reference_text: str
    user_text: str
    missed_words: list[str]
    extra_words: list[str]
    score_word: float
    score_timing: float
    score_total: float
    tip: str


class NextSentenceResponse(BaseModel):
    next_idx: int | None
    status: str


class VocabDueItem(BaseModel):
    id: int
    word: str
    due_date: date
    streak: int
