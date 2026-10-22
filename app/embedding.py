"""Gemini embeddings over the REST API: batched, retried on 429/5xx, L2-normalized,
optionally cached in a local JSONL file so a rerun of ingest re-embeds nothing.

Model, size, and task type are locked: CLAUDE.md "Embedding" and DECISIONS.md,
Step 07 "Embedding model and task types". The API key goes in a request header,
never the URL, so it can't leak through logged URLs or error messages.
"""

import hashlib
import json
import logging
import math
import os
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
MAX_TOTAL_SLEEP_SECONDS = 120  # per request, across all retries
RETRY_DELAY_RE = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')

log = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class RetryDelayTooLong(RuntimeError):
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
        self.cache = cache
        self.cached = load_cache(cache) if cache else {}

    def key(self, text: str) -> str:
        """Cache key: a vector is reusable only for the same model, size, task type, and text."""
        return hashlib.sha256(f"{MODEL}\n{DIMENSIONS}\n{self.task_type}\n{text}".encode()).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One unit vector per text, in order; texts already in the cache skip the API.
        Each batch is cached as soon as it returns, so a later failing batch loses nothing."""
        keys = [self.key(t) for t in texts]
        misses = [(k, t) for k, t in zip(keys, texts) if k not in self.cached]
        new = {}
        for start in range(0, len(misses), BATCH_SIZE):
            batch = misses[start : start + BATCH_SIZE]
            vectors = dict(zip([k for k, _ in batch], self._embed_batch([t for _, t in batch])))
            if self.cache:
                append_cache(self.cache, vectors)
                self.cached.update(vectors)
            new.update(vectors)
        return [new[k] if k in new else self.cached[k] for k in keys]

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
        slept = 0.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.client.post(ENDPOINT, json=body, headers=self.headers)
            except httpx.TransportError as exc:
                problem, reply = type(exc).__name__, ""
            else:
                if response.status_code == 200:
                    return response
                problem, reply = f"HTTP {response.status_code}: {response.text[:300]}", response.text
                if response.status_code not in RETRY_STATUSES:
                    raise EmbeddingError(f"Gemini embedding request failed, {problem}")
            if attempt == MAX_ATTEMPTS:
                raise EmbeddingError(f"Gemini embedding request failed after {attempt} attempts, {problem}")
            try:
                slept = wait_to_retry(attempt, reply, self.sleep, slept)
            except RetryDelayTooLong as exc:
                raise EmbeddingError(str(exc)) from exc
        raise AssertionError("unreachable")


def wait_to_retry(attempt: int, reply: str, sleep, slept: float) -> float:
    """Sleep before the next attempt and return the request's new total slept: Gemini's retryDelay
    hint plus 1 s if the reply has one, else backoff. Raises instead of sleeping when the wait would
    exceed 61 s (a daily quota) or push the total past 120 s: no retry would succeed in time."""
    hint = RETRY_DELAY_RE.search(reply)
    delay = float(hint.group(1)) + 1 if hint else backoff_seconds(attempt)
    if hint and delay > MAX_BACKOFF_SECONDS + 1:
        raise RetryDelayTooLong(f"Gemini asked to retry in {delay - 1:g} s, a wait over the {MAX_BACKOFF_SECONDS + 1} s limit: {reply[:300]}")
    if slept + delay > MAX_TOTAL_SLEEP_SECONDS:
        raise RetryDelayTooLong(
            f"retrying in {delay:g} s would bring the wait to {slept + delay:g} s, past the {MAX_TOTAL_SLEEP_SECONDS} s total: {reply[:300]}"
        )
    sleep(delay)
    return slept + delay


def load_cache(path: Path) -> dict[str, list[float]]:
    """Cached vectors by key. A line that is not a whole entry (e.g. cut off by an interrupted
    run) is skipped with a warning, and its text gets embedded again."""
    if not path.exists():
        return {}
    cached = {}
    with path.open() as lines:
        for number, line in enumerate(lines, 1):
            try:
                entry = json.loads(line)
                key, values = entry["sha256"], entry["values"]
                valid = len(values) == DIMENSIONS
            except (ValueError, KeyError, TypeError):
                valid = False
            if valid:
                cached[key] = values
            else:
                log.warning("embedding cache %s: skipping bad line %d", path, number)
    return cached


def append_cache(path: Path, vectors: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = "".join(json.dumps({"sha256": key, "values": values}) + "\n" for key, values in vectors.items())
    with path.open("ab+") as out:
        # Finish a line cut off by an interrupted run, so it doesn't swallow the next entry.
        end = out.seek(0, os.SEEK_END)
        if end:
            out.seek(end - 1)
            if out.read(1) != b"\n":
                out.write(b"\n")
        out.write(entries.encode())


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
