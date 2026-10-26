"""Eval CLI: run the step 10 baseline (opt-rag vs bare Gemini) against local Supabase, or summarize a run.

Usage:
  uv run --group eval python scripts/eval.py run --arm both --runs 3 --run-id baseline
  uv run --group eval python scripts/eval.py run --arm both --runs 1 --qids Q1 Q2 Q3 Q12 P01-N P01-L --run-id smoke
  uv run --group eval python scripts/eval.py summary --run-id smoke

Everything for a run lives in evals/results/<run_id>/: raw.jsonl, pairs.jsonl, failures.jsonl,
prompts.json, reference_claims.jsonl, query_embeddings.jsonl and summary.md. Generation uses the same generator settings as /query.
GEMINI_API_KEY and OPENAI_API_KEY come from the environment or .env and are never printed.
A run stops before any API call unless evals/gold_v1.jsonl matches the sha256 frozen in evals/README.md.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from app.db import connect
from app.embedding import DIMENSIONS
from app.embedding import MODEL as EMBEDDING_MODEL
from app.evals.judge import JUDGE_MODEL, Judge
from app.evals.metrics import TOP_K
from app.evals.runner import ARMS, RateLimit, read_jsonl, run
from app.evals.summary import summarize
from app.gold import EVALS_README, GOLD, ROOT, read_drafts
from app.ingest.cli import database_url
from app.retrieval import query_embedder, retrieve

RESULTS = ROOT / "evals" / "results"
FROZEN_SHA256 = re.compile(r"sha256: `([0-9a-f]{64})`")
GENERATION_CALLS_PER_MINUTE = 5
CHUNK_TEXTS = """
    select citation_key, string_agg(content, E'\n\n' order by document_id, chunk_index)
    from chunks group by citation_key
"""


def run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise argparse.ArgumentTypeError("use letters, digits, '.', '_' or '-'")
    return value


def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 10 eval: opt-rag vs bare Gemini.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run", help="answer and score gold items; resumes an existing run id")
    run_cmd.add_argument("--arm", choices=(*ARMS, "both"), default="both")
    run_cmd.add_argument("--runs", type=int, default=3)
    run_cmd.add_argument("--qids", nargs="+", help="these gold items only, in gold order")
    run_cmd.add_argument("--limit", type=int, help="first N gold items only (after --qids)")
    run_cmd.add_argument("--run-id", type=run_id, required=True)
    summary_cmd = commands.add_parser("summary", help="write summary.md for a run id")
    summary_cmd.add_argument("--run-id", type=run_id, required=True)
    return parser.parse_args(argv)


def git_state(root: Path = ROOT) -> dict:
    """HEAD sha and whether the tree differs from it; eval results themselves do not count."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout
    changes = git("status", "--porcelain", "--", ".", ":(exclude)evals/results")
    return {"head": git("rev-parse", "HEAD").strip(), "dirty": bool(changes.strip())}


def frozen_gold_sha256(gold: Path, readme: Path) -> str:
    """sha256 of the gold file; stops the run when it differs from the hash recorded in the README."""
    actual = hashlib.sha256(gold.read_bytes()).hexdigest()
    recorded = FROZEN_SHA256.search(readme.read_text(encoding="utf-8")).group(1)
    if actual != recorded:
        raise SystemExit(
            f"{gold.name} sha256 {actual} differs from the frozen {recorded} in {readme.name}; "
            "a changed gold set voids the baseline"
        )
    return actual


def run_models(generator) -> dict:
    """Models and generation settings, written to prompts.json and every row."""
    return {
        "generation_model": generator.model,
        "generation_temperature": generator.temperature,
        "top_k": TOP_K,
        "judge_model": JUDGE_MODEL,
        "embedding_model": f"{EMBEDDING_MODEL} ({DIMENSIONS} dims)",
    }


def select(items: list[dict], qids: list[str] | None, limit: int | None) -> list[dict]:
    if qids:
        unknown = sorted(set(qids) - {i["qid"] for i in items})
        if unknown:
            raise SystemExit(f"not in the gold set: {', '.join(unknown)}")
        items = [i for i in items if i["qid"] in qids]
    return items[:limit]


def run_eval(args: argparse.Namespace) -> None:
    gold_sha256 = frozen_gold_sha256(GOLD, EVALS_README)
    # Imported here so `summary` needs no API keys and no FastAPI app.
    from app.main import get_generator, setting

    out = RESULTS / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    items = select(read_drafts(GOLD), args.qids, args.limit)
    generator = get_generator()
    judge = Judge(setting("OPENAI_API_KEY"))
    embedder = query_embedder(setting("GEMINI_API_KEY"), cache=out / "query_embeddings.jsonl")
    with connect(database_url("local"), autocommit=True) as conn:
        known = dict(conn.execute(CHUNK_TEXTS).fetchall())
        if not known:
            raise SystemExit("the local chunks table is empty; run scripts/ingest.py first")
        run(
            items,
            list(ARMS) if args.arm == "both" else [args.arm],
            args.runs,
            out,
            retrieve=lambda question: retrieve(question, TOP_K, conn=conn, embedder=embedder),
            generator=generator,
            judge=judge,
            known=known,
            models=run_models(generator),
            limiter=RateLimit(GENERATION_CALLS_PER_MINUTE, 60),
            git=git_state(),
            gold_sha256=gold_sha256,
        )
    print(f"done: {out / 'raw.jsonl'}")


def write_summary(args: argparse.Namespace) -> None:
    out = RESULTS / args.run_id
    records = read_jsonl(out / "raw.jsonl")
    if not records:
        raise SystemExit(f"no results in {out}")
    prompts = out / "prompts.json"
    git = json.loads(prompts.read_text(encoding="utf-8"))["git"] if prompts.exists() else []
    path = out / "summary.md"
    path.write_text(
        f"# Eval summary: {args.run_id}\n\n" + summarize(records, read_jsonl(out / "pairs.jsonl"), git), encoding="utf-8"
    )
    print(f"wrote {path}")


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "run":
        run_eval(args)
    else:
        write_summary(args)
    return 0
