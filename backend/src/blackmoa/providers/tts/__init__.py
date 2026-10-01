from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.config import get_settings
from blackmoa.core.errors import ServiceUnavailable
from blackmoa.providers.http import TIMEOUT
from blackmoa.services import settings as S

OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]
_SENT = re.compile(r"(?<=[.!?。！？\n])\s+")


def split_sentences(text: str, max_len: int = 400) -> list[str]:
    parts = [p.strip() for p in _SENT.split(text) if p.strip()]
    out: list[str] = []
    for p in parts:
        while len(p) > max_len:
            out.append(p[:max_len])
            p = p[max_len:]
        out.append(p)
    return out or [text]


class OpenAITTS:
    provider = "openai"

    def __init__(self, key: str, model: str):
        self.key, self.model = key, model

    def voices(self) -> list[dict]:
        return [{"id": v, "name": v.title()} for v in OPENAI_VOICES]

    async def synthesize(self, text: str, voice: str, speed: float = 1.0, fmt: str = "mp3") -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", "https://api.openai.com/v1/audio/speech",
                                     headers={"Authorization": f"Bearer {self.key}"},
                                     json={"model": self.model, "voice": voice or "nova", "input": text[:4000],
                                           "response_format": fmt, "speed": max(0.5, min(2.0, speed))}) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    raise ServiceUnavailable(f"tts failed: {body[:200]!r}", code="tts_failed")
                async for chunk in r.aiter_bytes():
                    yield chunk


class ElevenLabsTTS:
    provider = "elevenlabs"

    def __init__(self, key: str, model: str = "eleven_multilingual_v2"):
        self.key, self.model = key, model

    def voices(self) -> list[dict]:
        return [{"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"}, {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"}]

    async def synthesize(self, text: str, voice: str, speed: float = 1.0, fmt: str = "mp3") -> AsyncIterator[bytes]:
        vid = voice or "21m00Tcm4TlvDq8ikWAM"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream",
                                     headers={"xi-api-key": self.key},
                                     json={"text": text[:4000], "model_id": self.model}) as r:
                if r.status_code >= 400:
                    raise ServiceUnavailable("tts failed", code="tts_failed")
                async for chunk in r.aiter_bytes():
                    yield chunk


async def get_tts(db: AsyncSession):
    prov = await S.get(db, "tts.provider")
    model = await S.get(db, "tts.model")
    if prov == "openai":
        key = await S.get(db, "providers.openai.api_key")
        if key:
            return OpenAITTS(key, model or "gpt-4o-mini-tts")
    if prov == "elevenlabs":
        key = await S.get(db, "providers.elevenlabs.api_key")
        if key:
            return ElevenLabsTTS(key, model or "eleven_multilingual_v2")
    raise ServiceUnavailable("tts not configured", code="tts_unavailable")


def cache_path(text: str, voice: str, model: str, fmt: str = "mp3"):
    h = hashlib.sha256(f"{model}|{voice}|{text}".encode()).hexdigest()
    p = get_settings().cache_root / "tts" / h[:2]
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{h}.{fmt}"
