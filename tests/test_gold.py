"""Step 09a gold set drafts: validation against the locally chunked corpus and review order.

Numbered tests map to Hank's step 09a expected results 2-5; result 1 is covered by
tests/test_questions.py. "Step 09b re-pin 5" maps to step 09b part 2 expected result 5.
Tests marked "extra" are edge cases added by Claude.
Reads files only: no Supabase, no Gemini.
"""

import pytest

from app.gold import (
    DRAFTS,
    NOT_IN_CORPUS,
    QUESTION_FIELDS,
    RAW_DIR,
    copy_problems,
    corpus_text,
    draft_problems,
    read_drafts,
    read_questions,
    review_order,
)
from app.ingest.chunking import read_manifest

KEY = "214.2(f)(10)(ii)(E)"
QUOTE = "Students may not accrue an aggregate of more than 90 days of unemployment during any post-completion OPT period"


@pytest.fixture(scope="module")
def corpus():
    return corpus_text()


def draft(qid="Q1", expected="answer", reference_answer="90 days.", citation_keys=(KEY,), source_quote=QUOTE):
    return {
        "qid": qid,
        "expected": expected,
        "reference_answer": reference_answer,
        "citation_keys": list(citation_keys),
        "source_quote": source_quote,
    }


# 2. A drafted "answer" item -> has reference_answer, at least one citation_key, and source_quote
# appears verbatim in the corpus text.
def test_02_drafted_answer_item_passes(corpus):
    assert draft_problems([draft()], corpus) == []


def test_02_answer_item_needs_answer_key_and_verbatim_quote(corpus):
    drafts = [
        draft("Q1", reference_answer=""),
        draft("Q2", citation_keys=()),
        draft("Q3", source_quote="Students may accrue an aggregate of more than 90 days of unemployment"),
    ]
    assert draft_problems(drafts, corpus) == [
        "Q1: no reference_answer",
        "Q2: no citation_keys",
        "Q2: source_quote not found in the cited text: 'Students may not accrue an aggregate of more than 90 days of'",
        "Q3: source_quote not found in the cited text: 'Students may accrue an aggregate of more than 90 days of une'",
    ]


# 3. A citation_key not in the locally chunked key list (e.g. (f)(10)(ii)(Z)) -> validation fails
# and names the qid and the bad key.
def test_03_unknown_citation_key_fails(corpus):
    item = draft("Q7", citation_keys=(KEY, "214.2(f)(10)(ii)(Z)"))
    assert draft_problems([item], corpus) == [
        "Q7: citation_key '214.2(f)(10)(ii)(Z)' is not in the chunked corpus"
    ]


# 4. A "refuse" item with a reference_answer or citation_keys filled in -> validation fails.
def test_04_refuse_item_with_a_draft_fails(corpus):
    drafts = [
        draft("Q40", "refuse", citation_keys=(), source_quote=""),
        draft("Q41", "refuse", reference_answer="", source_quote=""),
        draft("Q39", "refuse", reference_answer="", citation_keys=(), source_quote=""),
    ]
    assert draft_problems(drafts, corpus) == [
        "Q40: refuse item must have no reference_answer, citation_keys or source_quote",
        "Q41: refuse item must have no reference_answer, citation_keys or source_quote",
    ]


# 5. Edge: an "answer" item whose answer is not in the corpus -> marked NOT_IN_CORPUS with an
# empty answer, listed first in the review sheet.
def test_05_not_in_corpus_item_passes_and_is_reviewed_first(corpus):
    found = draft("Q1")
    missing = draft("Q2", reference_answer=NOT_IN_CORPUS, citation_keys=(), source_quote="")
    assert draft_problems([found, missing], corpus) == []
    assert review_order([found, missing]) == [missing, found]


def test_extra_not_in_corpus_item_with_a_citation_fails(corpus):
    item = draft("Q2", reference_answer=NOT_IN_CORPUS)
    assert draft_problems([item], corpus) == [
        f"Q2: {NOT_IN_CORPUS} item must have no citation_keys or source_quote"
    ]


def test_extra_quote_matches_across_line_breaks_and_extra_spaces(corpus):
    item = draft(source_quote=QUOTE.replace(" of unemployment ", "  of\nunemployment "))
    assert draft_problems([item], corpus) == []


def test_extra_quote_must_come_from_a_cited_key(corpus):
    item = draft(citation_keys=("214.2(f)(11)(i)",))
    assert draft_problems([item], corpus) == [
        "Q1: source_quote not found in the cited text: 'Students may not accrue an aggregate of more than 90 days of'"
    ]


# Step 09b: a cited key matches only chunks with exactly that citation_key, never a parent or child key.
def test_extra_quote_must_come_from_the_exact_key_not_its_parent_or_child(corpus):
    cites_parent = draft(citation_keys=("214.2(f)(10)",))
    cites_child = draft(
        source_quote="A student may be authorized 12 months of practical training",
        citation_keys=("214.2(f)(10)(i)",),
    )
    assert draft_problems([cites_parent, cites_child], corpus) == [
        "Q1: source_quote not found in the cited text: 'Students may not accrue an aggregate of more than 90 days of'",
        "Q1: source_quote not found in the cited text: 'A student may be authorized 12 months of practical training'",
    ]


# Step 09b re-pin 5. Edge: a draft whose citation_key no longer exists or whose quote no longer
# matches the new corpus -> validation fails and names the qid.
def test_09b_5_draft_from_the_amended_text_fails_after_the_repin(corpus):
    gone_key = draft("Q16", citation_keys=("214.2(f)(5)(vii)(A)",), source_quote="The status, and any employment authorization")
    old_quote = draft(
        "Q4",
        citation_keys=("214.2(f)(11)(i)(B)(2)",),
        source_quote="up to 90 days prior to his or her program end date and no later than 30 days after his or her program end date.",
    )
    assert draft_problems([gone_key, old_quote], corpus) == [
        "Q16: citation_key '214.2(f)(5)(vii)(A)' is not in the chunked corpus",
        "Q16: source_quote not found in the cited text: 'The status, and any employment authorization'",
        "Q4: source_quote not found in the cited text: 'up to 90 days prior to his or her program end date and no la'",
    ]


def test_extra_quote_fragments_are_checked_one_by_one(corpus):
    second = "A student must initiate the OPT application process by requesting a recommendation for OPT from his or her DSO."
    keys = (KEY, "214.2(f)(11)(i)")
    assert draft_problems([draft(citation_keys=keys, source_quote=f"{QUOTE} [...] {second}")], corpus) == []
    assert draft_problems([draft(citation_keys=keys, source_quote=f"{QUOTE} [...] Made up.")], corpus) == [
        "Q1: source_quote not found in the cited text: 'Made up.'"
    ]


def test_extra_review_order_keeps_file_order_and_leaves_out_refuse_items():
    first, refuse, second = draft("Q1"), draft("Q2", "refuse"), draft("Q3")
    missing = draft("Q4", reference_answer=NOT_IN_CORPUS)
    assert review_order([first, refuse, second, missing]) == [missing, first, second]


def test_extra_drafts_must_copy_question_fields_unchanged():
    questions = read_questions()[:2]
    drafts = [{**q, "corpus_issue_date": "2026-10-01"} for q in questions]
    drafts[1] = {**drafts[1], "question": drafts[1]["question"] + " (edited)"}
    assert copy_problems(drafts, questions, "2026-10-01") == [f"{questions[1]['qid']}: question differs from questions_v1.csv"]
    assert copy_problems(drafts[:1], questions, "2026-10-01") == ["draft count 1 does not match question count 2"]
    assert copy_problems(drafts[:1], questions[:1], "2026-10-02") == [
        f"{questions[0]['qid']}: corpus_issue_date is not the manifest's 2026-10-02"
    ]


def test_extra_draft_file_passes_every_check(corpus):
    if not DRAFTS.exists():
        pytest.skip(f"{DRAFTS} not written yet")
    drafts = read_drafts()
    issue_date = read_manifest(RAW_DIR)["ecfr_issue_date"]
    assert copy_problems(drafts, read_questions(), issue_date) == []
    assert draft_problems(drafts, corpus) == []
    assert all(set(d) == {*QUESTION_FIELDS, "reference_answer", "citation_keys", "source_quote", "corpus_issue_date"} for d in drafts)
