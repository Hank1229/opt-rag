"""Eval summary: per-arm markdown tables (mean, min, max over runs) and the worst answer items.

Which rows count toward what:
- Mean metrics average answer items within a run, then mean/min/max across runs. A metric
  Ragas could not score (None) is left out of its run's mean; the n column shows, per run,
  items scored out of answer items, so those gaps stay visible.
- Share metrics are x/n per run. Mean is the mean of each run's x/n; Min and Max are the runs
  with the lowest and highest share.
- Refuse items count only toward the three refusal verdict rows. On answer items, only
  REFUSED is a false refusal.
"""

import re
from collections import defaultdict

from app.evals.metrics import ANSWER_CORRECTNESS_LABEL

# Per arm: (table label, metric key) of the metrics averaged over answer items.
MEAN_METRICS = {
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
RUN_FIELDS = ("generation_model", "embedding_model", "judge_model", "metric_version")
REFUSAL_VERDICTS = ("REFUSED", "PARTIAL", "ANSWERED")
WORST = 5
SNIPPET_CHARS = 120
N_COLUMN_NOTE = (
    "n is per run: items scored out of answer items for rates, cited keys for the unknown citation rate, "
    "items or pairs judged for counts."
)


def summarize(records: list[dict], pairs: list[dict], git: list[dict] = ()) -> str:
    """Markdown summary of raw.jsonl rows, pairs.jsonl rows and the git states from prompts.json."""
    lines = []
    for field in RUN_FIELDS:
        values = sorted({r[field] for r in records if field in r})
        lines.append(f"- {field}: {', '.join(values) or 'n/a'}")
    states = [f"{s['head']} ({'dirty working tree' if s['dirty'] else 'clean'})" for s in git]
    lines += [f"- git: {', '.join(states) or 'n/a'}", ""]
    for arm in MEAN_METRICS:
        rows = [r for r in records if r["arm"] == arm]
        if rows:
            lines += arm_section(arm, rows, [p for p in pairs if p["arm"] == arm])
    return "\n".join(lines)


def arm_section(arm: str, rows: list[dict], pairs: list[dict]) -> list[str]:
    """One arm's heading, metric table and worst answer items."""
    run_ids = sorted({r["run"] for r in rows})
    runs = [[r for r in rows if r["run"] == n] for n in run_ids]
    pair_runs = [[p for p in pairs if p["run"] == n] for n in run_ids]
    lines = [
        f"## {arm}",
        "",
        f"Runs: {len(runs)}. Items scored per run: {', '.join(str(len(run)) for run in runs)}.",
        "",
        N_COLUMN_NOTE,
        "",
        "| Metric | Mean | Min | Max | n |",
        "|---|---|---|---|---|",
    ]
    lines += metric_table(arm, runs, pair_runs)
    lines += ["", f"{WORST} worst answer items by {ANSWER_CORRECTNESS_LABEL.lower()}, mean over runs:", ""]
    lines += worst_items(rows) or ["- none scored"]
    return lines + [""]


def metric_table(arm: str, runs: list[list[dict]], pair_runs: list[list[dict]]) -> list[str]:
    """Table rows in report order: mean metrics, unknown citation rate, then the share metrics."""
    lines = [
        mean_row(label, [metric_mean(run, key) for run in runs], [scored_of_answers(run, key) for run in runs])
        for label, key in MEAN_METRICS[arm]
    ]
    lines.append(mean_row(
        "Unknown citation rate",
        [unknown_citation_rate(run) for run in runs],
        [f"{cited_key_count(run)} keys" for run in runs],
    ))
    lines += [
        share_row(
            f"Refuse items judged {verdict}",
            [share(refuse_items(run), lambda r: r["metrics"]["refusal_verdict"] == verdict) for run in runs],
        )
        for verdict in REFUSAL_VERDICTS
    ]
    lines.append(share_row(
        "False refusal rate, answer items", [share(answer_items(run), lambda r: r["metrics"]["refused"]) for run in runs]
    ))
    lines.append(share_row("Pair stability", [share(group, lambda p: p["same"]) for group in pair_runs]))
    lines.append(share_row(
        "Answer items without the disclaimer",
        [share(answer_items(run), lambda r: not r["disclaimer_stripped"]) for run in runs],
    ))
    return lines


def mean_row(label: str, per_run: list[float | None], n: list[str]) -> str:
    """Table row of a metric with one value per run; runs with no value are left out."""
    values = [v for v in per_run if v is not None]
    if not values:
        return f"| {label} | n/a | n/a | n/a | {', '.join(n)} |"
    return f"| {label} | {mean(values):.3f} | {min(values):.3f} | {max(values):.3f} | {', '.join(n)} |"


def share_row(label: str, per_run: list[tuple[int, int]]) -> str:
    """Table row of an x/n count per run; Min and Max show the runs' own x/n."""
    judged = [(x, n) for x, n in per_run if n]
    n_column = ", ".join(str(n) for _, n in per_run)
    if not judged:
        return f"| {label} | n/a | n/a | n/a | {n_column} |"
    low = min(judged, key=lambda c: c[0] / c[1])
    high = max(judged, key=lambda c: c[0] / c[1])
    return f"| {label} | {mean([x / n for x, n in judged]):.3f} | {low[0]}/{low[1]} | {high[0]}/{high[1]} | {n_column} |"


def worst_items(rows: list[dict]) -> list[str]:
    """The lowest answer items by answer correctness averaged over runs, with their worst answer."""
    scored_by_qid = defaultdict(list)
    for r in answer_items(rows):
        if r["metrics"].get("answer_correctness") is not None:
            scored_by_qid[r["qid"]].append(r)
    ranked = sorted(scored_by_qid.values(), key=correctness_mean)
    lines = []
    for group in ranked[:WORST]:
        lowest = min(group, key=correctness)
        question, answer = snippet(lowest["question"]), snippet(lowest["answer"])
        lines.append(f"- {lowest['qid']} {correctness_mean(group):.2f}: {question} Answer: {answer}")
    return lines


def metric_mean(run: list[dict], key: str) -> float | None:
    """One run's mean of a metric over its scored answer items."""
    return mean([r["metrics"].get(key) for r in answer_items(run)])


def scored_of_answers(run: list[dict], key: str) -> str:
    answers = answer_items(run)
    return f"{sum(r['metrics'].get(key) is not None for r in answers)}/{len(answers)}"


def unknown_citation_rate(run: list[dict]) -> float | None:
    """Unknown cited keys over all cited keys of a run's answer items."""
    cited = cited_key_count(run)
    unknown = sum(len(r["unknown_keys"]) for r in answer_items(run))
    return unknown / cited if cited else None


def cited_key_count(run: list[dict]) -> int:
    return sum(len(r["cited_keys"]) for r in answer_items(run))


def share(rows: list[dict], is_counted) -> tuple[int, int]:
    """(rows where is_counted holds, all rows)."""
    return sum(is_counted(r) for r in rows), len(rows)


def answer_items(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["expected"] == "answer"]


def refuse_items(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["expected"] == "refuse"]


def correctness(row: dict) -> float:
    return row["metrics"]["answer_correctness"]


def correctness_mean(group: list[dict]) -> float:
    return mean([correctness(r) for r in group])


def mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def snippet(text: str) -> str:
    """Text on one line, cut to SNIPPET_CHARS."""
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 3] + "..."
