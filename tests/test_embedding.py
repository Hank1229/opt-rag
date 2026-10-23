"""Embedder tests against a mocked HTTP transport; no real Gemini calls.

Tests marked "Extra" are edge cases added by Claude. Tests marked "Cache/retry fix N" map to
Hank's expected results for the 2026-10-22 cache and retry fix; "Step 09b re-pin 3" maps to
step 09b part 2 expected result 3.
"""

import hashlib
import json
import logging
import math

import httpx
import pytest

from app.embedding import (
    DIMENSIONS,
    MAX_ATTEMPTS,
    MODEL,
    EmbeddingError,
    GeminiEmbedder,
    RetryDelayTooLong,
    wait_to_retry,
)
from app.ingest.chunking import Chunk

FAKE_KEY = "test-key-not-real"


def embedder_for(handler, sleeps=None, cache=None, task_type="RETRIEVAL_DOCUMENT"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleep = sleeps.append if sleeps is not None else lambda s: None
    return GeminiEmbedder(FAKE_KEY, task_type=task_type, client=client, sleep=sleep, cache=cache)


def quota_429(seconds: str) -> httpx.Response:
    return httpx.Response(429, json={"error": {"details": [{"retryDelay": seconds}]}})


def cache_line(key: str, values: list[float]) -> str:
    return json.dumps({"sha256": key, "values": values}) + "\n"


def expected_key(task_type: str, text: str) -> str:
    return hashlib.sha256(f"{MODEL}\n{DIMENSIONS}\n{task_type}\n{text}".encode()).hexdigest()


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
    responses = iter([quota_429("7s"), httpx.Response(503, text="unavailable")])
    sleeps = []

    def handler(request):
        return next(responses, None) or ok_response(request)

    assert len(embedder_for(handler, sleeps).embed(["a"])) == 1
    assert len(sleeps) == 2
    assert sleeps[0] == 8  # retryDelay 7s plus a 1-second buffer


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


# Extra (Claude), was the 60-second cap test: a hint of exactly 60 seconds is still slept (plus the
# 1-second buffer); a second 61-second sleep would pass the 120-second total, so the next 429 gives up.
def test_extra_hint_of_60_seconds_is_slept():
    calls = []
    sleeps = []

    def quota(request):
        calls.append(1)
        return quota_429("60s")

    with pytest.raises(EmbeddingError, match="120 s"):
        embedder_for(quota, sleeps).embed(["a"])
    assert len(calls) == 2
    assert sleeps == [61]


# Extra (Claude): the same two texts embedded again, by a new embedder on the same file, make zero requests.
def test_extra_cache_skips_api_for_seen_texts(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        texts = [r["content"]["parts"][0]["text"] for r in json.loads(request.content)["requests"]]
        # A different vector per text, so a mix-up between texts would show.
        return httpx.Response(200, json={"embeddings": [{"values": [0.0] * i + [1.0] + [0.0] * (DIMENSIONS - i - 1)} for i in map(len, texts)]})

    cache = tmp_path / "cache" / "embeddings.jsonl"
    texts = ["Header\nfirst chunk", "Header\nthe second chunk"]
    first = embedder_for(handler, cache=cache).embed(texts)
    assert len(calls) == 1

    second = embedder_for(handler, cache=cache).embed(texts)
    assert len(calls) == 1
    assert second == first
    assert first[0] != first[1]


# Step 09b re-pin 3. Re-ingest -> only chunks whose text or header changed are re-embedded; the
# rest come from the cache.
def test_09b_3_reingest_embeds_only_chunks_whose_text_or_header_changed(tmp_path):
    sent = []

    def handler(request):
        sent.append([r["content"]["parts"][0]["text"] for r in json.loads(request.content)["requests"]])
        return ok_response(request)

    cache = tmp_path / "embeddings.jsonl"
    before = [
        Chunk("214.2(f)(1)", 0, "8 CFR 214.2(f) > (1)", "same text"),
        Chunk("214.2(f)(2)", 0, "8 CFR 214.2(f) > (2)", "old text"),
        Chunk("214.2(f)(3)", 0, "8 CFR 214.2(f) > (3) Old heading", "same text"),
    ]
    after = [
        before[0],
        Chunk("214.2(f)(2)", 0, "8 CFR 214.2(f) > (2)", "new text"),
        Chunk("214.2(f)(3)", 0, "8 CFR 214.2(f) > (3) New heading", "same text"),
    ]
    embedder_for(handler, cache=cache).embed([c.embed_text for c in before])
    embedder_for(handler, cache=cache).embed([c.embed_text for c in after])

    assert sent[1] == [after[1].embed_text, after[2].embed_text]


# Cache/retry fix 1: the cache key is sha256 of model + dims + task_type + text, so the same text
# embedded as RETRIEVAL_DOCUMENT and as RETRIEVAL_QUERY makes two cache entries and two API calls.
def test_cache_key_includes_model_dims_and_task_type(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return ok_response(request)

    cache = tmp_path / "embeddings.jsonl"
    embedder_for(handler, cache=cache, task_type="RETRIEVAL_DOCUMENT").embed(["same text"])
    embedder_for(handler, cache=cache, task_type="RETRIEVAL_QUERY").embed(["same text"])

    assert len(calls) == 2
    keys = [json.loads(line)["sha256"] for line in cache.read_text().splitlines()]
    assert keys == [expected_key("RETRIEVAL_DOCUMENT", "same text"), expected_key("RETRIEVAL_QUERY", "same text")]


# Cache/retry fix 2: a half-written line and a blank line are skipped with a warning each; the
# one valid entry is loaded and served without an API call.
def test_bad_cache_lines_are_skipped(tmp_path, caplog):
    vector = [0.6, 0.8] + [0.0] * (DIMENSIONS - 2)
    cache = tmp_path / "embeddings.jsonl"
    cache.write_text(
        '{"sha256": "ab12", "values": [0.01, 0.0\n'
        + "\n"
        + cache_line(expected_key("RETRIEVAL_DOCUMENT", "a"), vector)
    )
    calls = []

    def handler(request):
        calls.append(1)
        return ok_response(request)

    with caplog.at_level(logging.WARNING, logger="app.embedding"):
        embedder = embedder_for(handler, cache=cache)

    assert len(embedder.cached) == 1
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2
    assert embedder.embed(["a"]) == [vector]
    assert calls == []


# Cache/retry fix 3: three batches where the second fails after its retries: the first batch's
# vectors are already in the cache file when the error comes out of embed().
def test_finished_batches_are_cached_before_a_later_batch_fails(tmp_path):
    batches = []

    def handler(request):
        batches.append(1)
        if len(batches) == 1:
            return ok_response(request)
        return httpx.Response(500, text="boom")

    cache = tmp_path / "embeddings.jsonl"
    texts = [f"text {i}" for i in range(201)]  # batches of 100, 100, 1
    with pytest.raises(EmbeddingError, match="after 5 attempts"):
        embedder_for(handler, cache=cache).embed(texts)

    assert len(batches) == 1 + 5  # the third batch is never sent
    keys = [json.loads(line)["sha256"] for line in cache.read_text().splitlines()]
    assert keys == [expected_key("RETRIEVAL_DOCUMENT", t) for t in texts[:100]]


# Cache/retry fix 4 (shared helper; follow-up 2 adds the buffer): a retryDelay hint over 60 seconds
# raises at once without sleeping; a hint under 60 seconds is slept plus a 1-second buffer.
def test_wait_to_retry_follows_the_hint_up_to_60_seconds():
    sleeps = []
    with pytest.raises(RetryDelayTooLong):
        wait_to_retry(1, quota_429("3600s").text, sleeps.append, 0)
    assert sleeps == []

    assert wait_to_retry(1, quota_429("7s").text, sleeps.append, 0) == 8
    assert sleeps == [8]


# Cache/retry follow-up 4: hints of 50, 50, 50 seconds: the helper sleeps 51 and 51, then raises
# before the third sleep, which would bring the total to 153 s, past 120.
def test_wait_to_retry_caps_total_sleep_at_120_seconds():
    sleeps = []
    reply = quota_429("50s").text
    slept = wait_to_retry(1, reply, sleeps.append, 0)
    slept = wait_to_retry(2, reply, sleeps.append, slept)
    with pytest.raises(RetryDelayTooLong, match="120 s"):
        wait_to_retry(3, reply, sleeps.append, slept)
    assert sleeps == [51, 51]


# Extra (Claude): the embedder carries the total across its attempts: three 50-second hints give
# two sleeps and an EmbeddingError on the third 429.
def test_extra_embedder_stops_at_total_sleep_cap():
    calls = []
    sleeps = []

    def quota(request):
        calls.append(1)
        return quota_429("50s")

    with pytest.raises(EmbeddingError, match="120 s"):
        embedder_for(quota, sleeps).embed(["a"])
    assert len(calls) == 3
    assert sleeps == [51, 51]


# Cache/retry fix 4 (embedder): an hour-long hint gives up after one call and no sleep; a 7-second
# hint is retried with 8-second sleeps (follow-up 2: 1-second buffer), 5 attempts at most.
def test_embedder_retries_follow_the_shared_helper():
    calls = []
    sleeps = []

    def daily_quota(request):
        calls.append(1)
        return quota_429("3600s")

    with pytest.raises(EmbeddingError, match="3600"):
        embedder_for(daily_quota, sleeps).embed(["a"])
    assert len(calls) == 1
    assert sleeps == []

    calls.clear()

    def short_quota(request):
        calls.append(1)
        return quota_429("7s")

    with pytest.raises(EmbeddingError, match="after 5 attempts"):
        embedder_for(short_quota, sleeps).embed(["a"])
    assert len(calls) == 5
    assert sleeps == [8] * 4


# Cache/retry follow-up 3 (embedder): RetryDelayTooLong does not escape embed(); it comes out as
# EmbeddingError with the helper's original message.
def test_embedder_reraises_long_delay_as_embedding_error():
    with pytest.raises(RetryDelayTooLong) as helper_error:
        wait_to_retry(1, quota_429("3600s").text, lambda seconds: None, 0)

    with pytest.raises(EmbeddingError) as raised:
        embedder_for(lambda request: quota_429("3600s")).embed(["a"])
    assert type(raised.value) is EmbeddingError
    assert str(raised.value) == str(helper_error.value)


# Extra (Claude), cache/retry fix 5: a cache line whose vector is not 768 long is skipped like a
# corrupted line, so the text is embedded again.
def test_extra_cache_line_with_wrong_dims_is_skipped(tmp_path, caplog):
    cache = tmp_path / "embeddings.jsonl"
    cache.write_text(cache_line(expected_key("RETRIEVAL_DOCUMENT", "a"), [1.0] * (DIMENSIONS - 1)))
    calls = []

    def handler(request):
        calls.append(1)
        return ok_response(request)

    with caplog.at_level(logging.WARNING, logger="app.embedding"):
        embedder = embedder_for(handler, cache=cache)

    assert embedder.cached == {}
    assert len(caplog.records) == 1
    assert len(embedder.embed(["a"])[0]) == DIMENSIONS
    assert len(calls) == 1


# Extra (Claude): a cache file cut off mid-line (no trailing newline) does not swallow the next
# entry appended to it.
def test_extra_append_after_cut_off_line(tmp_path):
    cache = tmp_path / "embeddings.jsonl"
    cache.write_text('{"sha256": "ab12", "values": [0.01')
    embedder_for(ok_response, cache=cache).embed(["a"])

    assert list(embedder_for(ok_response, cache=cache).cached) == [expected_key("RETRIEVAL_DOCUMENT", "a")]


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
