from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from openai import OpenAI

from app.core.config import get_settings


class STTService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _transcribe_cloud_openai(self, audio_path: Path) -> str:
        if not self.settings.whisper_api_key:
            raise RuntimeError("Missing WHISPER_API_KEY / OPENAI_API_KEY for cloud transcription")

        client = OpenAI(api_key=self.settings.whisper_api_key, base_url=self.settings.whisper_base_url)
        with audio_path.open("rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=self.settings.whisper_model,
                file=audio_file,
                response_format="text",
            )

        if isinstance(transcript, str):
            return transcript.strip()

        text = getattr(transcript, "text", "")
        return str(text).strip()

    def _transcribe_local_whisper(self, audio_path: Path) -> str:
        model = _get_local_whisper_model(
            model_size=self.settings.local_whisper_model,
            device=self.settings.local_whisper_device,
            compute_type=self.settings.local_whisper_compute_type,
            model_root=self.settings.models_dir / "whisper",
        )
        segments, _ = model.transcribe(
            str(audio_path),
            beam_size=self.settings.local_whisper_beam_size,
            language=self.settings.local_whisper_language,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text.strip()

    def transcribe(self, audio_path: Path) -> str:
        provider = self.settings.stt_provider.strip().lower()
        if provider == "local_whisper":
            text = self._transcribe_local_whisper(audio_path)
            if text:
                return text
            raise RuntimeError("Local Whisper transcription returned empty text.")

        if provider in {"openai_whisper", "cloud_whisper"}:
            text = self._transcribe_cloud_openai(audio_path)
            if text:
                return text
            raise RuntimeError("Cloud Whisper transcription returned empty text.")

        raise RuntimeError(
            f"Unsupported STT_PROVIDER='{self.settings.stt_provider}'. "
            "Use 'local_whisper' or 'openai_whisper'."
        )


@lru_cache(maxsize=4)
def _get_local_whisper_model(model_size: str, device: str, compute_type: str, model_root: Path):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Install dependencies and retry "
            "(e.g. `uv sync` with updated pyproject)."
        ) from exc

    model_root.mkdir(parents=True, exist_ok=True)
    return WhisperModel(
        model_size_or_path=model_size,
        device=device,
        compute_type=compute_type,
        download_root=str(model_root),
    )
