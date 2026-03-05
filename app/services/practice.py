from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, func, select

from app.models import PracticeSession, Sentence


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def next_sentence_index(
    db: Session,
    practice_session: PracticeSession,
    sentence_idx: int,
    score_total: float,
) -> tuple[int | None, str]:
    queue = json.loads(practice_session.revisit_queue_json)
    retry_counts = json.loads(practice_session.retry_counts_json)
    retries = int(retry_counts.get(str(sentence_idx), 0))

    if score_total < 0.6 and retries < 3:
        retry_counts[str(sentence_idx)] = retries + 1
        next_idx = sentence_idx
    else:
        if 0.6 <= score_total < 0.8 and sentence_idx not in queue:
            queue.append(sentence_idx)
        next_idx = sentence_idx + 1

    max_idx = db.exec(
        select(func.max(Sentence.idx)).where(Sentence.episode_id == practice_session.episode_id)
    ).one()

    if max_idx is None:
        practice_session.status = "completed"
        practice_session.updated_at = utc_now()
        db.add(practice_session)
        return None, "completed"

    if next_idx > max_idx:
        if queue:
            next_idx = queue.pop(0)
        else:
            next_idx = None

    if next_idx is None:
        practice_session.status = "completed"
    else:
        practice_session.current_idx = next_idx

    practice_session.revisit_queue_json = json.dumps(queue)
    practice_session.retry_counts_json = json.dumps(retry_counts)
    practice_session.updated_at = utc_now()

    db.add(practice_session)
    return next_idx, practice_session.status
