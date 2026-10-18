"""Shared fixtures for schema tests: target selection, fresh local database, connections.

`--target local` (default) reads URL and keys from `supabase status -o env`, resets
the local Supabase stack so every migration is applied to an empty database, and
allows direct Postgres access.
`--target opt-rag` reads .env and only runs tests that go through the Data API.
"""

import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
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
def target(request) -> str:
    return request.config.getoption("--target")


@pytest.fixture(scope="session")
def env(target) -> dict[str, str]:
    if target == "local":
        return read_local_status()
    return parse_env((ROOT / ".env").read_text())


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

