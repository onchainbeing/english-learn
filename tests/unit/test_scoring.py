from __future__ import annotations

from app.services.scoring import compute_score


def test_compute_score_rewards_exact_match():
    result = compute_score(
        reference="That was the coolest moment.",
        hypothesis="That was the coolest moment.",
        target_duration_s=3.0,
        user_duration_s=3.0,
    )

    assert result.score_word == 1.0
    assert result.score_timing == 1.0
    assert result.score_total == 1.0
    assert result.missed_words == []
    assert result.extra_words == []


def test_compute_score_penalizes_large_timing_mismatch():
    result = compute_score(
        reference="That was just the coolest moment.",
        hypothesis="That was just the coolest moment.",
        target_duration_s=3.27,
        user_duration_s=6.66,
    )

    assert result.score_word == 1.0
    assert result.score_timing == 0.0
    assert result.score_total == 0.7


def test_compute_score_reports_missed_and_extra_words():
    result = compute_score(
        reference="I don't remember TypeScript at all",
        hypothesis="I remember TypeScript now",
    )

    assert "don't" in result.missed_words
    assert "at" in result.missed_words
    assert "all" in result.missed_words
    assert "now" in result.extra_words
