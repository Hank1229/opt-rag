"""Postgres connections and the pgvector input format, shared by ingest and retrieval.

pgvector lives in the `extensions` schema (DECISIONS.md, Step 06), so every
connection puts it on the search path and SQL can use `vector` and `<=>` unqualified.
"""

import psycopg

SEARCH_PATH = "-c search_path=public,extensions"


def connect(conninfo: str, **kwargs) -> psycopg.Connection:
    return psycopg.connect(conninfo, options=SEARCH_PATH, **kwargs)


def vector_literal(values: list[float]) -> str:
    """Format floats as pgvector text input, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"
