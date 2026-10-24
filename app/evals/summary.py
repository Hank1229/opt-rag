"""Eval summary: per-arm metric tables (mean, min, max over runs) and the worst answer items.

Rates are averaged over answer items within a run, then summarized across runs. Counts
(refusal verdicts, pairs, missing disclaimers) are x/n per run; their mean is the mean of each
run's x/n, and min and max are the runs with the lowest and highest share. Refuse items count
only toward the three refusal verdict rows; on answer items only REFUSED is a false refusal. A metric Ragas could not score (None) is left out of its run's mean;
the n column shows, per run, items scored out of answer items, so those gaps stay visible.
"""

import re
from collections import defaultdict

from app.evals.metrics import ANSWER_CORRECTNESS_LABEL

RATES = {
    "opt-rag": [
        (ANSWER_CORRECTNESS_LABEL, "answer_correctness"),
        ("Faithfulness", "faithfulness"),
        ("Context recall", "context_recall"),
        ("hit@5", "hit_at_5"),
        ("MRR", "mrr"),
        ("Citation accuracy", "citation_accuracy"),
    ],
    "bare": [
        (ANSWER_CORRECTNESS_LABEL, "answer_correctness"),
        ("Citation accuracy", "citation_accuracy"),
    ],
}
WORST = 5
SNIPPET_CHARS = 120


def mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def rate(rows: list[dict], name: str) -> float | None:
    return mean([r["metrics"].get(name) for r in rows if r["expected"] == "answer"])


def coverage(rows: list[dict], name: str) -> str:
    answers = [r for r in rows if r["expected"] == "answer"]
    return f"{sum(r['metrics'].get(name) is not None for r in answers)}/{len(answers)}"


def cited_count(rows: list[dict]) -> int:
    return sum(len(r["cited_keys"]) for r in rows if r["expected"] == "answer")


def unknown_rate(rows: list[dict]) -> float | None:
    """Unknown cited keys over all cited keys of a run's answer items."""
    cited = cited_count(rows)
    unknown = sum(len(r["unknown_keys"]) for r in rows if r["expected"] == "answer")
    return unknown / cited if cited else None


def false_refusals(rows: list[dict]) -> tuple[int, int]:
    answers = [r for r in rows if r["expected"] == "answer"]
    return sum(r["metrics"]["refused"] for r in answers), len(answers)


def refuse_verdicts(rows: list[dict], verdict: str) -> tuple[int, int]:
    refuse = [r for r in rows if r["expected"] == "refuse"]
    return sum(r["metrics"]["refusal_verdict"] == verdict for r in refuse), len(refuse)


def missing_disclaimers(rows: list[dict]) -> tuple[int, int]:
    answers = [r for r in rows if r["expected"] == "answer"]
    return sum(not r["disclaimer_stripped"] for r in answers), len(answers)


def rate_row(label: str, per_run: list, n: list[str]) -> str:
    values = [v for v in per_run if v is not None]
    if not values:
        return f"| {label} | n/a | n/a | n/a | {', '.join(n)} |"
    return f"| {label} | {mean(values):.3f} | {min(values):.3f} | {max(values):.3f} | {', '.join(n)} |"


def count_row(label: str, per_run: list[tuple[int, int]]) -> str:
    counted = [(x, n) for x, n in per_run if n]
    n = ", ".join(str(n) for _, n in per_run)
    if not counted:
        return f"| {label} | n/a | n/a | n/a | {n} |"
    low, high = min(counted, key=lambda c: c[0] / c[1]), max(counted, key=lambda c: c[0] / c[1])
    return f"| {label} | {mean([x / total for x, total in counted]):.3f} | {low[0]}/{low[1]} | {high[0]}/{high[1]} | {n} |"


def one_line(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 3] + "..."


def worst_items(rows: list[dict]) -> list[str]:
    """The lowest answer items by answer correctness averaged over runs, with their worst answer."""
    by_qid = defaultdict(list)
    for r in rows:
        if r["expected"] == "answer" and r["metrics"].get("answer_correctness") is not None:
            by_qid[r["qid"]].append(r)
    ranked = sorted(by_qid.items(), key=lambda kv: mean([r["metrics"]["answer_correctness"] for r in kv[1]]))
    lines = []
    for qid, group in ranked[:WORST]:
        lowest = min(group, key=lambda r: r["metrics"]["answer_correctness"])
        score = mean([r["metrics"]["answer_correctness"] for r in group])
        lines.append(f"- {qid} {score:.2f}: {one_line(lowest['question'])} Answer: {one_line(lowest['answer'])}")
    return lines


def arm_section(arm: str, rows: list[dict], pairs: list[dict]) -> list[str]:
    runs = sorted({r["run"] for r in rows})
    by_run = {n: [r for r in rows if r["run"] == n] for n in runs}
    lines = [
        f"## {arm}",
        "",
        f"Runs: {len(runs)}. Items scored per run: {', '.join(str(len(by_run[n])) for n in runs)}.",
        "",
        "n is per run: items scored out of answer items for rates, cited keys for the unknown citation rate, "
        "items or pairs judged for counts.",
        "",
        "| Metric | Mean | Min | Max | n |",
        "|---|---|---|---|---|",
    ]
    lines += [
        rate_row(label, [rate(by_run[n], name) for n in runs], [coverage(by_run[n], name) for n in runs])
        for label, name in RATES[arm]
    ]
    lines.append(rate_row(
        "Unknown citation rate", [unknown_rate(by_run[n]) for n in runs], [f"{cited_count(by_run[n])} keys" for n in runs]
    ))
    lines += [
        count_row(f"Refuse items judged {verdict}", [refuse_verdicts(by_run[n], verdict) for n in runs])
        for verdict in ("REFUSED", "PARTIAL", "ANSWERED")
    ]
    lines.append(count_row("False refusal rate, answer items", [false_refusals(by_run[n]) for n in runs]))
    pair_runs = [[p for p in pairs if p["run"] == n] for n in runs]
    lines.append(count_row("Pair stability", [(sum(p["same"] for p in group), len(group)) for group in pair_runs]))
    lines.append(count_row("Answer items without the disclaimer", [missing_disclaimers(by_run[n]) for n in runs]))
    lines += ["", f"{WORST} worst answer items by {ANSWER_CORRECTNESS_LABEL.lower()}, mean over runs:", ""]
    lines += worst_items(rows) or ["- none scored"]
    return lines + [""]


def summarize(records: list[dict], pairs: list[dict], git: list[dict] = ()) -> str:
    """Markdown summary of raw.jsonl rows, pairs.jsonl rows and the git states from prompts.json."""
    lines = []
    for field in ("generation_model", "embedding_model", "judge_model", "metric_version"):
        values = sorted({r[field] for r in records if field in r})
        lines.append(f"- {field}: {', '.join(values) or 'n/a'}")
    states = [f"{s['head']} ({'dirty working tree' if s['dirty'] else 'clean'})" for s in git]
    lines.append(f"- git: {', '.join(states) or 'n/a'}")
    lines.append("")
    for arm in RATES:
        rows = [r for r in records if r["arm"] == arm]
        if rows:
            lines += arm_section(arm, rows, [p for p in pairs if p["arm"] == arm])
    return "\n".join(lines)
