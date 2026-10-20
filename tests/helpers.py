"""Plain helpers for tests: synthetic vectors, row inserts, and a fake embedder."""

import hashlib
import itertools
import math

EMBEDDING_DIMS = 768
_source_ids = itertools.count(1)


def vector_literal(values) -> str:
    """Format floats as pgvector text input, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def unit_vector(position: int, dims: int = EMBEDDING_DIMS) -> list[float]:
    values = [0.0] * dims
    values[position] = 1.0
    return values


def insert_document(
    db, source_tier="ecfr", version_date="2026-10-01", url="https://example.test/doc", source_id=None
):
    source_id = source_id or f"test-doc-{next(_source_ids)}"
    return db.execute(
        """
        insert into documents (source_id, source_tier, title, url, version_date)
        values (%s, %s, 'Test document', %s, %s)
        returning id
        """,
        (source_id, source_tier, url, version_date),
    ).fetchone()[0]


def insert_chunk(db, document_id, embedding, citation_key="214.2(f)(1)", chunk_index=0):
    return db.execute(
        """
        insert into chunks (document_id, citation_key, chunk_index, content, embedding)
        values (%s, %s, %s, 'Test chunk text', %s::vector)
        returning id
        """,
        (document_id, citation_key, chunk_index, vector_literal(embedding)),
    ).fetchone()[0]


def chunk_count(db, document_id) -> int:
    return db.execute(
        "select count(*) from chunks where document_id = %s", (document_id,)
    ).fetchone()[0]


class FakeEmbedder:
    """Stands in for Gemini: deterministic unit vectors derived from each text.

    `fail_if(text)` returning True for any text in a call raises, like a Gemini
    error on that document. `calls` counts embed() calls.
    """

    def __init__(self, fail_if=None):
        self.fail_if = fail_if
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail_if and any(self.fail_if(text) for text in texts):
            raise RuntimeError("fake Gemini error")
        return [fake_vector(text) for text in texts]


def fake_vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode()).digest()
    values = [(seed[i % len(seed)] + i) % 97 - 48.0 for i in range(EMBEDDING_DIMS)]
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]
