from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import ServiceUnavailable
from blackmoa.providers.http import request
from blackmoa.services import settings as S


@dataclass
class Transcript:
    text: str
    duration_s: float
    language: str


class OpenAISTT:
    provider = "openai"

    def __init__(self, key: str, model: str):
        self.key, self.model = key, model

    async def transcribe(self, audio: bytes, mime: str, language: str | None = None) -> Transcript:
        ext = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/ogg": "ogg",
               "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/flac": "flac"}.get(mime.split(";")[0], "webm")
        data = {"model": self.model, "response_format": "json"}
        if language:
            data["language"] = language
        r = await request("POST", "https://api.openai.com/v1/audio/transcriptions",
                          headers={"Authorization": f"Bearer {self.key}"}, data=data,
                          files={"file": (f"audio.{ext}", audio, mime.split(";")[0])})
        j = r.json()
        return Transcript(text=j.get("text", "").strip(), duration_s=float(j.get("duration") or 0.0), language=language or "")


class ElevenLabsSTT:
    provider = "elevenlabs"

    def __init__(self, key: str, model: str = "scribe_v1"):
        self.key, self.model = key, model

    async def transcribe(self, audio: bytes, mime: str, language: str | None = None) -> Transcript:
        data = {"model_id": self.model}
        if language:
            data["language_code"] = language
        r = await request("POST", "https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": self.key},
                          data=data, files={"file": ("audio", audio, mime.split(";")[0])})
        j = r.json()
        return Transcript(text=j.get("text", "").strip(), duration_s=0.0, language=j.get("language_code", ""))


async def get_stt(db: AsyncSession):
    prov = await S.get(db, "stt.provider")
    model = await S.get(db, "stt.model")
    if prov == "openai":
        key = await S.get(db, "providers.openai.api_key")
        if key:
            return OpenAISTT(key, model or "gpt-4o-mini-transcribe")
    if prov == "elevenlabs":
        key = await S.get(db, "providers.elevenlabs.api_key")
        if key:
            return ElevenLabsSTT(key, model or "scribe_v1")
    raise ServiceUnavailable("stt not configured", code="stt_unavailable")
