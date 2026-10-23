"""Step 09b: Tier 1 re-pinned to eCFR issue date 2026-09-14, the last day before the Duration
of Status amendment took effect.

Numbered tests map to Hank's step 09b part 2 expected results 2 and 4; result 3 is in
tests/test_embedding.py and result 5 in tests/test_gold.py. Tests marked "extra" are added by
Claude. Offline except the one marked live, which refetches from the eCFR API.
"""

import hashlib

import pytest

from app.gold import QUOTE_GAP, corpus_text, read_drafts
from app.ingest.chunking import check_raw_hashes, read_manifest
from conftest import RAW_DIR, ROOT

ISSUE_DATE = "2026-09-14"
OPT_STEPS = "applying-for-practical-training#practical-training-for-f-students/optional-practical-training/application-steps"
STATUS_GAP = "h-1b-status-and-the-cap-gap-extension#f-1-status-gap"


@pytest.fixture(scope="module")
def corpus():
    return corpus_text()


def tier1_entry() -> dict:
    return next(e for e in read_manifest(RAW_DIR)["entries"] if e["tier"] == 1)


# 2. Fetch with the new issue date -> manifest ecfr_issue_date becomes 2026-09-14; fetching the
# same date again gives the same hash.
def test_02_manifest_pins_tier1_to_the_new_issue_date():
    assert read_manifest(RAW_DIR)["ecfr_issue_date"] == ISSUE_DATE
    assert f"/full/{ISSUE_DATE}/" in tier1_entry()["url"]
    assert check_raw_hashes(RAW_DIR) == []


@pytest.mark.live
def test_02_live_refetching_the_same_date_gives_the_same_hash(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import fetch_ecfr

    with fetch_ecfr.make_client() as client:
        url = f"{fetch_ecfr.API}/full/{ISSUE_DATE}/title-{fetch_ecfr.TITLE}.xml"
        resp = client.get(url, params=fetch_ecfr.HIERARCHY).raise_for_status()
    assert hashlib.sha256(resp.content).hexdigest() == tier1_entry()["raw_sha256"]


# 4. After the re-pin, the Q4 and Q9 quotes say 60 days, and Tier 1 and Tier 2 no longer
# disagree on them.
def test_04_q4_and_q9_quotes_say_60_days():
    drafts = {d["qid"]: d for d in read_drafts()}
    assert "no later than 60 days after his or her program end date" in drafts["Q4"]["source_quote"]
    assert "60-day period to prepare for departure" in drafts["Q9"]["source_quote"]


def test_04_tier1_and_tier2_agree_on_60_days(corpus):
    assert "no later than 60 days after his or her program end date" in corpus["214.2(f)(11)(i)(B)(2)"]
    assert "no later than 60 days after you complete your degree" in corpus[OPT_STEPS]
    assert "additional 60-day period to prepare for departure" in corpus["214.2(f)(5)(iv)"]
    assert "F-1 students have only 60 days to take the steps necessary" in corpus[STATUS_GAP]


def test_extra_tier1_no_longer_has_the_30_day_rules(corpus):
    tier1 = " ".join(text for key, text in corpus.items() if key.startswith("214.2"))
    assert "no later than 30 days after his or her program end date" not in tier1
    assert "additional 30-day period" not in tier1
    assert "Period of stay" not in tier1


def test_extra_q4_and_q9_cite_both_tiers():
    drafts = {d["qid"]: d for d in read_drafts()}
    for qid in ("Q4", "Q9"):
        tiers = {key.startswith("214.2") for key in drafts[qid]["citation_keys"]}
        assert tiers == {True, False}, qid
        assert len(drafts[qid]["source_quote"].split(QUOTE_GAP)) >= 2, qid
