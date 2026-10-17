"""Shared fixtures for schema tests: target selection, fresh local database, connections.

`--target local` (default) reads .env.test, resets the local Supabase stack so every
migration is applied to an empty database, and allows direct Postgres access.
`--target opt-rag` reads .env and only runs tests that go through the Data API.
"""

import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
ENV_FILES = {"local": ROOT / ".env.test", "opt-rag": ROOT / ".env"}
EMBEDDING_DIMS = 768


def pytest_addoption(parser):
    parser.addoption("--target", choices=sorted(ENV_FILES), default="local")


def read_env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def vector_literal(values) -> str:
    """Format floats as pgvector text input, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


@pytest.fixture(scope="session")
def target(request) -> str:
    return request.config.getoption("--target")


@pytest.fixture(scope="session")
def env(target) -> dict[str, str]:
    return read_env_file(ENV_FILES[target])


def wait_for_data_api(env: dict[str, str], timeout: float = 30.0) -> None:
    # The REST service restarts after a reset; wait until it answers again.
    deadline = time.monotonic() + timeout
    while True:
        try:
            response = httpx.get(
                f"{env['SUPABASE_URL']}/rest/v1/",
                headers={"apikey": env["SUPABASE_SECRET_KEY"]},
            )
            if response.status_code < 500:
                return
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("Data API did not come back after supabase db reset")
        time.sleep(1)


@pytest.fixture(scope="session", autouse=True)
def fresh_database(target, env):
    """Local only: drop everything and re-apply supabase/migrations to an empty database."""
    if target != "local":
        return
    result = subprocess.run(
        ["supabase", "db", "reset"], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.exit(f"supabase db reset failed:\n{result.stdout}\n{result.stderr}")
    wait_for_data_api(env)


@pytest.fixture
def db(target, env):
    """Direct Postgres connection; everything a test writes is rolled back."""
    if target != "local":
        pytest.skip("direct database access only runs against the local stack")
    with psycopg.connect(env["DATABASE_URL"]) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def insert_document(db):
    def insert(source_tier="ecfr", version_date="2026-10-01", url="https://example.test/doc"):
        return db.execute(
            """
            insert into documents (source_tier, title, url, version_date)
            values (%s, 'Test document', %s, %s)
            returning id
            """,
            (source_tier, url, version_date),
        ).fetchone()[0]

    return insert


@pytest.fixture
def insert_chunk(db):
    def insert(document_id, embedding, citation_key="214.2(f)(1)", chunk_index=0):
        return db.execute(
            """
            insert into chunks (document_id, citation_key, chunk_index, content, embedding)
            values (%s, %s, %s, 'Test chunk text', %s::vector)
            returning id
            """,
            (document_id, citation_key, chunk_index, vector_literal(embedding)),
        ).fetchone()[0]

    return insert
