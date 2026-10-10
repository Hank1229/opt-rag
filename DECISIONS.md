# DECISIONS.md

Architecture and process decisions for opt-rag, with rejected
alternatives and rationale. Newest entries at the bottom.

## 2026-09-01 Project skeleton

**Decision**: uv for venv + dependency management, uv.lock committed, Python pinned >=3.12,<3.13
**Rejected alternatives**: pip + venv + requirements.txt; poetry
**Rationale**: uv covers venv, lockfile, and script execution in one tool and installs fast. The lockfile keeps local and Fly.io environments identical. poetry overlaps but runs slower; pip has no native lock mechanism.
**Note**: Suggested by Claude Code, confirmed by me.

## 2026-09-01 Gold dataset workflow (rule change)

**Decision**: LLM drafts QA candidates (question + short answer + source quote + citation), I verify every citation by hand before freezing the set. The original "fully hand-written" rule is retired.
**Rejected alternatives**: fully hand-written (requires reading the full regulation first, time cost too high); fully auto-generated (no human anchor for ground truth, eval loses credibility)
**Rationale**: Human citation review is the minimum credibility requirement and costs 2-3 minutes per item. LLM drafting cuts my manual work from a full day to about two hours.
**Known bias**: LLM drafts favor simple questions with an explicit source sentence. Multi-hop and refusal questions get added manually during category balancing.

## 2026-09-01 Corpus sources and ingestion format

**Decision**: Two-tier corpus. Tier 1: full text of 8 CFR 214.2(f) via the eCFR API (authoritative, citable by paragraph). Tier 2: Study in the States student pages from a fixed URL list (plain language, close to real user phrasing). Fetch script writes raw files to data/raw/ plus a manifest (url, fetched_at, content hash). A source_tier field goes into chunk metadata.
**Rejected alternatives**: USCIS OPT pages (overlap with Study in the States); SEVP policy PDFs (extra parsing format, kept as a fallback after Day 6 failure analysis); university ISS FAQs (single-school interpretations, weak authority); web crawler (uncontrolled scope)
**Rationale**: The two tiers cover two retrieval needs, citability and phrasing proximity. The manifest makes the corpus versionable, so corpus freeze and eval baseline stay bound together.

## 2026-09-01 Embedding model and dimension

**Decision**: Gemini embedding truncated to 768 dims via MRL; cosine distance (vector_cosine_ops in pgvector)
**Rejected alternatives**: full 3072 dims (4x storage and compute for a 1-2% quality gap at this corpus size); 1536 dims (middle option with no distinct advantage here)
**Rationale**: Corpus is roughly a thousand chunks. At that scale the quality gap between 768 and 3072 is unmeasurable in our eval, while storage and similarity compute drop 4x. Re-embedding the whole corpus later costs near zero, so this choice stays reversible.

## 2026-09-01 Chunking strategy

**Decision**: Structure-aware chunking. Tier 1 splits on regulation paragraph hierarchy, one numbered paragraph per chunk, paragraph ID (e.g. (f)(10)(ii)(A)) stored in metadata as the citation key. Tier 2 splits on HTML heading blocks (h2/h3). Paragraphs over ~800 tokens fall back to fixed-size splitting, keeping the parent paragraph ID in metadata.
**Rejected alternatives**: fixed token size + overlap (cheap to build, but cuts across paragraph boundaries; a clause split across two chunks retrieves poorly from both, and citations lose paragraph precision)
**Rationale**: Regulation text carries its own segmentation: paragraph numbering is both the semantic boundary and the citation key. Fixed-size splitting stays as a fallback for oversized paragraphs only.
**Note**: Flagged as the most likely parameter to revisit after Day 6 failure analysis; baseline runs on this version.

## 2026-09-01 Retrieval top-k baseline

**Decision**: top-k = 5 for the baseline
**Rejected alternatives**: k=3 (precision-leaning, risks missing cross-paragraph answers like STEM OPT extension rules that span (f)(10)(ii)(C) and EAD paragraphs)
**Rationale**: Structure-aware chunks are fine-grained, so cross-paragraph questions need headroom. Baseline should let context_recall stand first; if Day 6 analysis shows precision dragging, lower k or add reranking. Cheapest parameter to change: one number, one eval rerun, no re-ingestion.

## 2026-09-01 Generation prompt structure

**Decision**: Four fixed elements. (1) Each retrieved chunk is labeled with an index and source key, e.g. [1] 8 CFR 214.2(f)(10)(ii)(A). (2) The answer must cite which labeled source it relies on. (3) Refusal instruction: if the context does not contain the answer, say so and point the user to their DSO; never fill gaps with model knowledge. (4) Fixed disclaimer footer: informational summary, not legal advice. Answers are English-only.
**Rejected alternatives**: answer in the user's language (better demo, but the eval set is English and mixed-language answers add scoring noise in Ragas); no citation requirement (faster to build, but failure analysis loses the ability to tell retrieval errors from generation errors)
**Rationale**: Citation labels make Day 6 error triage fast. The refusal line is the faithfulness floor and doubles as the baseline for the refusal experiment. English-only keeps eval scoring clean; multilingual support goes to future work and needs its own dataset to measure.

## 2026-10-07 Corpus snapshot

**Decision**: Tier 1 is the eCFR 8 CFR 214.2 section at issue date 2026-10-01, fetched via the versioner API. fetch_ecfr.py takes an --issue-date argument, defaulting to the date recorded in the manifest, so a rerun reproduces the same file. The raw file keeps the full section; only paragraph (f) gets chunked and ingested. Tier 2 stores raw_sha256 (full HTML) and content_sha256 (visible text inside `<article>`).
**Rejected alternatives**: fetching the latest eCFR version without a date (not reproducible); trimming the raw file to (f) at fetch time (loses the untouched source of record); hashing `<main>` for content_sha256 (it contains the site-wide sidebar menu, so adding any page to the site would change all 13 hashes)
**Rationale**: A pinned issue date makes the corpus reproducible and ties it to the eval baseline. Restricting ingestion to (f) keeps unrelated visa classes out of the index, but does not remove H-1B entirely: the cap-gap paragraphs in (f)(5) and one Tier 2 page discuss H-1B. Refusal tests therefore need two kinds of items: fully out-of-scope questions, and near-miss questions where retrieval finds related text that cannot answer them. Two hashes separate real content changes from page-layout changes.

## 2026-10-07 Fetch implementation

**Decision**: Python pinned to uv-managed 3.12.14 via .python-version. httpx as the HTTP client. fetch_sits.py writes files only after all 13 pages succeed.
**Rejected alternatives**: python.org Python 3.12.5 (its OpenSSL 3.0.13 TLS fingerprint gets HTTP 403 from the site's Akamai CDN on every Tier 2 page); urllib from the standard library (manual gzip decoding); writing each page as soon as it arrives (a mid-run failure would leave a half-updated corpus)
**Rationale**: Reproducible fetches need both a working TLS stack and all-or-nothing writes.
