"""FastAPI app: /health, and /query (retrieve top-k chunks, then generate a cited answer).

Settings come from the process environment, then .env. DATABASE_URL is the
exception: in .env it points at OPT-RAG, so the server reads it from the process
environment only.
"""

import os
from functools import cache
from pathlib import Path
from typing import Annotated

from dotenv import dotenv_values
from fastapi import Depends, FastAPI
from pydantic import BaseModel, StringConstraints

from app.db import connect
from app.generation import DISCLAIMER, REFUSAL, GeminiGenerator, generate, label
from app.retrieval import Hit, query_embedder, retrieve

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = dotenv_values(ROOT / ".env")

app = FastAPI(title="opt-rag")


def setting(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if value is None and name != "DATABASE_URL":
        value = ENV_FILE.get(name)
    value = value or default
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def get_conn():
    with connect(setting("DATABASE_URL"), autocommit=True) as conn:
        yield conn


@cache
def get_embedder():
    return query_embedder(setting("GEMINI_API_KEY"))


@cache
def get_generator():
    return GeminiGenerator(
        setting("GEMINI_API_KEY"),
        model=setting("GEMINI_GENERATION_MODEL"),
        temperature=float(setting("GEMINI_TEMPERATURE", "0")),
    )


def source_url(chunk: Hit) -> str:
    """eCFR sources link to the paragraph anchor on the dated page; Study in the States to the page."""
    if chunk.source_tier == "ecfr":
        return f"{chunk.url}#p-{chunk.citation_key}"
    return chunk.url


Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class QueryRequest(BaseModel):
    question: Question


class Source(BaseModel):
    label: str
    citation_key: str
    title: str
    source_tier: str
    url: str
    distance: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query")
def query(
    request: QueryRequest,
    conn=Depends(get_conn),
    embedder=Depends(get_embedder),
    generator=Depends(get_generator),
) -> QueryResponse:
    chunks = retrieve(request.question, int(setting("RETRIEVAL_TOP_K", "5")), conn=conn, embedder=embedder)
    if not chunks:
        # Nothing to cite: refuse without spending a generation call.
        return QueryResponse(answer=f"{REFUSAL}\n\n{DISCLAIMER}", sources=[])
    return QueryResponse(
        answer=generate(request.question, chunks, generator=generator),
        sources=[
            Source(
                label=label(n, c),
                citation_key=c.citation_key,
                title=c.title,
                source_tier=c.source_tier,
                url=source_url(c),
                distance=c.distance,
            )
            for n, c in enumerate(chunks, 1)
        ],
    )
