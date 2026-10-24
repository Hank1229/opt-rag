"""Top-k retrieval: embed the question as a query, then exact cosine search over all chunks."""

from dataclasses import dataclass
from pathlib import Path

import psycopg

from app.embedding import GeminiEmbedder
from app.ingest.store import vector_literal

SEARCH = """
    select c.id, c.citation_key, d.title, d.source_tier, d.url, c.content,
           c.embedding <=> %s::vector as distance
    from chunks c
    join documents d on d.id = c.document_id
    order by distance, c.id
    limit %s
"""


@dataclass(frozen=True)
class Hit:
    id: int
    citation_key: str
    title: str
    source_tier: str
    url: str  # documents.url, without a paragraph anchor
    content: str
    distance: float


def query_embedder(api_key: str, client=None, cache: Path | None = None) -> GeminiEmbedder:
    """Questions are embedded as RETRIEVAL_QUERY, without the contextual header chunks get."""
    return GeminiEmbedder(api_key, task_type="RETRIEVAL_QUERY", client=client, cache=cache)


def retrieve(question: str, k: int, *, conn: psycopg.Connection, embedder) -> list[Hit]:
    """The k chunks nearest to the question, nearest first."""
    [vector] = embedder.embed([question])
    rows = conn.execute(SEARCH, (vector_literal(vector), k)).fetchall()
    return [Hit(*row) for row in rows]
