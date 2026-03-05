from __future__ import annotations

from html import unescape
import re
from dataclasses import dataclass
from pathlib import Path

TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[\.,]\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}[\.,]\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+")
CLAUSE_RE = re.compile(r"[^,;:]+[,;:]?")
MIN_CUE_MS = 120
MAX_SENTENCE_WORDS = 20
MAX_SENTENCE_DURATION_MS = 9000
MIN_PRACTICE_WORDS = 3
MIN_PRACTICE_DURATION_MS = 500


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str


def ts_to_ms(timestamp: str) -> int:
    hh, mm, rest = timestamp.split(":")
    ss, frac = rest.replace(",", ".").split(".")
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(frac)


def clean_text(raw: str) -> str:
    text = unescape(raw)
    text = TAG_RE.sub("", text)
    text = text.replace(">>", " ")
    text = text.replace("♪", " ")
    text = text.replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip("- ")
    return text


def _norm_for_compare(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def _norm_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _raw_slice_after_norm_words(raw_text: str, norm_word_count: int) -> str:
    if norm_word_count <= 0:
        return raw_text.strip()

    words = raw_text.split()
    seen = 0
    cut_idx = len(words)
    for idx, word in enumerate(words):
        if re.search(r"[a-z0-9']+", word.lower()):
            seen += 1
        if seen >= norm_word_count:
            cut_idx = idx + 1
            break

    return " ".join(words[cut_idx:]).strip()


def _extract_increment(prev_text: str, current_text: str) -> str:
    if not current_text:
        return ""
    if not prev_text:
        return current_text.strip()
    if current_text == prev_text:
        return ""
    if current_text.startswith(prev_text):
        return current_text[len(prev_text) :].strip()

    prev_norm = _norm_for_compare(prev_text)
    curr_norm = _norm_for_compare(current_text)
    if curr_norm and curr_norm in prev_norm:
        # Rolling captions often emit suffix-only resets, which are not new speech.
        return ""

    prev_words = _norm_words(prev_text)
    curr_words = _norm_words(current_text)
    max_overlap = min(len(prev_words), len(curr_words))
    for overlap in range(max_overlap, 0, -1):
        if prev_words[-overlap:] == curr_words[:overlap]:
            return _raw_slice_after_norm_words(current_text, overlap)

    return current_text.strip()


def _split_overlong_cue(cue: Cue) -> list[Cue]:
    duration_ms = cue.end_ms - cue.start_ms
    word_count = len(re.findall(r"[A-Za-z0-9']+", cue.text))
    if word_count <= MAX_SENTENCE_WORDS and duration_ms <= MAX_SENTENCE_DURATION_MS:
        return [cue]

    text = cue.text.strip()
    if not text:
        return []

    clauses: list[tuple[str, int, int]] = []
    for match in CLAUSE_RE.finditer(text):
        clause = match.group().strip()
        if clause:
            clauses.append((clause, match.start(), match.end()))

    if len(clauses) <= 1:
        words = text.split()
        if len(words) <= MAX_SENTENCE_WORDS:
            return [cue]

        chunks: list[Cue] = []
        total_words = max(1, len(words))
        start_word = 0
        while start_word < len(words):
            end_word = min(len(words), start_word + MAX_SENTENCE_WORDS)
            chunk_text = " ".join(words[start_word:end_word]).strip(",;: ")
            ratio_start = start_word / total_words
            ratio_end = end_word / total_words
            chunk_start = cue.start_ms + int(duration_ms * ratio_start)
            chunk_end = cue.start_ms + int(duration_ms * ratio_end)
            if chunk_end <= chunk_start:
                chunk_end = chunk_start + 250
            chunks.append(Cue(start_ms=chunk_start, end_ms=chunk_end, text=chunk_text))
            start_word = end_word
        return chunks

    chunks: list[Cue] = []
    pending_texts: list[str] = []
    pending_start = clauses[0][1]
    pending_end = clauses[0][2]
    pending_words = 0

    def flush_pending() -> None:
        nonlocal pending_texts, pending_start, pending_end, pending_words
        if not pending_texts:
            return
        chunk_text = " ".join(t.strip() for t in pending_texts).strip()
        chunk_text = chunk_text.strip(",;: ")
        if chunk_text:
            ratio_start = pending_start / max(1, len(text))
            ratio_end = pending_end / max(1, len(text))
            chunk_start = cue.start_ms + int(duration_ms * ratio_start)
            chunk_end = cue.start_ms + int(duration_ms * ratio_end)
            if chunk_end <= chunk_start:
                chunk_end = chunk_start + 250
            chunks.append(Cue(start_ms=chunk_start, end_ms=chunk_end, text=chunk_text))
        pending_texts = []
        pending_words = 0

    for clause_text, clause_start, clause_end in clauses:
        clause_words = len(re.findall(r"[A-Za-z0-9']+", clause_text))
        if pending_texts and (pending_words + clause_words) > MAX_SENTENCE_WORDS:
            flush_pending()
            pending_start = clause_start
            pending_end = clause_end

        if not pending_texts:
            pending_start = clause_start
        pending_end = clause_end
        pending_texts.append(clause_text)
        pending_words += clause_words

    flush_pending()
    return chunks if chunks else [cue]


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _is_tiny_practice_cue(cue: Cue) -> bool:
    duration_ms = cue.end_ms - cue.start_ms
    return _word_count(cue.text) < MIN_PRACTICE_WORDS or duration_ms < MIN_PRACTICE_DURATION_MS


def _merge_tiny_cues(cues: list[Cue]) -> list[Cue]:
    if not cues:
        return cues

    merged: list[Cue] = []
    for cue in cues:
        current = Cue(start_ms=cue.start_ms, end_ms=cue.end_ms, text=cue.text.strip())
        if _is_tiny_practice_cue(current) and merged:
            prev = merged[-1]
            prev.text = f"{prev.text} {current.text}".strip()
            prev.end_ms = max(prev.end_ms, current.end_ms)
            continue
        merged.append(current)

    while len(merged) >= 2 and _is_tiny_practice_cue(merged[0]):
        first = merged.pop(0)
        merged[0].text = f"{first.text} {merged[0].text}".strip()
        merged[0].start_ms = min(first.start_ms, merged[0].start_ms)

    return merged


def finalize_practice_cues(cues: list[Cue]) -> list[Cue]:
    if not cues:
        return []

    split_cues: list[Cue] = []
    for cue in cues:
        split_cues.extend(_split_overlong_cue(cue))
    split_cues = _merge_tiny_cues(split_cues)

    for idx, cue in enumerate(split_cues):
        if idx > 0 and cue.start_ms < split_cues[idx - 1].start_ms:
            cue.start_ms = split_cues[idx - 1].start_ms
        if cue.end_ms <= cue.start_ms:
            cue.end_ms = cue.start_ms + 300

    return split_cues


def _parse_raw_cues(content: str) -> list[Cue]:
    cues: list[Cue] = []
    lines = content.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = TIMESTAMP_RE.search(line)
        if not match:
            i += 1
            continue

        start_ms = ts_to_ms(match.group("start"))
        end_ms = ts_to_ms(match.group("end"))
        i += 1

        text_lines: list[str] = []
        while i < len(lines) and lines[i].strip() != "":
            text_lines.append(lines[i])
            i += 1

        text = clean_text(" ".join(text_lines))
        if text and not text.startswith("[") and (end_ms - start_ms) >= MIN_CUE_MS:
            cues.append(Cue(start_ms=start_ms, end_ms=end_ms, text=text))
        i += 1

    return cues


def parse_subtitle_file_basic(path: Path) -> list[Cue]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    raw_cues = _parse_raw_cues(content)
    return finalize_practice_cues(raw_cues)


def parse_subtitle_file_incremental(path: Path) -> list[Cue]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    raw_cues = _parse_raw_cues(content)

    rolling_fragments: list[Cue] = []
    prev_cue_text = ""
    for cue in raw_cues:
        increment = _extract_increment(prev_cue_text, cue.text)
        prev_cue_text = cue.text
        if not increment:
            continue
        rolling_fragments.append(Cue(start_ms=cue.start_ms, end_ms=cue.end_ms, text=increment))

    normalized_sentences: list[Cue] = []
    recent_norms: list[str] = []
    buffer_text = ""
    buffer_start_ms: int | None = None

    for fragment in rolling_fragments:
        if not buffer_text:
            buffer_start_ms = fragment.start_ms
            buffer_text = fragment.text
        else:
            buffer_text = f"{buffer_text} {fragment.text}".strip()

        while True:
            match = SENTENCE_RE.search(buffer_text)
            if not match:
                break

            sentence = clean_text(match.group())
            buffer_text = buffer_text[match.end() :].strip()

            words = re.findall(r"[A-Za-z0-9']+", sentence)
            if len(words) < 3:
                if not buffer_text:
                    buffer_start_ms = None
                continue

            norm = _norm_for_compare(sentence)
            if not norm:
                if not buffer_text:
                    buffer_start_ms = None
                continue

            is_duplicate = False
            for prev_norm in recent_norms[-12:]:
                if norm == prev_norm:
                    is_duplicate = True
                    break
                if len(norm.split()) >= 3 and norm in prev_norm:
                    is_duplicate = True
                    break

            if not is_duplicate:
                start_ms = buffer_start_ms if buffer_start_ms is not None else fragment.start_ms
                end_ms = max(start_ms + 250, fragment.end_ms)
                normalized_sentences.append(Cue(start_ms=start_ms, end_ms=end_ms, text=sentence))
                recent_norms.append(norm)

            if buffer_text:
                # Remaining text belongs to the current fragment tail.
                buffer_start_ms = fragment.start_ms
            else:
                buffer_start_ms = None

    if normalized_sentences:
        return finalize_practice_cues(normalized_sentences)

    # Fallback for subtitle formats that do not punctuate well.
    return finalize_practice_cues(raw_cues)


def parse_subtitle_file(path: Path) -> list[Cue]:
    # Backward-compatible default parser.
    return parse_subtitle_file_incremental(path)
