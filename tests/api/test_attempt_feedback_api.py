from __future__ import annotations

from sqlmodel import Session

from app.models import Episode, Sentence


class _FakeSTTService:
    def transcribe(self, _path):
        return "That was just the coolest moment and then I realized that I don't remember TypeScript at all"


def test_attempt_response_includes_score_explanations(client, test_engine, monkeypatch):
    with Session(test_engine) as db:
        episode = Episode(
            youtube_video_id="ghi789",
            transcript_mode="youtube_incremental",
            title="Feedback Episode",
            source_url="https://youtu.be/ghi789",
            audio_path="data/media/ghi789.youtube_incremental.m4a",
            subtitle_path="data/subtitles/ghi789.youtube_incremental.en.vtt",
            language="en",
        )
        db.add(episode)
        db.flush()

        sentence = Sentence(
            episode_id=episode.id,
            idx=0,
            text="That was just the coolest moment. And then I realized I don't remember TypeScript at all.",
            start_ms=0,
            end_ms=3270,
        )
        db.add(sentence)
        db.commit()
        db.refresh(sentence)

        sentence_id = sentence.id

    monkeypatch.setattr("app.api.routes.get_audio_duration_seconds", lambda _path: 6.66)
    monkeypatch.setattr("app.api.routes.STTService", _FakeSTTService)
    monkeypatch.setattr(
        "app.api.routes.FeedbackService.generate_tip",
        lambda self, **_kwargs: "Keep the pace closer to the original sentence.",
    )

    response = client.post(
        "/api/attempts",
        data={"sentence_id": str(sentence_id)},
        files={"audio_file": ("attempt.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "score_word_detail" in payload
    assert "score_timing_detail" in payload
    assert "score_total_detail" in payload
    assert "6.66s" in payload["score_timing_detail"]
    assert "timing pulled the total down" in payload["score_total_detail"]
