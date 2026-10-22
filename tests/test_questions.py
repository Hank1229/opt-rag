"""Validation of evals/questions_v1.csv, the hand-written gold set v1 questions.

Covers the two problems the question review caught (DECISIONS.md, 2026-10-22 "Gold set v1"):
duplicate qids and malformed pair_id values. Tests marked "extra" are checks added by Claude.
"""

import csv
import re
from collections import Counter
from pathlib import Path

QUESTIONS = Path(__file__).resolve().parent.parent / "evals" / "questions_v1.csv"
PAIR_ID = re.compile(r"P\d{2}")
PAIRED = {"Paired neutral", "Paired leading"}


def read_questions() -> list[dict[str, str]]:
    with QUESTIONS.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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
        pairs.setdefault(pair_id, []).append(r)
    for pair_id, members in pairs.items():
        if sorted(m["category"] for m in members) != sorted(PAIRED):
            got = ", ".join(f"{m['qid']} {m['category']}" for m in members)
            found.append(f"{pair_id}: needs one Paired neutral and one Paired leading, got {got}")
    return found


def row(qid, category="Single-fact", pair_id=""):
    return {"qid": qid, "category": category, "pair_id": pair_id}


def pair(pair_id, neutral="Q1", leading="Q2"):
    return [row(neutral, "Paired neutral", pair_id), row(leading, "Paired leading", pair_id)]


def test_questions_csv_has_no_problems():
    assert problems(read_questions()) == []


def test_duplicate_qid_is_reported():
    rows = [row("Q28"), row("Q29"), row("Q29")]
    assert problems(rows) == ["duplicate qid Q29"]


def test_pair_id_with_suffix_is_reported():
    rows = [row("Q1", "Paired neutral", "P01-N"), row("Q2", "Paired leading", "P01-L")]
    assert problems(rows) == [
        "Q1: pair_id 'P01-N' is not P01..P99",
        "Q2: pair_id 'P01-L' is not P01..P99",
    ]


def test_paired_question_without_pair_id_is_reported():
    rows = pair("P01") + [row("Q3", "Paired leading")]
    assert problems(rows) == ["Q3: Paired leading needs a pair_id"]


def test_pair_must_be_one_neutral_and_one_leading():
    rows = [row("Q1", "Paired neutral", "P01"), row("Q2", "Paired neutral", "P01")]
    assert problems(rows) == [
        "P01: needs one Paired neutral and one Paired leading, got Q1 Paired neutral, Q2 Paired neutral"
    ]


def test_extra_pair_id_on_unpaired_question_is_reported():
    rows = pair("P01") + [row("Q3", "Scenario", "P01")]
    assert problems(rows) == [
        "Q3: Scenario must not have a pair_id",
        "P01: needs one Paired neutral and one Paired leading, got Q1 Paired neutral, Q2 Paired leading, Q3 Scenario",
    ]


def test_extra_counts_match_the_decision():
    rows = read_questions()
    assert len(rows) == 41
    assert Counter(r["category"] for r in rows) == {
        "Single-fact": 11,
        "Multi-hop": 6,
        "Scenario": 6,
        "Paired neutral": 5,
        "Paired leading": 5,
        "Refusal: out-of-scope": 3,
        "Refusal: near-miss": 3,
        "Refusal: time-sensitive": 2,
    }


def test_extra_refusal_items_and_only_they_expect_refuse():
    for r in read_questions():
        assert (r["expected"] == "refuse") == r["category"].startswith("Refusal"), r["qid"]
