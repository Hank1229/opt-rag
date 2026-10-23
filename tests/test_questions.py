"""Validation of evals/questions_v1.csv, the hand-written gold set v1 questions.

Covers the two problems the question review caught (DECISIONS.md, 2026-10-22 "Gold set v1"):
duplicate qids and malformed pair_id values, plus the step 09a check that a paired qid starts
with its pair_id. Step 09a expected result 1 is test_questions_csv_has_no_problems together with
test_extra_counts_match_the_decision. Tests marked "extra" are checks added by Claude.
"""

from collections import Counter

from app.gold import problems, read_questions


def row(qid, category="Single-fact", pair_id=""):
    return {"qid": qid, "category": category, "pair_id": pair_id}


def pair(pair_id):
    return [row(f"{pair_id}-N", "Paired neutral", pair_id), row(f"{pair_id}-L", "Paired leading", pair_id)]


def test_questions_csv_has_no_problems():
    assert problems(read_questions()) == []


def test_duplicate_qid_is_reported():
    rows = [row("Q28"), row("Q29"), row("Q29")]
    assert problems(rows) == ["duplicate qid Q29"]


def test_pair_id_with_suffix_is_reported():
    rows = [row("P01-N", "Paired neutral", "P01-N"), row("P01-L", "Paired leading", "P01-L")]
    assert problems(rows) == [
        "P01-N: pair_id 'P01-N' is not P01..P99",
        "P01-L: pair_id 'P01-L' is not P01..P99",
    ]


def test_paired_question_without_pair_id_is_reported():
    rows = pair("P01") + [row("P02-L", "Paired leading")]
    assert problems(rows) == ["P02-L: Paired leading needs a pair_id"]


def test_pair_must_be_one_neutral_and_one_leading():
    rows = [row("P01-N", "Paired neutral", "P01"), row("P01-L", "Paired neutral", "P01")]
    assert problems(rows) == [
        "P01: needs one Paired neutral and one Paired leading, got P01-N Paired neutral, P01-L Paired neutral"
    ]


def test_paired_qid_prefix_must_match_pair_id():
    rows = [row("P01-N", "Paired neutral", "P02"), row("P02-L", "Paired leading", "P02")]
    assert problems(rows) == ["P01-N: qid prefix does not match pair_id P02"]


def test_extra_pair_id_on_unpaired_question_is_reported():
    rows = pair("P01") + [row("Q3", "Scenario", "P01")]
    assert problems(rows) == [
        "Q3: Scenario must not have a pair_id",
        "P01: needs one Paired neutral and one Paired leading, got P01-N Paired neutral, P01-L Paired leading, Q3 Scenario",
    ]


def test_extra_counts_match_the_decision():
    rows = read_questions()
    assert len(rows) == 41
    assert Counter(r["category"] for r in rows) == {
        "Single-fact": 11,
        "Multi-hop": 6,
        "Scenario": 5,
        "Paired neutral": 5,
        "Paired leading": 5,
        "Refusal: out-of-scope": 3,
        "Refusal: near-miss": 4,
        "Refusal: time-sensitive": 2,
    }


def test_extra_refusal_items_and_only_they_expect_refuse():
    for r in read_questions():
        assert (r["expected"] == "refuse") == r["category"].startswith("Refusal"), r["qid"]
