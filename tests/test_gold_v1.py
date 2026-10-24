"""Step 09c: the frozen gold set v1 (evals/gold_v1.jsonl) and its recorded hash.

Numbered tests map to Hank's step 09c expected results 1-5. Tests marked "extra" are added by
Claude. Reads files only: no Supabase, no Gemini.
"""

import hashlib
import json
import re
from collections import Counter

import pytest

from app.gold import (
    DRAFTS,
    EVALS_README,
    GOLD,
    QUESTION_FIELDS,
    RAW_DIR,
    copy_problems,
    corpus_text,
    draft_problems,
    problems,
    read_drafts,
    read_questions,
)
from app.ingest.chunking import read_manifest

EDITED = {"Q10", "Q12", "Q13", "Q16"}
LEAVE_EXCEPTION = "excluding time off taken consistent with leave-related policies"


@pytest.fixture(scope="module")
def gold():
    return {g["qid"]: g for g in read_drafts(GOLD)}


def canonical(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


# 1. evals/gold_v1.jsonl -> 41 items: 31 answer, 10 refuse; Single-fact 11, Multi-hop 5,
# Scenario 5, Paired neutral 5, Paired leading 5, Refusal: out-of-scope 3, Refusal: near-miss 5,
# Refusal: time-sensitive 2. Every existing validation (exact keys, verbatim quotes, empty refuse
# fields, pairs) passes on it.
def test_01_gold_counts_and_every_validation_passes(gold):
    items = list(gold.values())
    assert len(items) == 41
    assert Counter(g["expected"] for g in items) == {"answer": 31, "refuse": 10}
    assert Counter(g["category"] for g in items) == {
        "Single-fact": 11,
        "Multi-hop": 5,
        "Scenario": 5,
        "Paired neutral": 5,
        "Paired leading": 5,
        "Refusal: out-of-scope": 3,
        "Refusal: near-miss": 5,
        "Refusal: time-sensitive": 2,
    }
    assert draft_problems(items, corpus_text()) == []
    assert problems(items) == []
    assert copy_problems(items, read_questions(), read_manifest(RAW_DIR)["ecfr_issue_date"]) == []


# 2. Compared with the draft, only Q10, Q12, Q13 and Q16 differ; every other item is
# byte-identical after JSON normalization.
def test_02_only_the_approved_items_differ_from_the_draft(gold):
    drafts = {d["qid"]: d for d in read_drafts(DRAFTS)}
    assert list(drafts) == list(gold)
    assert {qid for qid in gold if canonical(gold[qid]) != canonical(drafts[qid])} == EDITED


# 3. Q10's answer does not mention the EAD; Q13's answer and quote include the leave exception;
# Q12 is a refuse item with empty answer fields.
def test_03_approved_edits(gold):
    assert "EAD" not in gold["Q10"]["reference_answer"]
    assert "leave" in gold["Q13"]["reference_answer"]
    assert LEAVE_EXCEPTION in gold["Q13"]["source_quote"]
    q12 = gold["Q12"]
    assert (q12["category"], q12["expected"]) == ("Refusal: near-miss", "refuse")
    assert (q12["reference_answer"], q12["citation_keys"], q12["source_quote"]) == ("", [], "")


# 4. evals/README.md records the sha256 of evals/gold_v1.jsonl -> a test recomputes it and fails
# if the file changes. The failure message says a changed gold set voids the baseline.
def test_04_gold_file_matches_the_recorded_sha256():
    recorded = re.search(r"sha256: `([0-9a-f]{64})`", EVALS_README.read_text(encoding="utf-8")).group(1)
    actual = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    assert actual == recorded, (
        f"{GOLD.name} changed (sha256 {actual}, recorded {recorded}): a changed gold set voids the "
        "baseline; freeze a new version instead of editing v1"
    )


# 5. Edge: Q16 -> either its quote contains "timely" or its answer does not.
def test_05_q16_timely_is_supported_by_the_quote(gold):
    q16 = gold["Q16"]
    assert "timely" in q16["source_quote"] or "timely" not in q16["reference_answer"]


def test_extra_gold_items_keep_the_draft_schema(gold):
    fields = {*QUESTION_FIELDS, "reference_answer", "citation_keys", "source_quote", "corpus_issue_date"}
    assert all(set(g) == fields for g in gold.values())

