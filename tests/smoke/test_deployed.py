"""Step 12 smoke tests against a running server: Cloud Run, or the local Docker image.

Skipped unless SMOKE_BASE_URL is set, e.g.
`SMOKE_BASE_URL=http://localhost:8080 uv run pytest tests/smoke -v`.
The /query cases call real Gemini through the server: two generation calls per run.
The first request is timed and printed, as the cold-start number when the service
was scaled to zero.
"""

import json
import os
import re
import time
from pathlib import Path

import httpx
import pytest

from app.generation import DISCLAIMER, REFUSAL

BASE_URL = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="SMOKE_BASE_URL is not set")

GOLD = Path(__file__).resolve().parents[2] / "evals" / "gold_v1.jsonl"
ANSWER_QID = "Q1"  # single-fact; baseline-v1 answered it with citations in all 3 runs
REFUSE_QID = "Q26"  # out-of-scope (O-1A); baseline-v1 refused it in all 3 runs
ALLOWED_ORIGIN = "https://opt-rag.vercel.app"


def gold_question(qid: str) -> str:
    for line in GOLD.read_text().splitlines():
        item = json.loads(line)
        if item["qid"] == qid:
            return item["question"]
    raise KeyError(qid)


@pytest.fixture(scope="module")
def client():
    # Embedding and generation may each sleep up to 120 s on retries (app/embedding.py).
    with httpx.Client(base_url=BASE_URL, timeout=300) as client:
        yield client


@pytest.fixture(scope="module")
def first_health(client, pytestconfig):
    """GET /health as the module's first request, timed."""
    start = time.monotonic()
    response = client.get("/health")
    seconds = time.monotonic() - start
    reporter = pytestconfig.pluginmanager.get_plugin("terminalreporter")
    reporter.write_line(f"\nfirst request (GET /health): {seconds:.2f} s")
    return response


def ask(client, qid: str) -> httpx.Response:
    return client.post("/query", json={"question": gold_question(qid)})


def test_health_is_200(first_health):
    assert first_health.status_code == 200
    assert first_health.json() == {"status": "ok"}


def test_answerable_question_gets_cited_answer(first_health, client):
    response = ask(client, ANSWER_QID)

    assert response.status_code == 200
    body = response.json()
    assert body["answer"].strip()
    assert re.search(r"\[\d+\]", body["answer"])
    assert body["sources"]
    assert all("content" not in source for source in body["sources"])


def test_refusal_question_is_refused(first_health, client):
    response = ask(client, REFUSE_QID)

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert REFUSAL in answer
    assert "DSO" in answer
    assert DISCLAIMER in answer


def test_preflight_from_allowed_origin_is_allowed(first_health, client):
    response = client.options(
        "/query",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_unlisted_origin_gets_no_allow_origin_header(first_health, client):
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
