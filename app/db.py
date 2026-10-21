"""Postgres connections shared by ingest and retrieval.

pgvector lives in the `extensions` schema (DECISIONS.md, Step 06), so every
connection puts it on the search path and SQL can use `vector` and `<=>` unqualified.
"""

import psycopg

SEARCH_PATH = "-c search_path=public,extensions"


def connect(conninfo: str, **kwargs) -> psycopg.Connection:
    return psycopg.connect(conninfo, options=SEARCH_PATH, **kwargs)
