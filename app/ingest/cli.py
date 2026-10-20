"""Ingest CLI: chunk the committed raw corpus, run the quality gate, embed, write to Postgres.

Every run checks raw file hashes against the manifest, chunks data/raw/, checks
the chunks, and writes a JSON chunk report. If the gate finds a problem the run
stops before any Gemini call or database write. A real run
then embeds and writes one document at a time; a failed document keeps its old
rows, the rest still update, and the exit code is non-zero.

Usage:
  uv run python scripts/ingest.py --dry-run           # no Gemini, no database
  uv run python scripts/ingest.py                     # local Supabase (URL from `supabase status`)
  uv run python scripts/ingest.py --target opt-rag    # DATABASE_URL from .env

GEMINI_API_KEY and DATABASE_URL are read from .env and never printed.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

from app.embedding import GeminiEmbedder
from app.ingest import chunking
from app.ingest.chunking import MAX_TOKENS, Document, count_tokens
from app.ingest.store import write_document

ROOT = Path(__file__).resolve().parents[2]
PREVIEW_CHARS = 200


def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunk, embed, and store the raw corpus.")
    parser.add_argument("--dry-run", action="store_true", help="chunk and check only")
    parser.add_argument("--target", choices=("local", "opt-rag"), default="local")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "chunk_report.json")
    return parser.parse_args(argv)


def env_value(name: str) -> str:
    value = dotenv_values(ROOT / ".env").get(name)
    if not value:
        raise SystemExit(f"{name} is not set in .env")
    return value


def database_url(target: str) -> str:
    if target == "opt-rag":
        return env_value("DATABASE_URL")
    result = subprocess.run(
        ["supabase", "status", "-o", "env"], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit("supabase status failed; is the local stack running (`supabase start`)?")
    for line in result.stdout.splitlines():
        if line.startswith("DB_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("supabase status did not report DB_URL")


def build_report(documents: list[Document], problems: list[str]) -> dict:
    report_docs = []
    for doc in documents:
        tokens = [count_tokens(c.content) for c in doc.chunks]
        chars = [len(c.content) for c in doc.chunks]
        report_docs.append({
            "source_id": doc.source_id,
            "source_tier": doc.source_tier,
            "title": doc.title,
            "version_date": doc.version_date.isoformat(),
            "chunk_count": len(doc.chunks),
            "min_tokens": min(tokens, default=None),
            "max_tokens": max(tokens, default=None),
            "min_chars": min(chars, default=None),
            "max_chars": max(chars, default=None),
            "citation_keys": list(dict.fromkeys(c.citation_key for c in doc.chunks)),
            "chunks": [
                {
                    "citation_key": c.citation_key,
                    "chunk_index": c.chunk_index,
                    "tokens": n,
                    "header": c.header,
                    "preview": f"{c.header}\n{c.content[:PREVIEW_CHARS]}",
                }
                for c, n in zip(doc.chunks, tokens)
            ],
        })
    return {
        "token_limit": MAX_TOKENS,
        "document_count": len(documents),
        "chunk_count": sum(len(d.chunks) for d in documents),
        "problems": problems,
        "documents": report_docs,
    }


def main(argv=None, embedder=None) -> int:
    """Run the CLI; returns the exit code. Tests pass a fake embedder."""
    args = parse_args(argv)
    # A raw file that doesn't match the manifest is not the frozen corpus: don't even chunk it.
    problems = chunking.check_raw_hashes(args.raw_dir)
    documents = [] if problems else chunking.load_documents(args.raw_dir)
    problems += chunking.check_chunks(documents)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(build_report(documents, problems), indent=2) + "\n")
    for doc in documents:
        tokens = [count_tokens(c.content) for c in doc.chunks] or [0]
        print(f"{doc.source_id}: {len(doc.chunks)} chunks, {min(tokens)}-{max(tokens)} tokens")
    print(f"chunk report: {args.report}")

    if problems:
        for problem in problems:
            print(f"GATE {problem}", file=sys.stderr)
        print(f"quality gate failed ({len(problems)} problems); nothing embedded or written", file=sys.stderr)
        return 1
    if args.dry_run:
        print("dry run: quality gate passed; no Gemini calls, no database writes")
        return 0

    conninfo = database_url(args.target)
    print(f"target: {args.target} (host {conninfo_to_dict(conninfo).get('host')})")
    embedder = embedder or GeminiEmbedder(env_value("GEMINI_API_KEY"))

    started = time.monotonic()
    failed = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        for doc in documents:
            try:
                vectors = embedder.embed([c.embed_text for c in doc.chunks])
                write_document(conn, doc, vectors)
            except Exception as exc:  # one bad document must not stop the others
                failed.append(doc.source_id)
                print(f"FAILED {doc.source_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            print(f"written {doc.source_id}: {len(doc.chunks)} chunks")

    elapsed = time.monotonic() - started
    written = len(documents) - len(failed)
    print(f"{written}/{len(documents)} documents written in {elapsed:.1f} s")
    if failed:
        print(f"failed, left unchanged: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0
