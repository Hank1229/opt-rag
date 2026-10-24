"""Deterministic eval metrics: hit@k, MRR, citation parsing and accuracy (DECISIONS.md,
2026-10-23 "Step 10 judge model and custom metrics"), and the answer correctness score
over judge verdicts. No LLM, no network.
"""

import re

from app.generation import DISCLAIMER

TOP_K = 5
# Bump when any metric definition changes; every raw.jsonl row records it.
METRIC_VERSION = "step10-2026-10-24c"
ANSWER_CORRECTNESS_MODE = "reference-claim recall"
ANSWER_CORRECTNESS_LABEL = f"Answer correctness ({ANSWER_CORRECTNESS_MODE})"
LABEL = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# "8 CFR 214.2(f)(10)", "8 C.F.R. § 214.2(f)(11)(i)(B)(2)", "8 CFR §214.2 (f) (5)"
CFR_REFERENCE = re.compile(r"8\s*C\.?\s*F\.?\s*R\.?\s*(?:§+\s*)?(214\.2(?:\s*\([0-9A-Za-z]+\))*)", re.IGNORECASE)


def hit_at_k(retrieved: list[str], gold: list[str], k: int = TOP_K) -> int:
    return int(any(key in gold for key in retrieved[:k]))


def reciprocal_rank(retrieved: list[str], gold: list[str], k: int = TOP_K) -> float:
    for rank, key in enumerate(retrieved[:k], 1):
        if key in gold:
            return 1 / rank
    return 0.0


def unique(keys: list[str]) -> list[str]:
    return list(dict.fromkeys(keys))


def rag_citations(answer: str, sources: list[str]) -> list[str]:
    """Citation keys behind the [n] labels in an opt-rag answer, in first-cited order.
    A label past the last source has no key; it is kept as "[n]" so it counts as unknown."""
    labels = [int(n) for group in LABEL.findall(answer) for n in group.split(",")]
    return unique([sources[n - 1] if 1 <= n <= len(sources) else f"[{n}]" for n in labels])


def bare_citations(answer: str) -> list[str]:
    """8 CFR 214.2 references in a bare-Gemini answer, normalized to chunk citation keys."""
    return unique([re.sub(r"\s+", "", ref) for ref in CFR_REFERENCE.findall(answer)])


def citation_accuracy(cited: list[str], gold: list[str]) -> float:
    """Precision of the cited keys against gold; an answer with no citations scores 0."""
    if not cited:
        return 0.0
    return sum(key in gold for key in cited) / len(cited)


def unknown_keys(cited: list[str], known) -> list[str]:
    """Cited keys that are neither a chunk key nor an ancestor paragraph of one."""
    return [key for key in cited if key not in known and not any(k.startswith(key + "(") for k in known)]


def reference_claim_recall(verdicts: list[bool]) -> float | None:
    """Share of reference claims the answer supports; None when the reference yields no claims."""
    return sum(verdicts) / len(verdicts) if verdicts else None


def strip_disclaimer(answer: str) -> tuple[str, bool]:
    """Answer without the fixed disclaimer line, for Ragas inputs only, and whether it was there."""
    if DISCLAIMER not in answer:
        return answer, False
    return answer.replace(DISCLAIMER, "").strip(), True
