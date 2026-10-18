"""Plain helpers for schema tests: synthetic vectors and row inserts on a psycopg connection."""

EMBEDDING_DIMS = 768


def vector_literal(values) -> str:
    """Format floats as pgvector text input, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def unit_vector(position: int, dims: int = EMBEDDING_DIMS) -> list[float]:
    values = [0.0] * dims
    values[position] = 1.0
    return values


def insert_document(db, source_tier="ecfr", version_date="2026-10-01", url="https://example.test/doc"):
    return db.execute(
        """
        insert into documents (source_tier, title, url, version_date)
        values (%s, 'Test document', %s, %s)
        returning id
        """,
        (source_tier, url, version_date),
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
