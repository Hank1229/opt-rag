"""Step 12 tests: the API starts with no settings at all, as a fresh container does.

app.main is reloaded with no .env file and no env vars, then /health must work and
/query must name the missing setting. Tests marked "extra" are edge cases added by Claude.
"""

import importlib

import dotenv
import pytest
from fastapi.testclient import TestClient

from app import main as api

SETTINGS = (
    "DATABASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_GENERATION_MODEL",
    "GEMINI_TEMPERATURE",
    "RETRIEVAL_TOP_K",
    "CORS_ALLOWED_ORIGINS",
)
QUESTION = {"question": "How long is the OPT unemployment limit?"}


@pytest.fixture
def bare_env(monkeypatch):
    """No settings in the process environment and no .env file; restores app.main afterwards."""
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *args, **kwargs: {})
    yield monkeypatch
    monkeypatch.undo()
    importlib.reload(api)


def test_health_is_200_with_no_settings(bare_env):
    client = TestClient(importlib.reload(api).app)
    assert client.get("/health").json() == {"status": "ok"}


def test_query_without_database_url_is_503_naming_it(bare_env):
    client = TestClient(importlib.reload(api).app)

    response = client.post("/query", json=QUESTION)

    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_URL is not set"}


# Extra (Claude): with the database reachable, the next missing setting is the Gemini key.
def test_extra_query_without_gemini_key_is_503_naming_it(bare_env, env):
    bare_env.setenv("DATABASE_URL", env["DATABASE_URL"])
    client = TestClient(importlib.reload(api).app)

    response = client.post("/query", json=QUESTION)

    assert response.status_code == 503
    assert response.json() == {"detail": "GEMINI_API_KEY is not set"}


# Extra (Claude): the 503 still carries CORS headers, so the browser can show the error.
def test_extra_503_has_cors_header_for_allowed_origin(bare_env):
    origin = "https://opt-rag.vercel.app"
    bare_env.setenv("CORS_ALLOWED_ORIGINS", origin)
    client = TestClient(importlib.reload(api).app)

    response = client.post("/query", json=QUESTION, headers={"Origin": origin})

    assert response.status_code == 503
    assert response.headers["access-control-allow-origin"] == origin
