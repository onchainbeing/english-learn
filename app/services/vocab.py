from __future__ import annotations

from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import VocabItem, VocabReview


def add_missed_words(session: Session, missed_words: list[str], source_sentence_id: int) -> None:
    unique_words = {w.lower() for w in missed_words if len(w) >= 5}
    for word in unique_words:
        existing = session.exec(select(VocabItem).where(VocabItem.word == word)).first()
        if existing:
            continue
        session.add(
            VocabItem(
                word=word,
                source_sentence_id=source_sentence_id,
                due_date=date.today(),
            )
        )


def review_vocab_item(session: Session, item: VocabItem, quality: int) -> VocabItem:
    quality = max(0, min(5, quality))

    if quality < 3:
        item.streak = 0
        item.interval_days = 1
    else:
        item.streak += 1
        if item.streak == 1:
            item.interval_days = 1
        elif item.streak == 2:
            item.interval_days = 3
        else:
            item.interval_days = max(1, int(item.interval_days * item.ease_factor))

    item.ease_factor = max(1.3, item.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    item.due_date = date.today() + timedelta(days=item.interval_days)

    session.add(item)
    session.add(
        VocabReview(
            vocab_item_id=item.id,
            quality=quality,
            next_due_date=item.due_date,
        )
    )
    return item
