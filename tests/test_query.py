"""Step 08 tests: retrieval SQL, prompt building, and the /query endpoint.

Numbered tests map to Hank's expected results 1-8. Tests marked "extra" are edge
cases added by Claude. Retrieval runs against local Supabase with synthetic
vectors; Gemini is mocked everywhere except test 8, which skips without a key.
"""

import json
import math
import os
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main as api
from app.db import connect
from app.embedding import RetryDelayTooLong, wait_to_retry
from app.generation import DISCLAIMER, REFUSAL, GeminiGenerator, GenerationError, build_prompt
from app.retrieval import Hit, query_embedder, retrieve
from helpers import EMBEDDING_DIMS, insert_chunk, insert_document, unit_vector

QUESTION = "How many days of unemployment are allowed on post-completion OPT?"
ECFR_URL = "https://www.ecfr.gov/on/2026-10-01/title-8/section-214.2"
SITS_URL = "https://studyinthestates.dhs.gov/stem-opt-hub/additional-resources/form-i-983-overview"
SOURCE_FIELDS = {"label", "citation_key", "title", "source_tier", "url", "distance"}
CORPUS_CHUNKS = 266  # chunk count of a full local ingest of data/raw/


class FixedEmbedder:
    """Returns the same vector for every text."""

    def __init__(self, vector):
        self.vector = vector

    def embed(self, texts):
        return [self.vector for _ in texts]


class FakeGenerator:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return "Up to 90 days [1]."


def tilted(degrees: float) -> list[float]:
    """Unit vector at the given angle from unit_vector(0), in the plane of dims 0 and 1."""
    values = [0.0] * EMBEDDING_DIMS
    values[0] = math.cos(math.radians(degrees))
    values[1] = math.sin(math.radians(degrees))
    return values


def hit(citation_key, source_tier="ecfr", title="8 CFR 214.2(f) Students", url=ECFR_URL, n=0):
    return Hit(
        id=n,
        citation_key=citation_key,
        title=title,
        source_tier=source_tier,
        url=url,
        content=f"Text of {citation_key}",
        distance=0.1 * n,
    )


@pytest.fixture
def client(app_db):
    """/query wired to the test connection, a fixed query vector, and a fake generator."""
    embedder = FixedEmbedder(unit_vector(0))
    generator = FakeGenerator()
    api.app.dependency_overrides = {
        api.get_conn: lambda: app_db,
        api.get_embedder: lambda: embedder,
        api.get_generator: lambda: generator,
    }
    yield TestClient(api.app), embedder, generator
    api.app.dependency_overrides = {}


def insert_tilted_chunks(db, angles):
    document_id = insert_document(db, url=ECFR_URL)
    return [
        insert_chunk(db, document_id, tilted(angle), citation_key=f"214.2(f)({i})")
        for i, angle in enumerate(angles, 1)
    ]


# 1. Chunks at v, orthogonal to v, and -v: retrieve(v, k=2) returns [v, orthogonal],
# distance ascending, with id, citation_key, title, source_tier, content, distance.
def test_01_retrieve_orders_by_cosine_distance(app_db):
    v = unit_vector(0)
    document_id = insert_document(app_db)
    opposite_id = insert_chunk(app_db, document_id, [-x for x in v], citation_key="214.2(f)(3)")
    orthogonal_id = insert_chunk(app_db, document_id, unit_vector(1), citation_key="214.2(f)(2)")
    same_id = insert_chunk(app_db, document_id, v, citation_key="214.2(f)(1)")

    hits = retrieve(QUESTION, 2, conn=app_db, embedder=FixedEmbedder(v))

    assert [h.id for h in hits] == [same_id, orthogonal_id]
    assert opposite_id not in [h.id for h in hits]
    assert [h.distance for h in hits] == pytest.approx([0.0, 1.0])
    assert hits[0].citation_key == "214.2(f)(1)"
    assert hits[0].title == "Test document"
    assert hits[0].source_tier == "ecfr"
    assert hits[0].content == "Test chunk text"


# Chunks at the same distance come back in id order, so a rerun gets the same top k.
def test_ties_ordered_by_chunk_id(app_db):
    ids = insert_tilted_chunks(app_db, [0, 0, 0])
    # Rewriting the first row moves it to the end of the table, so a plain scan reads it last.
    app_db.execute("update chunks set content = content where id = %s", (ids[0],))

    hits = retrieve(QUESTION, 3, conn=app_db, embedder=FixedEmbedder(unit_vector(0)))

    assert [h.id for h in hits] == ids


# 2. retrieve embeds the bare question (no contextual header) with task type RETRIEVAL_QUERY.
def test_02_retrieve_embeds_question_as_query(app_db):
    requests = []

    def gemini(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [{"values": unit_vector(0)}]})

    embedder = query_embedder("test-key-not-real", client=httpx.Client(transport=httpx.MockTransport(gemini)))
    retrieve(QUESTION, 5, conn=app_db, embedder=embedder)

    [body] = requests
    [request] = body["requests"]
    assert request["taskType"] == "RETRIEVAL_QUERY"
    assert request["content"]["parts"] == [{"text": QUESTION}]


# 3. build_prompt with five chunks: labels [1]-[5] in order (Tier 1 "8 CFR <key>",
# Tier 2 "<title> <key>"), refusal instruction pointing to the DSO, disclaimer, question last.
def test_03_build_prompt_labels_refusal_disclaimer_question_last():
    chunks = [
        hit("214.2(f)(10)(ii)(A)", n=1),
        hit("214.2(f)(10)(ii)(E)", n=2),
        hit("form-i-983-overview#purpose", source_tier="sits", title="Form I-983 Overview", url=SITS_URL, n=3),
        hit("214.2(f)(11)(i)", n=4),
        hit("form-i-983-overview", source_tier="sits", title="Form I-983 Overview", url=SITS_URL, n=5),
    ]
    prompt = build_prompt(QUESTION, chunks)

    labels = [
        "[1] 8 CFR 214.2(f)(10)(ii)(A)",
        "[2] 8 CFR 214.2(f)(10)(ii)(E)",
        "[3] Form I-983 Overview form-i-983-overview#purpose",
        "[4] 8 CFR 214.2(f)(11)(i)",
        "[5] Form I-983 Overview form-i-983-overview",
    ]
    positions = [prompt.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "DSO" in REFUSAL
    assert REFUSAL in prompt
    assert DISCLAIMER in prompt
    assert prompt.endswith(QUESTION)


# 4. POST /query returns 200, a string answer, and five sources with exactly the public
# fields (no content), in retrieve order.
def test_04_query_returns_answer_and_sources(app_db, client):
    test_client, embedder, generator = client
    insert_tilted_chunks(app_db, [50, 10, 40, 0, 30, 20])

    response = test_client.post("/query", json={"question": QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["answer"], str)
    assert len(body["sources"]) == 5
    assert all(set(source) == SOURCE_FIELDS for source in body["sources"])
    expected = retrieve(QUESTION, 5, conn=app_db, embedder=embedder)
    assert [s["citation_key"] for s in body["sources"]] == [h.citation_key for h in expected]
    # Extra (Claude): the response labels are the same strings the prompt used.
    assert all(s["label"] in generator.prompts[0] for s in body["sources"])


# 5. Tier 1 url gets the eCFR paragraph anchor; Tier 2 url is returned as stored.
# Key changed from "(f)(10)(ii)(A)" to the stored form "214.2(f)(10)(ii)(A)" with Hank's OK.
def test_05_source_urls():
    assert api.source_url(hit("214.2(f)(10)(ii)(A)")) == f"{ECFR_URL}#p-214.2(f)(10)(ii)(A)"
    assert api.source_url(hit("form-i-983-overview", source_tier="sits", url=SITS_URL)) == SITS_URL


# 6. Empty, whitespace-only, and over-1000-character questions are rejected with 422.
@pytest.mark.parametrize("question", ["", "   \n\t", "x" * 1001])
def test_06_invalid_question_is_422(client, question):
    test_client, _, generator = client
    assert test_client.post("/query", json={"question": question}).status_code == 422
    assert generator.prompts == []


# Extra (Claude): exactly 1000 characters is accepted.
def test_extra_question_of_1000_chars_is_accepted(app_db, client):
    test_client, _, _ = client
    insert_tilted_chunks(app_db, [0])
    assert test_client.post("/query", json={"question": "x" * 1000}).status_code == 200


# 7a. Fewer chunks than k: retrieve returns what exists.
def test_07a_fewer_chunks_than_k(app_db):
    insert_tilted_chunks(app_db, [0, 30])
    assert len(retrieve(QUESTION, 5, conn=app_db, embedder=FixedEmbedder(unit_vector(0)))) == 2


# 7b. Zero chunks: /query skips the generation call and returns the refusal with the DSO pointer.
def test_07b_zero_chunks_refuses_without_generation(client):
    test_client, _, generator = client

    response = test_client.post("/query", json={"question": QUESTION})

    assert response.status_code == 200
    assert generator.prompts == []
    assert REFUSAL in response.json()["answer"]
    assert "DSO" in response.json()["answer"]
    assert DISCLAIMER in response.json()["answer"]
    assert response.json()["sources"] == []


# Extra (Claude): connections from app.db.connect put pgvector's schema on the search path.
def test_extra_connection_search_path(app_db):
    assert app_db.execute("show search_path").fetchone()[0] == "public,extensions"


def generator_for(handler, sleeps=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleep = sleeps.append if sleeps is not None else lambda seconds: None
    return GeminiGenerator("test-key-not-real", model="gemini-3.6-flash", temperature=0.0, client=client, sleep=sleep)


def generation_reply(model_version, text="Answer [1]."):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}], "modelVersion": model_version}


# Extra (Claude): request carries the model, temperature, and key header; the answer text comes back.
def test_extra_generator_request_shape():
    seen = []

    def gemini(request):
        seen.append(request)
        return httpx.Response(200, json=generation_reply("gemini-3.6-flash"))

    assert generator_for(gemini).complete("prompt text") == "Answer [1]."
    [request] = seen
    assert request.url.path.endswith("/models/gemini-3.6-flash:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key-not-real"
    assert "test-key-not-real" not in str(request.url)
    body = json.loads(request.content)
    assert body["generationConfig"]["temperature"] == 0.0
    assert body["contents"][0]["parts"] == [{"text": "prompt text"}]


# Extra (Claude): a reply served by a different model than configured is an error, so an
# eval run cannot silently switch models.
def test_extra_generator_rejects_other_model_version():
    def gemini(request):
        return httpx.Response(200, json=generation_reply("gemini-3.8-flash"))

    with pytest.raises(GenerationError, match="gemini-3.8-flash"):
        generator_for(gemini).complete("prompt text")


# Retry: two 503s then a 200 returns the answer after two backoff sleeps.
def test_generator_retries_503_then_succeeds():
    responses = iter([httpx.Response(503, text="high demand"), httpx.Response(503, text="high demand")])
    calls = []
    sleeps = []

    def gemini(request):
        calls.append(1)
        return next(responses, None) or httpx.Response(200, json=generation_reply("gemini-3.6-flash"))

    assert generator_for(gemini, sleeps).complete("prompt text") == "Answer [1]."
    assert len(calls) == 3
    assert len(sleeps) == 2


# Retry: five 503s in a row give up with GenerationError after five attempts.
def test_generator_gives_up_after_five_503s():
    calls = []

    def unavailable(request):
        calls.append(1)
        return httpx.Response(503, text="high demand")

    with pytest.raises(GenerationError, match="503"):
        generator_for(unavailable).complete("prompt text")
    assert len(calls) == 5


# Cache/retry fix 4 (generator; replaces the 60-second cap test): an hour-long retryDelay hint
# gives up after one call and no sleep; a 7-second hint is retried with 8-second sleeps
# (follow-up 2: 1-second buffer), 5 attempts at most.
def test_generator_retries_follow_the_shared_helper():
    calls = []
    sleeps = []

    def daily_quota(request):
        calls.append(1)
        return httpx.Response(429, json={"error": {"details": [{"retryDelay": "3600s"}]}})

    with pytest.raises(GenerationError, match="3600"):
        generator_for(daily_quota, sleeps).complete("prompt text")
    assert len(calls) == 1
    assert sleeps == []

    calls.clear()

    def short_quota(request):
        calls.append(1)
        return httpx.Response(429, json={"error": {"details": [{"retryDelay": "7s"}]}})

    with pytest.raises(GenerationError, match="429"):
        generator_for(short_quota, sleeps).complete("prompt text")
    assert len(calls) == 5
    assert sleeps == [8] * 4


# Cache/retry follow-up 3 (generator): RetryDelayTooLong does not escape complete(); it comes out as
# GenerationError with the helper's original message.
def test_generator_reraises_long_delay_as_generation_error():
    reply = json.dumps({"error": {"details": [{"retryDelay": "3600s"}]}})
    with pytest.raises(RetryDelayTooLong) as helper_error:
        wait_to_retry(1, reply, lambda seconds: None)

    with pytest.raises(GenerationError) as raised:
        generator_for(lambda request: httpx.Response(429, text=reply)).complete("prompt text")
    assert type(raised.value) is GenerationError
    assert str(raised.value) == str(helper_error.value)


# Extra (Claude): other HTTP errors are not retried; replies without an answer (e.g. blocked prompts) raise.
def test_extra_generator_errors():
    calls = []

    def bad_request(request):
        calls.append(1)
        return httpx.Response(400, text="bad request")

    with pytest.raises(GenerationError, match="400"):
        generator_for(bad_request).complete("prompt text")
    assert len(calls) == 1

    def blocked(request):
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}, "modelVersion": "gemini-3.6-flash"})

    with pytest.raises(GenerationError, match="SAFETY"):
        generator_for(blocked).complete("prompt text")


def gemini_key():
    return os.environ.get("GEMINI_API_KEY") or api.ENV_FILE.get("GEMINI_API_KEY")


# 8. Live (marker "live"; run with `uv run pytest -m live`): ask an OPT question through /query
# against the corpus already ingested locally; the answer cites at least one [n], and every
# source citation_key exists in the database. Skips until scripts/ingest.py has run.
@pytest.mark.live
@pytest.mark.skipif(not gemini_key(), reason="GEMINI_API_KEY is not set")
def test_08_live_opt_question(env, monkeypatch):
    with connect(env["DATABASE_URL"]) as conn:
        if conn.execute("select count(*) from chunks").fetchone()[0] < CORPUS_CHUNKS:
            pytest.skip("run scripts/ingest.py first")
        stored = {key for (key,) in conn.execute("select citation_key from chunks").fetchall()}
    monkeypatch.setenv("DATABASE_URL", env["DATABASE_URL"])

    response = TestClient(api.app).post("/query", json={"question": QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert re.search(r"\[\d+\]", body["answer"])
    assert body["sources"]
    assert all(source["citation_key"] in stored for source in body["sources"])
