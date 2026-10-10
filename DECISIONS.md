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

## 2026-10-08 Gold set authorship split

**Amends**: [2026-09-01 Gold dataset workflow (rule change)](#2026-09-01-gold-dataset-workflow-rule-change). That entry stays as the record of the earlier rule; where the two differ, this entry applies.
**Decision**: I write every question by hand, seeded from OPT questions my classmates and I have actually asked. Refusal questions and the paired neutral / preference-leading questions are also written entirely by hand. An LLM may draft the reference answer and citation for each question; I verify every draft against the source text before the set freezes.
**Rejected alternatives**: LLM drafts the full candidate including the question (the 2026-09-01 rule; question wording drifts toward the model's own phrasing and topic choice drifts toward easily retrieved paragraphs); fully hand-written including reference answers (answer drafting is the most time-consuming part, and per-item verification already keeps its bias in check)
**Rationale**: Dataset bias enters mainly through the questions: wording that matches the model's phrasing, and topics that favor paragraphs that are easy to retrieve. Real questions from real students avoid both. Reference answers take the most time to write, and verifying each draft against the source keeps LLM drafting bias under control.

## 2026-10-08 Processing time data: one-time snapshot

**Decision**: Processing time data is fetched once, the same way as the corpus: record the fetch date and a content hash, and commit the snapshot to the repo. No scheduled fetching. The data stays out of the v1 index, and the fetch is deferred until a step actually needs it. Processing-time questions in the gold set are refusal items. Continuous monitoring is listed as future work in the README.
**Rejected alternatives**: scheduled fetching from the start of the project to build a history (a 14-day window cannot accumulate a meaningful history, and a scheduler adds infrastructure that serves neither retrieval nor eval)
**Rationale**: A one-time snapshot is versioned and reproducible like the corpus, at near-zero cost. Monitoring over time is a product feature the eval story does not depend on.

## 2026-10-08 Product scope: no pivot

**Decision**: opt-rag stays a RAG QA system over F-1/OPT regulations; the project description in CLAUDE.md is unchanged. A deterministic OPT/STEM timeline calculator is a stretch goal: built only if there is slack after the first version ships, otherwise listed as future work. My own OPT application delay is used only in the README motivation section and as a gold set question category. "RAG has no advantage over a bare LLM on public data" is treated as a hypothesis to test, not a conclusion.
**Rejected alternatives**: pivoting to an OPT/STEM timeline calculator and scenario-comparison tool (moves the center of the project away from retrieval and eval; the date engine alone was budgeted at up to 1.5 days); switching to a different domain (rebuilds the corpus and dataset without saving time)
**Rationale**: The project exists to prove hands-on RAG skill, which is judged on retrieval quality and eval rigor rather than product novelty. A fixed scope protects the days the experiments need. Treating the no-advantage claim as a hypothesis turns it into something the eval can measure (see the baseline comparison entry below).

## 2026-10-08 Baseline comparison: bare Gemini vs opt-rag

**Decision**: Run the same frozen gold set through bare Gemini and through opt-rag. Bare Gemini gets the same generation prompt as opt-rag (cite paragraph numbers, refuse when unsure) minus the retrieved context, so retrieval is the only difference between the two arms. Ragas metrics: Faithfulness, Context recall, Factual correctness. Both systems: Factual correctness, citation accuracy, refusal behavior, and answer stability across the paired neutral / preference-leading questions. opt-rag only: Faithfulness, Context recall, hit@5, and MRR; hit@5 and MRR are computed from citation IDs, with no LLM judge. Each configuration runs 3 times to measure score variance. The judge LLM comes from a different model family than the generator.
**Rejected alternatives**: evaluating opt-rag alone (no reference point for whether retrieval adds anything); bare Gemini with code execution as a third arm (only meaningful next to the timeline calculator, which is a stretch goal); a bare Gemini prompt without the citation and refusal instructions (prompt differences would mix into the retrieval comparison); a single run per configuration (a small delta cannot be told apart from run-to-run noise); a judge from the generator's model family (it may favor answers written in its own style)
**Rationale**: This tests the hypothesis from the product scope entry directly. Answer stability across neutral and leading phrasings shows whether retrieved context makes answers less sensitive to how a question is framed. Retrieval metrics computed from citation IDs are deterministic, so they carry none of the judge's noise.
