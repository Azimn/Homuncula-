from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

TOKEN_RE = re.compile(r"[a-z0-9_']+")

class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...

@dataclass
class HashEmbedder:
    dimensions: int = 192
    name: str = "hash-ngram-v1"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = TOKEN_RE.findall(text.lower())
        features: list[str] = list(tokens)
        features.extend(" ".join(tokens[index : index + 2]) for index in range(len(tokens) - 1))
        features.extend(" ".join(tokens[index : index + 3]) for index in range(len(tokens) - 2))

        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:8], "little") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            weight = 1.0 + min(len(feature), 32) / 64.0
            vector[bucket] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

class OllamaEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 30.0,
        fallback: Embedder | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.fallback = fallback or HashEmbedder()
        self.name = f"ollama:{model}"
        self.dimensions = 0

    def embed(self, text: str) -> list[float]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": text},
                )
            response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings") or []
            if not embeddings:
                raise ValueError("Ollama returned no embedding")
            vector = [float(value) for value in embeddings[0]]
            norm = math.sqrt(sum(value * value for value in vector))
            if norm:
                vector = [value / norm for value in vector]
            self.dimensions = len(vector)
            return vector
        except (httpx.HTTPError, ValueError, TypeError):
            vector = self.fallback.embed(text)
            self.name = self.fallback.name
            self.dimensions = self.fallback.dimensions
            return vector

def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
