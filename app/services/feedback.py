from __future__ import annotations

from openai import OpenAI

from app.core.config import get_settings


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
