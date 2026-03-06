from __future__ import annotations

from app.services.feedback import build_score_explanations


def test_build_score_explanations_explains_high_word_but_low_timing_score():
    explanations = build_score_explanations(
        missed_words=[],
        extra_words=[],
        score_word=0.938,
        score_timing=0.0,
        score_total=0.656,
        target_duration_s=3.27,
        user_duration_s=6.66,
    )

    assert "matched the target words closely" in explanations["score_word_detail"]
    assert "6.66s" in explanations["score_timing_detail"]
    assert "3.27s" in explanations["score_timing_detail"]
    assert "timing pulled the total down" in explanations["score_total_detail"]


def test_build_score_explanations_calls_out_missed_and_extra_words():
    explanations = build_score_explanations(
        missed_words=["don't", "at", "all"],
        extra_words=["now"],
        score_word=0.4,
        score_timing=0.9,
        score_total=0.55,
        target_duration_s=3.0,
        user_duration_s=3.2,
    )

    assert "missed 3 word(s)" in explanations["score_word_detail"]
    assert "added 1 extra word(s)" in explanations["score_word_detail"]
    assert "word accuracy pulled the total down" in explanations["score_total_detail"]
