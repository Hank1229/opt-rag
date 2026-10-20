"""Write one document and its chunks to Postgres in a single transaction.

Design: DECISIONS.md, Step 07 "Replacing a document's chunks". Readers see the
old document or the new one, never a mix and never zero chunks.
"""

import psycopg

from app.ingest.chunking import Document

UPSERT_DOCUMENT = """
    insert into documents (source_id, source_tier, title, url, version_date)
    values (%s, %s, %s, %s, %s)
    on conflict (source_id) do update
    set source_tier = excluded.source_tier,
        title = excluded.title,
        url = excluded.url,
        version_date = excluded.version_date
    returning id
"""
INSERT_CHUNK = """
    insert into chunks (document_id, citation_key, chunk_index, content, embedding)
    values (%s, %s, %s, %s, %s::extensions.vector)
"""


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def write_document(conn: psycopg.Connection, doc: Document, vectors: list[list[float]]) -> None:
    """Upsert the documents row and replace all of its chunks; all or nothing."""
    if len(vectors) != len(doc.chunks):
        raise ValueError(f"{len(doc.chunks)} chunks but {len(vectors)} vectors")
    with conn.transaction():
        document_id = conn.execute(
            UPSERT_DOCUMENT,
            (doc.source_id, doc.source_tier, doc.title, doc.url, doc.version_date),
        ).fetchone()[0]
        conn.execute("delete from chunks where document_id = %s", (document_id,))
        with conn.cursor() as cur:
            cur.executemany(
                INSERT_CHUNK,
                [
                    (document_id, c.citation_key, c.chunk_index, c.content, vector_literal(v))
                    for c, v in zip(doc.chunks, vectors)
                ],
            )
