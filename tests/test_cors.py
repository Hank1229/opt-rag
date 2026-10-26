"""Step 11 tests: CORS on the FastAPI app, origins from CORS_ALLOWED_ORIGINS.

Test 6 maps to Hank's expected result 6; tests marked "extra" are edge cases added
by Claude. The middleware reads the variable at import, so each test reloads app.main.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app import main as api

ALLOWED = "http://localhost:5173"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f"{ALLOWED}, https://opt-rag.example.app")
    yield TestClient(importlib.reload(api).app)
    monkeypatch.undo()
    importlib.reload(api)


def test_6_allowed_origin_gets_allow_origin_header(client):
    response = client.get("/health", headers={"Origin": ALLOWED})
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_6_unlisted_origin_gets_no_allow_origin_header(client):
    response = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers


def test_extra_origin_after_comma_and_space_is_allowed(client):
    origin = "https://opt-rag.example.app"
    response = client.get("/health", headers={"Origin": origin})
    assert response.headers["access-control-allow-origin"] == origin


def test_extra_preflight_for_json_post_to_query_is_allowed(client):
    # The browser sends this before a POST with Content-Type: application/json.
    response = client.options(
        "/query",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
