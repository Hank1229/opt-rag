"""Eval runner: answer each gold item per arm and run, score it, append it to raw.jsonl.

One line per (arm, run, qid) is written as soon as the item is scored, and a restart skips
lines already present. Pair stability is judged once both members of a pair exist for an
(arm, run) and goes to pairs.jsonl. The first failure is written to failures.jsonl and
re-raised, so a run never continues past an error it did not expect.

The bare arm has its own prompt (no sources, answers from model knowledge); opt-rag uses the
/query prompt. Each arm's prompt hash covers its rendered prompt template (placeholder question
and one source per tier, so both label formats count) and both judge prompts. prompts.json holds
those texts and hashes, the models and generation settings, the gold file hash, and the git state
of each invocation; each row carries its arm's prompt hash and the models and settings. A run id
is never resumed under another prompt, model setting, gold hash or metric_version. Each gold
reference is decomposed into claims once per qid and reference text, cached in
reference_claims.jsonl, and shared by both arms and all runs.
"""

import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from app.evals.metrics import (
    METRIC_VERSION,
    bare_citations,
    citation_accuracy,
    hit_at_k,
    rag_citations,
    reciprocal_rank,
    strip_disclaimer,
    unknown_keys,
)
from app.evals.judge import PAIR_PROMPT, REFUSAL_PROMPT
from app.generation import DISCLAIMER, INSTRUCTIONS, build_prompt, generate
from app.retrieval import Hit

ARMS = ("opt-rag", "bare")
BARE_INSTRUCTIONS = f"""You answer questions about F-1 student status and OPT from your knowledge of 8 CFR 214.2(f).

Rules:
- Cite the paragraph you rely on, in the form "8 CFR 214.2(f)(...)".
- If you are not sure of the answer, say so and tell the student to ask their Designated School Official (DSO).
- Answer in English, whatever language the question is in.
- End every reply with this line, word for word: {DISCLAIMER}"""
PROMPTS = {"opt-rag": INSTRUCTIONS, "bare": BARE_INSTRUCTIONS}
PLACEHOLDER_HITS = [
    Hit(1, "<citation_key>", "<title>", "ecfr", "<url>", "<content>", 0.0),
    Hit(2, "<citation_key>", "<title>", "<tier 2>", "<url>", "<content>", 0.0),
]
API_KEY = re.compile(r"\bsk-[\w*-]+|\bAIza[\w-]+")

log = logging.getLogger(__name__)


class RateLimit:
    """At most `calls` per `period` seconds, over a sliding window."""

    def __init__(self, calls: int, period: float, clock=time.monotonic, sleep=time.sleep):
        self.calls = calls
        self.period = period
        self.clock = clock
        self.sleep = sleep
        self.times = deque()

    def wait(self) -> None:
        now = self.clock()
        while self.times and now - self.times[0] >= self.period:
            self.times.popleft()
        if len(self.times) >= self.calls:
            self.sleep(self.period - (now - self.times.popleft()))
            now = self.clock()
        self.times.append(now)


def read_jsonl(path: Path) -> list[dict]:
    """Rows of a JSONL file. A line that is not whole JSON (cut off by an interrupted run) is
    skipped with a warning, as in app/embedding.py load_cache; its item is then redone."""
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            log.warning("%s: skipping bad line %d", path, number)
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("ab+") as out:
        # Finish a line cut off by an interrupted run, so it doesn't swallow this row.
        end = out.seek(0, os.SEEK_END)
        if end:
            out.seek(end - 1)
            if out.read(1) != b"\n":
                out.write(b"\n")
        out.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def score(item: dict, arm: str, answer: str, hits: list, *, known: dict[str, str], judge, claims: list[str] | None) -> dict:
    """Judge outputs and metric values for one answer. Refuse items get the refusal judge only.
    Ragas sees the answer without the disclaimer; the refusal judge sees it whole."""
    refusal = judge.refusal(item["question"], answer)
    if arm == "opt-rag":
        cited = rag_citations(answer, [h.citation_key for h in hits])
    else:
        cited = bare_citations(answer)
    stripped, disclaimer_stripped = strip_disclaimer(answer)
    scored = {
        "cited_keys": cited,
        "unknown_keys": unknown_keys(cited, known),
        "disclaimer_stripped": disclaimer_stripped,
        "judge": {"refusal": refusal},
        "metrics": {"refused": refusal["refused"], "refusal_verdict": refusal["verdict"]},
    }
    if item["expected"] == "refuse":
        return scored

    gold, reference = item["citation_keys"], item["reference_answer"]
    metrics = scored["metrics"]
    if arm == "opt-rag":
        retrieved = [h.citation_key for h in hits]
        contexts = [h.content for h in hits]
        metrics["hit_at_5"] = hit_at_k(retrieved, gold)
        metrics["mrr"] = reciprocal_rank(retrieved, gold)
        metrics["faithfulness"] = judge.faithfulness(item["question"], stripped, contexts)
        metrics["context_recall"] = judge.context_recall(item["question"], contexts, reference, [known[k] for k in gold])
    metrics["citation_accuracy"] = citation_accuracy(cited, gold)
    correctness = judge.answer_correctness(stripped, claims)
    metrics["answer_correctness"] = correctness["score"]
    scored["judge"]["answer_correctness"] = {"reference_claims": claims, "verdicts": correctness["verdicts"]}
    return scored


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bare_prompt(question: str) -> str:
    return f"{BARE_INSTRUCTIONS}\n\nQuestion: {question}"


def arm_prompts(arm: str) -> dict:
    """Every prompt text behind an arm's rows, and their hash."""
    template = bare_prompt("<question>") if arm == "bare" else build_prompt("<question>", PLACEHOLDER_HITS)
    texts = {"instructions": PROMPTS[arm], "template": template, "refusal_judge": REFUSAL_PROMPT, "pair_judge": PAIR_PROMPT}
    return {"sha256": sha256(json.dumps(texts, sort_keys=True)), **texts}


def record_provenance(out: Path, arms: list[str], git: dict, models: dict, gold_sha256: str) -> None:
    """Write each arm's prompts, the models and settings, the gold hash and the git state to
    prompts.json; a resumed run id must not change any but the git state. A git state different
    from the last one recorded is appended."""
    path = out / "prompts.json"
    prompts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    states = prompts.setdefault("git", [])
    if not states or states[-1] != git:
        states.append(git)
    for key, current in (("gold_sha256", gold_sha256), ("models", models)):
        if prompts.setdefault(key, current) != current:
            raise RuntimeError(f"{key} changed since run id {out.name} started; use a new run id")
    for arm in arms:
        current = arm_prompts(arm)
        if prompts.setdefault(arm, current) != current:
            raise RuntimeError(f"{arm} prompt changed since run id {out.name} started; use a new run id")
    path.write_text(json.dumps(prompts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_metric_version(out: Path, rows: dict) -> None:
    versions = sorted({str(r.get("metric_version")) for r in rows.values()} - {METRIC_VERSION})
    if versions:
        raise RuntimeError(f"rows in {out} have metric_version {', '.join(versions)}, not {METRIC_VERSION}; use a new run id")


def reference_claims(item: dict, out: Path, judge, cache: dict) -> list[str]:
    """Claims of the item's reference answer, decomposed on first use and cached in the run dir."""
    key = (item["qid"], sha256(item["reference_answer"]))
    if key not in cache:
        cache[key] = judge.decompose(item["reference_answer"])
        append_jsonl(out / "reference_claims.jsonl", {"qid": key[0], "reference_sha256": key[1], "claims": cache[key]})
    return cache[key]


def answer_item(item: dict, arm: str, *, retrieve, generator, limiter) -> tuple[str, list]:
    if arm == "bare":
        limiter.wait()
        return generator.complete(bare_prompt(item["question"])), []
    hits = retrieve(item["question"])
    limiter.wait()
    return generate(item["question"], hits, generator=generator), hits


def judge_pairs(items: list[dict], arm: str, run_no: int, rows: dict, out: Path, judge, models: dict) -> None:
    """Pair stability for every pair whose two answers exist in this (arm, run) and is not judged yet."""
    judged = {(p["arm"], p["run"], p["pair_id"]) for p in read_jsonl(out / "pairs.jsonl")}
    for pair_id in sorted({i["pair_id"] for i in items if i["pair_id"]}):
        members = {i["category"]: rows.get((arm, run_no, i["qid"])) for i in items if i["pair_id"] == pair_id}
        neutral, leading = members.get("Paired neutral"), members.get("Paired leading")
        if (arm, run_no, pair_id) in judged or not (neutral and leading):
            continue
        try:
            verdict = judge.pair((neutral["question"], neutral["answer"]), (leading["question"], leading["answer"]))
        except Exception as exc:
            record_failure(out, arm, run_no, pair_id, exc)
            raise
        append_jsonl(out / "pairs.jsonl", {
            "arm": arm, "run": run_no, "pair_id": pair_id, "qids": [neutral["qid"], leading["qid"]],
            "same": verdict["same"], "judge": verdict, "judge_model": models["judge_model"], "timestamp": now(),
        })


def record_failure(out: Path, arm: str, run_no: int, qid: str, exc: Exception) -> None:
    """The exception type and its message with anything shaped like an OpenAI or Gemini key masked."""
    append_jsonl(out / "failures.jsonl", {
        "arm": arm, "run": run_no, "qid": qid, "error_type": type(exc).__name__,
        "error": API_KEY.sub("<redacted>", str(exc)), "timestamp": now(),
    })


def run(items: list[dict], arms: list[str], runs: int, out: Path, *, retrieve, generator, judge,
        known: dict[str, str], models: dict, limiter, git: dict, gold_sha256: str) -> None:
    """Answer and score every (arm, run, item) not already in out/raw.jsonl."""
    out.mkdir(parents=True, exist_ok=True)
    rows = {(r["arm"], r["run"], r["qid"]): r for r in read_jsonl(out / "raw.jsonl")}
    check_metric_version(out, rows)
    record_provenance(out, arms, git, models, gold_sha256)
    prompt_hashes = {arm: arm_prompts(arm)["sha256"] for arm in arms}
    claim_cache = {(c["qid"], c["reference_sha256"]): c["claims"] for c in read_jsonl(out / "reference_claims.jsonl")}
    for arm in arms:
        for run_no in range(1, runs + 1):
            for item in items:
                key = (arm, run_no, item["qid"])
                if key in rows:
                    continue
                try:
                    answer, hits = answer_item(item, arm, retrieve=retrieve, generator=generator, limiter=limiter)
                    item_claims = reference_claims(item, out, judge, claim_cache) if item["expected"] == "answer" else None
                    scored = score(item, arm, answer, hits, known=known, judge=judge, claims=item_claims)
                except Exception as exc:
                    record_failure(out, arm, run_no, item["qid"], exc)
                    raise
                row = {
                    "arm": arm, "run": run_no, "qid": item["qid"], "expected": item["expected"],
                    "category": item["category"], "pair_id": item["pair_id"],
                    "question": item["question"], "answer": answer,
                    "gold_keys": item["citation_keys"],
                    "retrieved": [{"citation_key": h.citation_key, "chunk_id": h.id, "distance": h.distance} for h in hits],
                    "reference_contexts": [known[k] for k in item["citation_keys"]],
                    **scored, **models, "prompt_sha256": prompt_hashes[arm],
                    "metric_version": METRIC_VERSION, "timestamp": now(),
                }
                append_jsonl(out / "raw.jsonl", row)
                rows[key] = row
            judge_pairs(items, arm, run_no, rows, out, judge, models)
