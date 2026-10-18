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

## 2026-10-13 v2 backlog

**Decision**: These are planned for v2 and start only after v1 (steps 06 to 13) ships: Langfuse tracing, hybrid search, reranking, chunking experiments, refusal experiments, and Jev refusal-gating. They stay out of CLAUDE.md's stack and out of v1 code, but they are not cancelled.
**Rejected alternatives**: building any of them during v1 (expands scope before the core pipeline and baseline eval exist); dropping them (they are the experiments that turn the baseline into measured improvements).
**Rationale**: v1 needs a working pipeline and a frozen baseline first. Each v2 item is one variable to change and re-measure against that baseline.

## Step 06: Database schema

### Two tables: `documents` + `chunks`
- **Decision:** Store source-level info (source_tier, title, URL, version_date) in `documents`; store chunk text, citation_key, chunk_index, and embedding in `chunks`, linked by a foreign key with ON DELETE CASCADE.
- **Rejected alternatives:** One flat `chunks` table repeating source info on every row; one table with source info in a JSONB `metadata` column.
- **Rationale:** A flat table works at this scale, but re-ingesting a document, recovering from a half-finished ingest, and listing corpus versions all get error-prone when source info is copied onto hundreds of rows. JSONB lets typos like `eCFR` or a misspelled key through unchecked. The cost of two tables is one join at retrieval time.
- **Date:** 2026-10-14

### One `version_date` per document, required
- **Decision:** `documents.version_date` is NOT NULL with no default. eCFR rows store the official issue date (2026-10-01); Study in the States rows store the fetch date, since those pages have no official publish date.
- **Rejected alternatives:** No version field; full version history with validity ranges; defaulting to the insert date.
- **Rationale:** Answers need to state which version they cite. A default of "today" would silently record the wrong date for eCFR. Full history adds version filtering that no question in scope needs.
- **Date:** 2026-10-14

### `source_tier` restricted to `ecfr` / `sits`
- **Decision:** A CHECK constraint rejects any other value.
- **Rejected alternatives:** Free text; auto-lowercasing input before insert.
- **Rationale:** Fail loud. A wrong tier value means an upstream bug in fetch or ingest; silently normalizing it hides the bug and only fixes casing errors.
- **Date:** 2026-10-14

### No vector index (exact scan)
- **Decision:** Retrieval compares the query against every chunk with cosine distance; no HNSW or IVFFlat index.
- **Rejected alternatives:** HNSW; IVFFlat.
- **Rationale:** The corpus is a few hundred to low thousands of chunks, so exact scan takes milliseconds while Gemini generation takes seconds. Exact results keep hit@5 free of approximation error, which matters for legal content. IVFFlat also needs existing data to build well.
- **Revisit when:** chunk count exceeds ~10k or retrieval noticeably slows responses; then add HNSW and compare hit@5 against exact scan.
- **Date:** 2026-10-14

### Uniqueness on (document_id, citation_key, chunk_index)
- **Decision:** A unique constraint on the three columns together.
- **Rejected alternatives:** No constraint; truncate and reload every ingest; unique content_hash.
- **Rationale:** A database-level guard against duplicates regardless of ingest bugs, so ingest can be rerun safely. citation_key alone is not unique because oversized paragraphs split into several chunks sharing one key. Truncate-and-reload re-embeds everything every run and leaves a half-empty table on failure. content_hash leaves stale rows behind when text changes. Removing stale chunks on re-ingest is handled in step 07.
- **Date:** 2026-10-14

### Schema managed as migration SQL files
- **Decision:** All schema changes live as migration files in the repo; existing migrations are never edited, changes go in new files.
- **Rejected alternatives:** Running SQL by hand in the Supabase dashboard; an ORM (SQLAlchemy + Alembic).
- **Rationale:** Anyone can rebuild the same database from the repo, and git history shows every schema change. An ORM needs extra packages for pgvector and is more machinery than this project needs.
- **Date:** 2026-10-14

### RLS on, backend-only access
- **Decision:** Row Level Security enabled on both tables with no public policies. The project has the Data API on, "Automatically expose new tables" off, and "Enable automatic RLS" off. The migration enables RLS itself and grants table privileges only to the role the secret key uses. Only the FastAPI backend reads and writes, using the Supabase secret key, which never ships to the Vercel frontend.
- **Rejected alternatives:** RLS off; RLS on with a public read policy; auto-exposing new tables and relying on RLS alone; Supabase's automatic RLS trigger.
- **Rationale:** The publishable key is public by design. With tables not auto-exposed, the publishable key gets a permission error instead of silently returning zero rows, which makes misuse obvious. Automatic RLS is off so the migration alone is responsible for RLS: a test can then catch a migration that forgets it, and the repo rebuilds correctly on a project without that setting.
- **Caught:** The plan first used the legacy `anon` / `service_role` key names. New Supabase projects only issue publishable and secret keys, so tests and env vars use the new names.
- **Date:** 2026-10-14

### Primary keys: bigint identity
- **Decision:** Both tables use `bigint generated always as identity` for `id`.
- **Rejected alternatives:** uuid; identity `generated by default` (allows manual ids).
- **Rationale:** ids stay internal to one backend-only database, so uuid's benefits (global uniqueness, unguessable, client-side generation) don't apply, while sequential ids are easier to read when debugging. `generated always` stops ingest from inserting its own ids. Eval metrics (hit@5, MRR) match on `citation_key`, so ids changing across re-ingests doesn't affect them.
- **Date:** 2026-10-16

### Required columns are NOT NULL
- **Decision:** NOT NULL on `documents.title`, `url`, `version_date`, and on `chunks.document_id`, `citation_key`, `chunk_index`, `content`, `embedding`.
- **Rejected alternatives:** NOT NULL on `version_date` only.
- **Rationale:** Fail loud: an ingest bug that drops a field should error, not write an empty row. It also closes a gap in the uniqueness constraint, since Postgres treats NULLs as distinct and would let two chunks with a NULL `citation_key` coexist.
- **Date:** 2026-10-16

### pgvector in the `extensions` schema
- **Decision:** Install pgvector in `extensions`, not `public`.
- **Rejected alternatives:** Installing in `public`.
- **Rationale:** Supabase convention; `public` is the schema the Data API exposes, and Supabase's security advisor flags extensions there. Known follow-up: queries using `vector` or `<=>` need `extensions` on the search path (relevant to step 08's retrieval function).
- **Date:** 2026-10-16

### Deferred to step 07
- **Decision:** No `created_at` column and no unique constraint on `documents.url` in step 06.
- **Rationale:** Nothing needs `created_at` yet; a later migration can add it. How re-ingest identifies "the same document" (url, eCFR section, or another key) is an ingest question and gets decided in step 07.
- **Date:** 2026-10-16

### Tests run against local Supabase; cloud check is opt-in
- **Decision:** pytest runs against a local Supabase started with the CLI and rebuilt with `supabase db reset` before each run. Local URLs and keys are read from `supabase status -o env` at test time, so no keys are stored in the repo. Passing `--target opt-rag` runs test 8 against OPT-RAG with the keys in `.env`.
- **Rejected alternatives:** Running tests directly on OPT-RAG; a second Supabase project for tests; mocking the database; committing local keys in `.env.test`; a gitignored `.env.test` with an example file.
- **Rationale:** Every run starts from an empty database built only from the migrations, without touching real data. Reading from `supabase status` keeps keys out of git and always matches the running local stack; the CLI is already required for `db reset`. Mocks don't enforce dimension limits, constraints, or RLS.
- **Constraint:** Test 8 writes a temporary row to OPT-RAG and deletes it in a `finally` block. Run it against OPT-RAG only before ingest, or check the dashboard afterward. Claude Code never runs `--target opt-rag` unless asked (see CLAUDE.md).
- **Caught:** The first version committed local default keys in `.env.test`. GitHub push protection blocked the push because the local secret key has the same `sb_secret_` format as a real one. The unpushed history was rewritten to drop the file before anything reached GitHub.
- **Date:** 2026-10-17

### Migration revokes from public roles and grants to service_role explicitly
- **Decision:** The migration revokes all table privileges from `anon` and `authenticated` and grants them to `service_role`.
- **Rejected alternatives:** Relying on OPT-RAG's "Automatically expose new tables: off" setting; a follow-up migration narrowing `service_role` to SELECT/INSERT/UPDATE/DELETE only.
- **Rationale:** Local Supabase exposes new tables to `anon` by default and OPT-RAG does not, so the same migration has to produce the same permissions in both. The `service_role` grant is a no-op under both current defaults but keeps the migration independent of them. Narrowing `service_role` adds little because the secret key is already admin-level and backend-only.
- **Caught:** Removing the revoke line on purpose made test 8 return zero rows on local Supabase instead of a permission error, confirming the two environments differ and that the test detects it.
- **Date:** 2026-10-17
