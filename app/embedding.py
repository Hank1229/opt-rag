"""Gemini embeddings over the REST API: batched, retried on 429/5xx, L2-normalized,
optionally cached in a local JSONL file so a rerun of ingest re-embeds nothing.

Model, size, and task type are locked: CLAUDE.md "Embedding" and DECISIONS.md,
Step 07 "Embedding model and task types". The API key goes in a request header,
never the URL, so it can't leak through logged URLs or error messages.
"""

import hashlib
import json
import math
import random
import re
import time
from pathlib import Path

import httpx

MODEL = "gemini-embedding-001"
DIMENSIONS = 768
BATCH_SIZE = 100  # API limit per batchEmbedContents request
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:batchEmbedContents"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 60
RETRY_DELAY_RE = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')


class EmbeddingError(RuntimeError):
    pass


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
        client=None,
        sleep=time.sleep,
        cache: Path | None = None,
    ):
        self.task_type = task_type
        self.headers = {"x-goog-api-key": api_key}
        self.client = client or httpx.Client(timeout=60)
        self.sleep = sleep
        # Keyed by text only, so one cache file must only ever see one task type (ingest's).
        self.cache = cache
        self.cached = load_cache(cache) if cache else {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One unit vector per text, in order; texts already in the cache skip the API."""
        misses = [t for t in texts if text_hash(t) not in self.cached]
        fresh = []
        for start in range(0, len(misses), BATCH_SIZE):
            fresh += self._embed_batch(misses[start : start + BATCH_SIZE])
        new = dict(zip(map(text_hash, misses), fresh))
        vectors = [self.cached.get(text_hash(t)) or new[text_hash(t)] for t in texts]
        if self.cache and new:
            append_cache(self.cache, new)
            self.cached.update(new)
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": f"models/{MODEL}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": self.task_type,
                    "outputDimensionality": DIMENSIONS,
                }
                for text in texts
            ]
        }
        embeddings = self._post(body).json().get("embeddings", [])
        if len(embeddings) != len(texts):
            raise EmbeddingError(f"asked for {len(texts)} embeddings, got {len(embeddings)}")
        return [normalize(e["values"]) for e in embeddings]

    def _post(self, body: dict) -> httpx.Response:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            delay = backoff_seconds(attempt)
            try:
                response = self.client.post(ENDPOINT, json=body, headers=self.headers)
            except httpx.TransportError as exc:
                problem = type(exc).__name__
            else:
                if response.status_code == 200:
                    return response
                problem = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in RETRY_STATUSES:
                    raise EmbeddingError(f"Gemini embedding request failed, {problem}")
                # 429 bodies say how long the quota needs; wait at least that long.
                hint = RETRY_DELAY_RE.search(response.text)
                if hint:
                    delay = max(delay, float(hint.group(1)) + 1)
            if attempt == MAX_ATTEMPTS:
                raise EmbeddingError(f"Gemini embedding request failed after {attempt} attempts, {problem}")
            # A daily-quota 429 can ask for hours; give up after MAX_ATTEMPTS instead of sleeping that long.
            self.sleep(min(delay, MAX_BACKOFF_SECONDS))
        raise AssertionError("unreachable")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_cache(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    with path.open() as lines:
        return {entry["sha256"]: entry["values"] for entry in map(json.loads, lines)}


def append_cache(path: Path, vectors: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        for key, values in vectors.items():
            out.write(json.dumps({"sha256": key, "values": values}) + "\n")


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter: about 2, 4, 8, 16, 32, then capped at 60 seconds."""
    return min(MAX_BACKOFF_SECONDS, 2**attempt) + random.uniform(0, 1)


def normalize(values: list[float]) -> list[float]:
    """Scale to unit length; Gemini vectors below 3072 dims are not normalized by the API."""
    if len(values) != DIMENSIONS:
        raise EmbeddingError(f"expected {DIMENSIONS} dims, got {len(values)}")
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        raise EmbeddingError("zero vector")
    return [v / norm for v in values]
