"""Embedding providers (API only)."""
from __future__ import annotations

import hashlib
import math
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from memora.providers.http import request
from memora.services import settings as S


class EmbeddingProvider(Protocol):
    provider: str
    model: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedding:
    provider = "openai"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dim: int = 1536):
        self.key, self.model, self.dim = api_key, model, dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 96):
            batch = [t[:24000] for t in texts[i:i + 96]]
            r = await request("POST", "https://api.openai.com/v1/embeddings", headers={"Authorization": f"Bearer {self.key}"},
                              json={"model": self.model, "input": batch, "dimensions": self.dim})
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend([d["embedding"] for d in data])
        return out


class GeminiEmbedding:
    provider = "gemini"

    def __init__(self, api_key: str, model: str = "text-embedding-004", dim: int = 768):
        self.key, self.model, self.dim = api_key, model, dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = texts[i:i + 64]
            r = await request("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents",
                              params={"key": self.key},
                              json={"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t[:20000]}]}} for t in batch]})
            out.extend([e["values"] for e in r.json()["embeddings"]])
        return out


class VoyageEmbedding:
    provider = "voyage"

    def __init__(self, api_key: str, model: str = "voyage-3", dim: int = 1024):
        self.key, self.model, self.dim = api_key, model, dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            r = await request("POST", "https://api.voyageai.com/v1/embeddings", headers={"Authorization": f"Bearer {self.key}"},
                              json={"model": self.model, "input": texts[i:i + 64]})
            out.extend([d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])])
        return out


class HashEmbedding:
    """Deterministic offline fallback for tests / no-key installs (NOT semantic)."""
    provider = "hash"

    def __init__(self, dim: int = 1536):
        self.model, self.dim = "hash", dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in t.lower().split():
                h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
                v[h % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class EmbeddingUnavailable(Exception):
    code = "embedding_key_missing"

    def __init__(self, message: str = "embedding provider not configured (embedding_key_missing)"):
        super().__init__(message)


async def get_embedding_provider(db: AsyncSession) -> EmbeddingProvider:
    prov = await S.get(db, "embedding.provider")
    model = await S.get(db, "embedding.model")
    dim = int(await S.get(db, "embedding.dim") or 1536)
    if prov == "openai":
        key = await S.get(db, "providers.openai.api_key")
        if not key:
            raise EmbeddingUnavailable()
        return OpenAIEmbedding(key, model, dim)
    if prov == "gemini":
        key = await S.get(db, "providers.google.api_key")
        if not key:
            raise EmbeddingUnavailable()
        return GeminiEmbedding(key, model, dim)
    if prov == "voyage":
        key = await S.get(db, "providers.voyage.api_key")
        if not key:
            raise EmbeddingUnavailable()
        return VoyageEmbedding(key, model, dim)
    if prov == "hash":
        return HashEmbedding(dim)
    raise EmbeddingUnavailable()


def pad(vec: list[float], dim: int = 1536) -> list[float]:
    """Store vectors in the fixed 1536 column: pad/truncate (documented in plan/09)."""
    if len(vec) == dim:
        return vec
    if len(vec) > dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))


async def embedding_available(db) -> bool:
    """Whether semantic search can run. False means documents are still indexed and still
    searchable — by keyword only — so the UI can say that instead of looking broken."""
    try:
        await get_embedding_provider(db)
        return True
    except EmbeddingUnavailable:
        return False
