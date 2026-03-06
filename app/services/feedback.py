from __future__ import annotations

from openai import OpenAI

from app.core.config import get_settings


def _score_label(score: float) -> str:
    if score >= 0.85:
        return "High"
    if score >= 0.6:
        return "Moderate"
    return "Low"


def _preview_words(words: list[str], limit: int = 3) -> str:
    preview = ", ".join(words[:limit])
    if len(words) > limit:
        preview += ", ..."
    return preview


def build_score_explanations(
    *,
    missed_words: list[str],
    extra_words: list[str],
    score_word: float,
    score_timing: float,
    score_total: float,
    target_duration_s: float | None,
    user_duration_s: float | None,
) -> dict[str, str]:
    if not missed_words and not extra_words:
        word_detail = (
            f"{_score_label(score_word)} word score because your attempt matched the target words closely "
            "with no missed or extra words detected."
        )
    else:
        parts: list[str] = []
        if missed_words:
            parts.append(f"missed {len(missed_words)} word(s): {_preview_words(missed_words)}")
        if extra_words:
            parts.append(f"added {len(extra_words)} extra word(s): {_preview_words(extra_words)}")
        word_detail = f"{_score_label(score_word)} word score because you " + " and ".join(parts) + "."

    if target_duration_s and user_duration_s and target_duration_s > 0:
        duration_gap_s = abs(user_duration_s - target_duration_s)
        if score_timing >= 0.85:
            timing_detail = (
                f"{_score_label(score_timing)} timing score because your recording length stayed close to the target "
                f"({user_duration_s:.2f}s vs {target_duration_s:.2f}s)."
            )
        elif score_timing >= 0.6:
            timing_detail = (
                f"{_score_label(score_timing)} timing score because your rhythm was somewhat close, but the duration "
                f"still differed by {duration_gap_s:.2f}s ({user_duration_s:.2f}s vs {target_duration_s:.2f}s)."
            )
        else:
            timing_detail = (
                f"{_score_label(score_timing)} timing score because your recording length was far from the target "
                f"by {duration_gap_s:.2f}s ({user_duration_s:.2f}s vs {target_duration_s:.2f}s)."
            )
    else:
        timing_detail = "Timing score was estimated without enough duration data."

    if score_word >= 0.85 and score_timing >= 0.85:
        total_detail = (
            f"{_score_label(score_total)} total score because both word accuracy and pacing were strong. "
            "The total score weights word accuracy more heavily than timing."
        )
    elif score_word >= 0.85 and score_timing < 0.6:
        total_detail = (
            f"{_score_label(score_total)} total score because your words were strong, but timing pulled the total down. "
            "The total score weights word accuracy more heavily than timing."
        )
    elif score_word < 0.6 and score_timing >= 0.85:
        total_detail = (
            f"{_score_label(score_total)} total score because your rhythm was solid, but word accuracy pulled the total down. "
            "The total score weights word accuracy more heavily than timing."
        )
    else:
        total_detail = (
            f"{_score_label(score_total)} total score because both word accuracy and timing still need work. "
            "The total score weights word accuracy more heavily than timing."
        )

    return {
        "score_word_detail": word_detail,
        "score_timing_detail": timing_detail,
        "score_total_detail": total_detail,
    }


class FeedbackService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _fallback_tip(self, score_total: float, missed_words: list[str]) -> str:
        if score_total < 0.6 and missed_words:
            word = missed_words[0]
            return f"Replay once at 0.8x and focus on hearing '{word}' clearly before repeating."
        if score_total < 0.8:
            return "Good attempt. Keep sentence rhythm steady and avoid adding pauses between word groups."
        return "Strong repetition. Next step: match stress and speed even more closely."

    def generate_tip(
        self,
        reference: str,
        user_text: str,
        missed_words: list[str],
        extra_words: list[str],
        score_total: float,
    ) -> str:
        if not self.settings.llm_api_key:
            return self._fallback_tip(score_total, missed_words)

        client = OpenAI(api_key=self.settings.llm_api_key, base_url=self.settings.llm_base_url)
        system_prompt = (
            "You are an English shadowing coach. Give exactly one concise, practical tip in <= 25 words."
        )
        user_prompt = (
            f"Reference: {reference}\n"
            f"Learner said: {user_text}\n"
            f"Missed words: {', '.join(missed_words) if missed_words else 'None'}\n"
            f"Extra words: {', '.join(extra_words) if extra_words else 'None'}\n"
            f"Score: {score_total:.2f}\n"
        )

        try:
            response = client.chat.completions.create(
                model=self.settings.llm_model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content if response.choices else None
            if content:
                return content.strip()
        except Exception:
            pass

        return self._fallback_tip(score_total, missed_words)
