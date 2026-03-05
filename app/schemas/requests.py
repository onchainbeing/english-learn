from pydantic import BaseModel, Field


class ImportYouTubeRequest(BaseModel):
    url: str
    preferred_lang: str = Field(default="en")
    transcript_mode: str = Field(default="strict_whisper")


class StartSessionRequest(BaseModel):
    episode_id: int


class NextSentenceRequest(BaseModel):
    sentence_idx: int
    score_total: float


class VocabReviewRequest(BaseModel):
    vocab_item_id: int
    quality: int = Field(ge=0, le=5)
