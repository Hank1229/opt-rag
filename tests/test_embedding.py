"""Step 07 embedder tests against a mocked HTTP transport; no real Gemini calls.

All tests here are extra edge cases added by Claude (not in Hank's expected results).
"""

import json
import math

import httpx
import pytest

from app.embedding import DIMENSIONS, MAX_ATTEMPTS, MODEL, EmbeddingError, GeminiEmbedder

FAKE_KEY = "test-key-not-real"


def embedder_for(handler, sleeps=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiEmbedder(FAKE_KEY, client=client, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def ok_response(request: httpx.Request) -> httpx.Response:
    count = len(json.loads(request.content)["requests"])
    return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0] + [0.0] * (DIMENSIONS - 2)}] * count})


# Extra (Claude): request carries model, task type, 768 dims; key only in a header;
# returned vectors are unit length.
def test_extra_request_shape_and_normalization():
    seen = []

    def handler(request):
        seen.append(request)
        return ok_response(request)

    vectors = embedder_for(handler).embed(["a", "b"])

    request = seen[0]
    assert FAKE_KEY not in str(request.url)
    assert request.headers["x-goog-api-key"] == FAKE_KEY
    body = json.loads(request.content)["requests"][0]
    assert body["model"] == f"models/{MODEL}"
    assert body["taskType"] == "RETRIEVAL_DOCUMENT"
    assert body["outputDimensionality"] == DIMENSIONS
    assert len(vectors) == 2
    assert vectors[0][:2] == pytest.approx([0.6, 0.8])
    assert math.sqrt(sum(v * v for v in vectors[0])) == pytest.approx(1.0)


# Extra (Claude): more than 100 texts are sent in batches of at most 100.
def test_extra_batches_of_100():
    sizes = []

    def handler(request):
        sizes.append(len(json.loads(request.content)["requests"]))
        return ok_response(request)

    assert len(embedder_for(handler).embed(["t"] * 250)) == 250
    assert sizes == [100, 100, 50]


# Extra (Claude): 429 and 503 are retried, honoring the 429 retryDelay hint.
def test_extra_retries_429_and_5xx():
    responses = iter([
        httpx.Response(429, json={"error": {"details": [{"retryDelay": "7s"}]}}),
        httpx.Response(503, text="unavailable"),
    ])
    sleeps = []

    def handler(request):
        return next(responses, None) or ok_response(request)

    assert len(embedder_for(handler, sleeps).embed(["a"])) == 1
    assert len(sleeps) == 2
    assert sleeps[0] >= 8  # retryDelay 7s plus a second of margin


# Extra (Claude): a 400 is not retried; persistent 500s give up after MAX_ATTEMPTS.
def test_extra_gives_up():
    calls = []

    def bad_request(request):
        calls.append(1)
        return httpx.Response(400, text="bad request")

    with pytest.raises(EmbeddingError, match="400"):
        embedder_for(bad_request).embed(["a"])
    assert len(calls) == 1

    calls.clear()

    def always_500(request):
        calls.append(1)
        return httpx.Response(500, text="boom")

    with pytest.raises(EmbeddingError, match="after"):
        embedder_for(always_500).embed(["a"])
    assert len(calls) == MAX_ATTEMPTS


# A 429 asking for an hour sleeps at most 60 seconds per retry and gives up after 5 attempts.
def test_retry_delay_is_capped_at_60_seconds():
    calls = []
    sleeps = []

    def daily_quota(request):
        calls.append(1)
        return httpx.Response(429, json={"error": {"details": [{"retryDelay": "3600s"}]}})

    with pytest.raises(EmbeddingError, match="after 5 attempts"):
        embedder_for(daily_quota, sleeps).embed(["a"])
    assert len(calls) == 5
    assert sleeps == [60] * 4


# Extra (Claude): a response with the wrong number of vectors or dims is an error.
def test_extra_rejects_malformed_response():
    def wrong_dims(request):
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] * 3072}]})

    with pytest.raises(EmbeddingError, match="768"):
        embedder_for(wrong_dims).embed(["a"])

    def too_few(request):
        return httpx.Response(200, json={"embeddings": []})

    with pytest.raises(EmbeddingError, match="got 0"):
        embedder_for(too_few).embed(["a"])
