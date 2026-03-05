from __future__ import annotations

from pathlib import Path
import re

from app.core.config import get_settings
from app.services.stt import _get_local_whisper_model
from app.services.subtitle_parser import Cue, clean_text, finalize_practice_cues

# Sentence boundary heuristic:
# split only when punctuation likely ends a sentence, or at end-of-segment.
SENTENCE_RE = re.compile(r".+?(?:[.!?]+(?=\s+(?:[\"'(\[]?[A-Z0-9])|$)|$)")
WORD_RE = re.compile(r"[A-Za-z0-9']+")
ABBREV_END_RE = re.compile(r"\b[A-Z]\.$")
CONNECTOR_STARTS = {
    "and",
    "or",
    "but",
    "so",
    "because",
    "to",
    "for",
    "of",
    "in",
    "on",
    "at",
    "with",
    "without",
    "from",
}
MAX_FRAGMENT_MERGE_GAP_MS = 4000
MAX_FRAGMENT_MERGE_WORDS = 26


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def _starts_with_connector(text: str) -> bool:
    words = WORD_RE.findall(text.lower())
    return bool(words) and words[0] in CONNECTOR_STARTS


def _is_fragment_like(text: str) -> bool:
    words = _word_count(text)
    if words == 0:
        return True
    if ABBREV_END_RE.search(text):
        return True
    if words <= 6 and _starts_with_connector(text):
        return True
    if words <= 5 and text[:1].islower():
        return True
    return False


def _merge_cues(left: Cue, right: Cue) -> Cue:
    return Cue(
        start_ms=min(left.start_ms, right.start_ms),
        end_ms=max(left.end_ms, right.end_ms),
        text=f"{left.text} {right.text}".strip(),
    )


def _can_merge_adjacent(left: Cue, right: Cue) -> bool:
    gap_ms = max(0, right.start_ms - left.end_ms)
    if gap_ms > MAX_FRAGMENT_MERGE_GAP_MS:
        return False
    return (_word_count(left.text) + _word_count(right.text)) <= MAX_FRAGMENT_MERGE_WORDS


def _sweep_fragment_cues(cues: list[Cue]) -> list[Cue]:
    if not cues:
        return []

    swept: list[Cue] = []
    i = 0
    while i < len(cues):
        current = cues[i]
        if _is_fragment_like(current.text):
            if i + 1 < len(cues):
                nxt = cues[i + 1]
                if _can_merge_adjacent(current, nxt):
                    swept.append(_merge_cues(current, nxt))
                    i += 2
                    continue
            if swept and _can_merge_adjacent(swept[-1], current):
                swept[-1] = _merge_cues(swept[-1], current)
                i += 1
                continue

        swept.append(current)
        i += 1

    return swept


def _split_segment_to_sentences(start_ms: int, end_ms: int, text: str) -> list[Cue]:
    matches = list(SENTENCE_RE.finditer(text))
    if not matches:
        if len(WORD_RE.findall(text)) < 1:
            return []
        return [Cue(start_ms=start_ms, end_ms=end_ms, text=text)]

    duration_ms = max(1, end_ms - start_ms)
    text_len = max(1, len(text))
    cues: list[Cue] = []

    for match in matches:
        sentence = clean_text(match.group())
        if len(WORD_RE.findall(sentence)) < 1:
            continue
        sent_start = start_ms + int(duration_ms * (match.start() / text_len))
        sent_end = start_ms + int(duration_ms * (match.end() / text_len))
        if sent_end <= sent_start:
            sent_end = sent_start + 250
        cues.append(Cue(start_ms=sent_start, end_ms=sent_end, text=sentence))

    return cues


def transcribe_audio_to_sentence_cues(audio_path: Path, language: str = "en") -> list[Cue]:
    settings = get_settings()
    model = _get_local_whisper_model(
        model_size=settings.local_whisper_model,
        device=settings.local_whisper_device,
        compute_type=settings.local_whisper_compute_type,
        model_root=settings.models_dir / "whisper",
    )

    segments, _ = model.transcribe(
        str(audio_path),
        beam_size=settings.local_whisper_beam_size,
        language=language or settings.local_whisper_language,
        vad_filter=True,
    )

    cues: list[Cue] = []
    for seg in segments:
        text = clean_text(seg.text or "")
        if not text:
            continue
        start_ms = int(float(seg.start) * 1000)
        end_ms = int(float(seg.end) * 1000)
        cues.extend(_split_segment_to_sentences(start_ms, end_ms, text))

    return finalize_practice_cues(_sweep_fragment_cues(cues))
