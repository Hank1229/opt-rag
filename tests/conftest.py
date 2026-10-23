"""Shared fixtures for tests: fresh local database, connections, corpus copies.

Tests run against local Supabase only. URL and keys come from
`supabase status -o env`, and the stack is reset so every migration is applied
to an empty database. `--target opt-rag` was retired in step 07 and exits
without running anything (DECISIONS.md, "Cloud mode for test 8 retired").
"""

import shutil
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

from app.db import connect

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
TARGETS = ("local", "opt-rag")
# `supabase status -o env` name -> the .env name the tests use.
STATUS_KEYS = {
    "DB_URL": "DATABASE_URL",
    "API_URL": "SUPABASE_URL",
    "PUBLISHABLE_KEY": "SUPABASE_PUBLISHABLE_KEY",
    "SECRET_KEY": "SUPABASE_SECRET_KEY",
}


def pytest_addoption(parser):
    parser.addoption("--target", choices=TARGETS, default="local")


def pytest_configure(config):
    if config.getoption("--target") == "opt-rag":
        pytest.exit(
            "--target opt-rag is retired: tests run against local Supabase only. "
            'See DECISIONS.md, Step 07, "Cloud mode for test 8 retired".',
            returncode=2,
        )


def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def read_local_status() -> dict[str, str]:
    """URL and keys of the running local stack, renamed to match .env."""
    result = subprocess.run(
        ["supabase", "status", "-o", "env"], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.exit(f"supabase status failed (is `supabase start` running?):\n{result.stderr}")
    status = parse_env(result.stdout)
    return {ours: status[theirs] for theirs, ours in STATUS_KEYS.items()}


@pytest.fixture(scope="session")
def env(request) -> dict[str, str]:
    """Local stack URL and keys. The first test that asks for them resets the database, so tests
    that only read files never need Supabase. No reset for `-m live`: the live test reads the
    corpus already ingested locally.
    """
    status = read_local_status()
    if request.config.getoption("markexpr") != "live":
        reset_database(status)
    return status


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


def reset_database(env: dict[str, str]) -> None:
    """Drop everything and re-apply supabase/migrations to an empty database."""
    result = subprocess.run(
        ["supabase", "db", "reset"], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.exit(f"supabase db reset failed:\n{result.stdout}\n{result.stderr}")
    wait_for_data_api(env)


@pytest.fixture
def db(env):
    """Direct Postgres connection; everything a test writes is rolled back."""
    with psycopg.connect(env["DATABASE_URL"]) as conn:
        yield conn
        conn.rollback()


def empty_tables(conn) -> None:
    conn.execute("truncate documents, chunks restart identity cascade")


@pytest.fixture
def ingest_db(env):
    """Autocommit connection for ingest tests, which commit: tables emptied before and after."""
    with psycopg.connect(env["DATABASE_URL"], autocommit=True) as conn:
        empty_tables(conn)
        yield conn
        empty_tables(conn)


@pytest.fixture
def app_db(env):
    """Connection opened the way the app opens it, on empty tables; everything is rolled back."""
    with connect(env["DATABASE_URL"]) as conn:
        empty_tables(conn)
        yield conn
        conn.rollback()


@pytest.fixture
def raw_copy(tmp_path) -> Path:
    """Copy of data/raw/ that a test may edit; the committed corpus is never touched."""
    return shutil.copytree(RAW_DIR, tmp_path / "raw")

