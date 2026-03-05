from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from jiwer import wer

WORD_RE = re.compile(r"[a-zA-Z']+")


@dataclass
class ScoreResult:
    score_word: float
    score_timing: float
    score_total: float
    wer_value: float
    missed_words: list[str]
    extra_words: list[str]


def normalize_text(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def token_diff(reference: str, hypothesis: str) -> tuple[list[str], list[str]]:
    ref_tokens = normalize_text(reference).split()
    hyp_tokens = normalize_text(hypothesis).split()
    matcher = SequenceMatcher(a=ref_tokens, b=hyp_tokens)

    missed: list[str] = []
    extra: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"delete", "replace"}:
            missed.extend(ref_tokens[i1:i2])
        if tag in {"insert", "replace"}:
            extra.extend(hyp_tokens[j1:j2])

    return missed, extra


def compute_score(
    reference: str,
    hypothesis: str,
    target_duration_s: float | None = None,
    user_duration_s: float | None = None,
) -> ScoreResult:
    norm_ref = normalize_text(reference)
    norm_hyp = normalize_text(hypothesis)

    wer_value = wer(norm_ref, norm_hyp) if norm_ref else 1.0
    score_word = max(0.0, min(1.0, 1.0 - wer_value))

    score_timing = 1.0
    if target_duration_s and user_duration_s and target_duration_s > 0:
        diff_ratio = abs(user_duration_s - target_duration_s) / target_duration_s
        score_timing = max(0.0, 1.0 - min(diff_ratio, 1.0))

    score_total = 0.7 * score_word + 0.3 * score_timing
    missed_words, extra_words = token_diff(reference, hypothesis)

    return ScoreResult(
        score_word=score_word,
        score_timing=score_timing,
        score_total=score_total,
        wer_value=wer_value,
        missed_words=missed_words,
        extra_words=extra_words,
    )
