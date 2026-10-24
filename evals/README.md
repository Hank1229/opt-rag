# Gold set v1

`gold_v1.jsonl` is the frozen eval set for opt-rag: 41 hand-written F-1/OPT questions with reference answers, verbatim source quotes and citation keys drawn from the corpus in `data/raw/`. Questions come from `questions_v1.csv`; the reference answers were drafted by Claude from `data/raw/`, cross-checked by Codex, and reviewed by Hank (DECISIONS.md, 2026-10-23 "Gold set v1 frozen"). `drafts/gold_v1_draft.jsonl` is kept as the record of the draft before review fixes.

Corpus: `corpus_issue_date` 2026-09-14 (Tier 1 eCFR 8 CFR 214.2; Tier 2 Study in the States, unchanged).

## Schema

One JSON object per line:

- `qid`: question id; paired items are `P01-N` / `P01-L`, the rest `Q1`..`Q31`.
- `question`: the question as asked, in English.
- `category`: one of the categories counted below.
- `topic`: subject area (OPT, STEM OPT, Cap-Gap, Travel, ...).
- `expected`: `answer` or `refuse`.
- `pair_id`: `P01`..`P05` for neutral / preference-leading pairs, empty otherwise.
- `source`: who the question came from (`self` or `classmate`).
- `original`: the question as first written, in Chinese.
- `reference_answer`: short answer; empty for refuse items.
- `citation_keys`: chunk citation keys the answer rests on; empty for refuse items.
- `source_quote`: verbatim corpus text supporting the answer, fragments joined with ` [...] `; empty for refuse items.
- `corpus_issue_date`: eCFR issue date of the corpus the answer was checked against.

## Counts

41 items: 31 answer, 10 refuse.

- Single-fact: 11
- Multi-hop: 5
- Scenario: 5
- Paired neutral: 5
- Paired leading: 5
- Refusal: out-of-scope: 3
- Refusal: near-miss: 5
- Refusal: time-sensitive: 2

## Freeze rule

The file never changes. Any change, including a fix, voids every baseline run on it and requires a new version (`gold_v2.jsonl`). `tests/test_gold_v1.py` recomputes the hash below and fails if the file differs.

sha256: `d0f9095114b08c0ebe2d0c8a775b7743f59ff0ad785e5c20fa280cc4c2043dba`

## Known corpus gaps

- Q12 and Q19 are near-miss refusals because the corpus has no counting rule for part-time pre-completion OPT and no rule for when unemployment days start relative to EAD receipt.
- Q17's answer covers status and work authorization only, because the corpus lists no proof-of-employment document.
- Planned v2 fix: add SEVP practical training policy guidance to the corpus.
