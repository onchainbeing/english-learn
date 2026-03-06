from __future__ import annotations

from sqlmodel import Session

from app.models import Episode, Sentence


def test_list_episode_sentences_returns_ordered_rows(client, test_engine):
    with Session(test_engine) as db:
        episode = Episode(
            youtube_video_id="abc123",
            transcript_mode="youtube_incremental",
            title="Test Episode",
            source_url="https://youtu.be/abc123",
            audio_path="data/media/abc123.youtube_incremental.m4a",
            subtitle_path="data/subtitles/abc123.youtube_incremental.en.vtt",
            language="en",
        )
        db.add(episode)
        db.flush()

        db.add(
            Sentence(
                episode_id=episode.id,
                idx=1,
                text="second",
                start_ms=2000,
                end_ms=3000,
            )
        )
        db.add(
            Sentence(
                episode_id=episode.id,
                idx=0,
                text="first",
                start_ms=0,
                end_ms=1000,
            )
        )
        db.commit()

        episode_id = episode.id

    response = client.get(f"/api/episodes/{episode_id}/sentences")

    assert response.status_code == 200
    payload = response.json()
    assert [row["idx"] for row in payload] == [0, 1]
    assert [row["text"] for row in payload] == ["first", "second"]


def test_practice_page_shows_transcript_mode_label(client, test_engine):
    with Session(test_engine) as db:
        episode = Episode(
            youtube_video_id="def456",
            transcript_mode="strict_whisper",
            title="Practice Episode",
            source_url="https://youtu.be/def456",
            audio_path="data/media/def456.strict_whisper.m4a",
            subtitle_path=None,
            language="en",
        )
        db.add(episode)
        db.commit()
        db.refresh(episode)

        episode_id = episode.id

    response = client.get(f"/practice/{episode_id}")

    assert response.status_code == 200
    assert "Practice Episode [strict_whisper]" in response.text
