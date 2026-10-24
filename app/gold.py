"""Gold set v1: load the hand-written questions, drafts and frozen set, and check them.

Checks are deterministic (DECISIONS.md, 2026-10-22 "Gold set v1"): qids and pairs in
evals/questions_v1.csv, and for drafts, citation keys that exist in the local chunker output
and quotes that match its text verbatim (whitespace-normalized). A quote taken from more than
one place joins its fragments with QUOTE_GAP. Offline: reads evals/ and data/raw/ only.
"""

import csv
import json
import re
from collections import Counter
from pathlib import Path

from app.ingest.chunking import load_documents

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "evals" / "questions_v1.csv"
DRAFTS = ROOT / "evals" / "drafts" / "gold_v1_draft.jsonl"
GOLD = ROOT / "evals" / "gold_v1.jsonl"
EVALS_README = ROOT / "evals" / "README.md"
RAW_DIR = ROOT / "data" / "raw"
QUESTION_FIELDS = ("qid", "question", "category", "topic", "expected", "pair_id", "source", "original")
NOT_IN_CORPUS = "NOT_IN_CORPUS"
QUOTE_GAP = " [...] "
PAIR_ID = re.compile(r"P\d{2}")
PAIRED = {"Paired neutral", "Paired leading"}


def read_questions(path: Path = QUESTIONS) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_drafts(path: Path = DRAFTS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def problems(rows: list[dict[str, str]]) -> list[str]:
    """Every duplicate qid and malformed or unmatched pair, as readable messages."""
    found = [f"duplicate qid {qid}" for qid, n in Counter(r["qid"] for r in rows).items() if n > 1]
    pairs = {}
    for r in rows:
        qid, category, pair_id = r["qid"], r["category"], r["pair_id"]
        if not pair_id:
            if category in PAIRED:
                found.append(f"{qid}: {category} needs a pair_id")
            continue
        if category not in PAIRED:
            found.append(f"{qid}: {category} must not have a pair_id")
        if not PAIR_ID.fullmatch(pair_id):
            found.append(f"{qid}: pair_id {pair_id!r} is not P01..P99")
            continue
        if category in PAIRED and qid.split("-")[0] != pair_id:
            found.append(f"{qid}: qid prefix does not match pair_id {pair_id}")
        pairs.setdefault(pair_id, []).append(r)
    for pair_id, members in pairs.items():
        if sorted(m["category"] for m in members) != sorted(PAIRED):
            got = ", ".join(f"{m['qid']} {m['category']}" for m in members)
            found.append(f"{pair_id}: needs one Paired neutral and one Paired leading, got {got}")
    return found


def normalize(text: str) -> str:
    return " ".join(text.split())


def corpus_text(raw_dir: Path = RAW_DIR) -> dict[str, str]:
    """Normalized text per citation key, built by the chunker ingest uses; no embedding, no database."""
    parts = {}
    for doc in load_documents(raw_dir):
        for chunk in doc.chunks:
            parts.setdefault(chunk.citation_key, []).append(chunk.content)
    return {key: normalize(" ".join(texts)) for key, texts in parts.items()}


def draft_problems(drafts: list[dict], corpus: dict[str, str]) -> list[str]:
    """One message per broken rule; an empty list means the drafts may go to review."""
    found = []
    for d in drafts:
        qid, answer, keys, quote = d["qid"], d["reference_answer"], d["citation_keys"], d["source_quote"]
        if d["expected"] == "refuse":
            if answer or keys or quote:
                found.append(f"{qid}: refuse item must have no reference_answer, citation_keys or source_quote")
            continue
        if answer == NOT_IN_CORPUS:
            if keys or quote:
                found.append(f"{qid}: {NOT_IN_CORPUS} item must have no citation_keys or source_quote")
            continue
        if not answer:
            found.append(f"{qid}: no reference_answer")
        if not keys:
            found.append(f"{qid}: no citation_keys")
        found += [f"{qid}: citation_key {key!r} is not in the chunked corpus" for key in keys if key not in corpus]
        cited = [corpus[key] for key in keys if key in corpus]
        for fragment in map(normalize, quote.split(QUOTE_GAP)):
            if not fragment or not any(fragment in text for text in cited):
                found.append(f"{qid}: source_quote not found in the cited text: {fragment[:60]!r}")
    return found


def copy_problems(drafts: list[dict], questions: list[dict[str, str]], issue_date: str) -> list[str]:
    """Drafts must list every question in CSV order with the fields Hank wrote unchanged."""
    if len(drafts) != len(questions):
        return [f"draft count {len(drafts)} does not match question count {len(questions)}"]
    found = []
    for d, q in zip(drafts, questions):
        found += [f"{q['qid']}: {field} differs from questions_v1.csv" for field in QUESTION_FIELDS if d[field] != q[field]]
        if d["corpus_issue_date"] != issue_date:
            found.append(f"{q['qid']}: corpus_issue_date is not the manifest's {issue_date}")
    return found


def review_order(drafts: list[dict]) -> list[dict]:
    """Answer items for the review sheet: NOT_IN_CORPUS first, otherwise in file order."""
    answers = [d for d in drafts if d["expected"] == "answer"]
    return sorted(answers, key=lambda d: d["reference_answer"] != NOT_IN_CORPUS)
