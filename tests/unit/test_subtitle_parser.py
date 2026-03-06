from __future__ import annotations

from pathlib import Path

from app.services.subtitle_parser import parse_subtitle_file_incremental


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_incremental_parser_keeps_full_sentence_from_rolling_captions():
    cues = parse_subtitle_file_incremental(FIXTURE_DIR / "rolling_caption_sample.vtt")

    texts = [cue.text for cue in cues]

    assert any("girl i was looking at the other geyser." in text.lower() for text in texts)


def test_incremental_parser_flushes_trailing_unpunctuated_tail():
    cues = parse_subtitle_file_incremental(FIXTURE_DIR / "rolling_caption_sample.vtt")

    assert cues[-1].text.endswith("without punctuation tail")
