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
**Added 2026-10-21**: Generation model upgrade from `gemini-3.6-flash` to a newer Gemini Flash (e.g. `gemini-3.8-flash`), run as a one-variable experiment against the baseline.

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

### Local Supabase runs only the services tests need
- **Decision:** supabase/config.toml disables realtime, studio, inbucket, storage, edge_runtime, and analytics (vector and pg_meta stop with them). Local stack runs db, the API gateway, PostgREST, and auth.
- **Rejected alternatives:** Running the full default stack; lowering the Docker memory limit alone.
- **Rationale:** The full stack froze a 16 GB Mac. Trimming dropped container memory from about 2.2 GiB to about 260 MiB and cut a test run from about 40 s to about 12 s, with all 12 tests still passing. Re-enable a service if a later step needs it.
- **Date:** 2026-10-19

### Migration revokes from public roles and grants to service_role explicitly
- **Decision:** The migration revokes all table privileges from `anon` and `authenticated` and grants them to `service_role`.
- **Rejected alternatives:** Relying on OPT-RAG's "Automatically expose new tables: off" setting; a follow-up migration narrowing `service_role` to SELECT/INSERT/UPDATE/DELETE only.
- **Rationale:** Local Supabase exposes new tables to `anon` by default and OPT-RAG does not, so the same migration has to produce the same permissions in both. The `service_role` grant is a no-op under both current defaults but keeps the migration independent of them. Narrowing `service_role` adds little because the secret key is already admin-level and backend-only.
- **Caught:** Removing the revoke line on purpose made test 8 return zero rows on local Supabase instead of a permission error, confirming the two environments differ and that the test detects it.
- **Date:** 2026-10-17

## Step 07: Ingest

### Ingest shape
- **Decision:** Ingest is a local CLI script that reads only the committed raw corpus and manifest, with custom chunking code.
- **Rejected alternatives:** One script that fetches and writes in the same run; LangChain / LlamaIndex loaders and vector stores; a `POST /ingest` FastAPI endpoint.
- **Rationale:** Eval needs the same input to always produce the same chunks, so ingest must not depend on the network. Framework splitters don't understand eCFR paragraph IDs, and every chunk's origin has to be explainable. The corpus changes a few times a year, so there is no reason to expose a write path on a public API or keep database credentials anywhere but the local machine.
- **Date:** 2026-10-19

### Document identity on re-ingest
- **Decision:** Each source gets a stable id (e.g. `ecfr-214.2f`) stored in the manifest and in a unique column on `documents`. The fetch scripts write the id, so a refetch keeps it. A new version of the same source updates `version_date` on the existing row.
- **Rejected alternatives:** Unique on `url`; content hash as identity; ids added to the manifest by hand.
- **Rationale:** eCFR URLs carry the issue date, so a new version would look like a new document and the old regulation text would stay retrievable. A content hash answers "did it change", not "is it the same document". Hand-added ids would be wiped the next time a fetch script rewrites the manifest. Re-embedding all ~14 documents is cheap, so skip-if-unchanged isn't needed yet.
- **Resolves:** Step 06 "Deferred to step 07".
- **Date:** 2026-10-19

### Replacing a document's chunks
- **Decision:** Per document, compute all embeddings first, then in one Postgres transaction upsert the `documents` row (title, url, version_date) and replace that document's chunks (delete, then insert). Writes use a direct Postgres connection (psycopg). If one document fails, its row and chunks stay unchanged, the others still update, and the run exits non-zero.
- **Rejected alternatives:** Upsert only; truncate and rebuild everything; version history with soft delete (v2); updating the `documents` row in a separate step; stopping the whole run on the first failure.
- **Rationale:** The (document_id, citation_key, chunk_index) constraint prevents duplicates but not orphans: upsert leaves removed paragraphs in the table and retrievable. The transaction means readers see all-old or all-new, never zero chunks, and `version_date` always matches the chunks under it. Embedding outside the transaction keeps the slow, failure-prone Gemini call from holding it open. supabase-py sends delete and insert as separate HTTP requests, which can't share a transaction. Truncate-rebuild leaves the cloud index empty if a run dies halfway. Since each document is all-or-nothing, one failure can't corrupt the others.
- **Date:** 2026-10-19

### Embedding model and task types
- **Decision:** `gemini-embedding-001` at 768 dims, task type `RETRIEVAL_DOCUMENT` for chunks and `RETRIEVAL_QUERY` for questions, L2-normalized before storing. Model name locked in CLAUDE.md.
- **Rejected alternatives:** No task type; `QUESTION_ANSWERING` for queries (kept as a lever for failure analysis); `gemini-embedding-2-preview`.
- **Rationale:** Questions and regulation text look nothing alike; task types train the model to place a question near its answer instead of near similar-looking text. Google requires manual normalization below 3072 dims; cosine doesn't need it, but it costs nothing and avoids a bug if we switch to inner product. Vectors from different models aren't comparable, so the model is locked; GA is more stable than preview. 
- **Date:** 2026-10-19

### Contextual header for embedding
- **Decision:** The text sent to Gemini is one header line (document title + paragraph or heading path) plus the chunk text. The `content` column stores the original text only.
- **Rejected alternatives:** Embed raw chunk text; LLM-generated contextual summaries per chunk.
- **Rationale:** Many eCFR chunks lose context on their own (a paragraph about 90 days of unemployment never says "OPT"). The header restores it deterministically at zero cost. LLM summaries add a call per chunk and make ingest non-deterministic.
- **Date:** 2026-10-19

### Chunk quality gate before embedding
- **Decision:** A dry-run mode chunks everything and writes a report without calling Gemini or touching the database. Empty chunks, duplicate (citation_key, chunk_index), and chunks over the ~800-token fallback size fail the check. The same check runs at the start of every real ingest and stops it before any Gemini call.
- **Rejected alternatives:** Inspecting chunks only after they are in the database.
- **Rationale:** Chunk quality caps hit@5, and bad chunks are cheaper to catch before paying for embeddings and writing to the index. A chunk over the fallback size means the fallback split itself failed. Token counts come from one local function shared by the chunker and the gate, so dry-run stays offline and both agree on the limit.
- **Date:** 2026-10-19

### Cloud mode for test 8 retired
- **Decision:** `--target opt-rag` no longer runs test 8; passing it exits with a message pointing to this entry. All tests run against local Supabase only.
- **Rejected alternatives:** Keeping the opt-in flag and relying on CLAUDE.md; letting test 8 check whether OPT-RAG already has documents before running.
- **Rationale:** Test 8 writes a temporary row to OPT-RAG. Once ingest puts real data there, a failed cleanup would leave a fake document next to real ones, and a written rule is easy to forget. The cloud check already passed in step 06. A row-count check would still connect to the production database just to decide not to run.
- **Amends:** Step 06 "Tests run against local Supabase; cloud check is opt-in".
- **Date:** 2026-10-19

### Study in the States citation keys
- **Decision:** Tier 2 `citation_key` is `<page-slug>` for text before the first heading, otherwise `<page-slug>#<heading path>`. The path joins h2 through h5 headings and accordion questions with `/`, each lowercased with runs of other characters turned into `-`. Each `<dt>`/`<dd>` pair in an accordion is its own section, with the question as its last path part. Fallback parts share the key and differ by `chunk_index`.
- **Rejected alternatives:** Positional keys (`#section-3`); numeric ids per heading; one chunk per accordion block; splitting on h2/h3 only.
- **Rationale:** You can check readable keys against the page by eye when verifying gold-set citations. Positional keys shift when someone adds a section above. FAQ questions are the closest text to real user questions, so each one gets its own embedding. With h2/h3 only, the 2,180-token "Practical Training for F Students" section on applying-for-practical-training mixed CPT, OPT, and STEM OPT across four size-based parts.
- **Known cost:** A reworded heading changes its key, so gold-set citations must be rechecked after any Tier 2 refetch.
- **Date:** 2026-10-19

### Navigation-only text is not a chunk
- **Decision:** Text before the first heading that consists only of in-page anchor links is dropped.
- **Rejected alternatives:** Keeping it as an intro chunk.
- **Rationale:** The STEM OPT FAQ intro ("Click on the ... topic of your choice") carries no content. If retrieved, it takes one of the five context slots.
- **Date:** 2026-10-19

### eCFR paragraph levels from marker style
- **Decision:** Ingest reads the level from the marker: `(10)` is level 2, `(ii)` 3, `(C)` 4, italic `(7)` 5, italic `(i)` 6. A paragraph that opens several levels inline gets the deepest key. Heading-only and `[Reserved]` paragraphs are not chunks. A skipped level or an unnumbered paragraph inside (f) raises an error.
- **Rejected alternatives:** Guessing the level from position; chunking every paragraph, including empty ones.
- **Rationale:** Only the italic markup separates levels 5 and 6 from levels 2 and 3 in the XML. A loud failure on a structure change is better than writing wrong citation keys.
- **Date:** 2026-10-19

### Small eCFR list items stay separate for the baseline
- **Decision:** Each eCFR list item stays its own chunk, even very short ones such as "(3) Is nonfrivolous."
- **Rejected alternatives:** Merging list items into their parent paragraph now.
- **Rationale:** This follows the 2026-09-01 one-paragraph-per-chunk rule, and the header line restores each item's path at embed time. Merging is a chunking experiment from the v2 backlog. Its value shows up only as a hit@5/MRR change against this baseline.
- **Date:** 2026-10-19

### Local token estimate shared by chunker and gate
- **Decision:** `count_tokens` counts `\w+|[^\w\s]` matches (words plus punctuation marks). The same function decides fallback splits, sizes the parts, and runs the gate's 800 limit.
- **Rejected alternatives:** Gemini `countTokens` API; tiktoken.
- **Rationale:** Dry-run must stay offline and deterministic, and the chunker and gate must agree exactly. `countTokens` is a network call, and tiktoken is another model's tokenizer plus a new dependency. The ~800 limit is approximate by design.
- **Date:** 2026-10-19

### Stored content keeps the section's own heading line
- **Decision:** `chunks.content` is the unit's original source text, including its own heading line (eCFR marker and heading; Study in the States heading or FAQ question). Only the embedding sees the synthetic header (document title + path).
- **Rejected alternatives:** Body text only; storing the full header in `content`.
- **Rationale:** The generator sees `content`, and an FAQ answer such as "Yes. You and your employer..." is ambiguous without its question. Storing the synthetic header would break "content stores the original text only".
- **Date:** 2026-10-19

### Gemini over REST with httpx
- **Decision:** `app/embedding.py` calls `batchEmbedContents` with httpx: batches of 100, key in the `x-goog-api-key` header, retries on 429/5xx with exponential backoff and the 429 `retryDelay` hint, up to 6 attempts.
- **Rejected alternatives:** google-genai SDK.
- **Rationale:** httpx is already a dependency and the call uses one endpoint. Owning the retry loop makes it testable with a mocked transport. Sending the key in a header keeps it out of URLs and error messages.
- **Date:** 2026-10-19

### Local ingest reads the database URL from supabase status
- **Decision:** `scripts/ingest.py --target local` (the default) reads `DB_URL` from `supabase status -o env`; `--target opt-rag` reads `DATABASE_URL` from `.env`.
- **Rejected alternatives:** One `DATABASE_URL` in `.env` for both, switched by hand.
- **Rationale:** The tests already work this way. With no local URL in `.env`, a forgotten edit cannot point a "local" run at OPT-RAG.
- **Date:** 2026-10-19

### Human-readable eCFR URL in `documents.url`
- **Decision:** For eCFR, `documents.url` stores the point-in-time page for `ecfr_issue_date` (e.g. `https://www.ecfr.gov/on/2026-10-01/title-8/section-214.2`). The manifest keeps the versioner API URL as the fetch record. Display code builds paragraph anchors from `citation_key`; the database does not store them.
- **Rejected alternatives:** Storing the versioner API XML URL; a `/current/` link.
- **Rationale:** The frontend shows `url` as the source link, and I open it to check gold-set citations, so a person must be able to read it. A `/current/` link can drift away from the indexed version.
- **Date:** 2026-10-19

### Ingest verifies raw file hashes
- **Decision:** Before chunking, ingest compares each raw file's SHA-256 with `raw_sha256` in the manifest. Any mismatch fails the gate for the whole run, dry-run included, before any Gemini call.
- **Rejected alternatives:** No check; warning and continuing.
- **Rationale:** The 2026-10-07 corpus snapshot ties the eval baseline to the manifest hashes. Without the check, a hand-edited raw file would reach the index silently.
- **Date:** 2026-10-19

### Sources removed from the manifest are not deleted
- **Decision:** Ingest only inserts and replaces documents listed in the manifest. A source dropped from the manifest keeps its rows.
- **Rejected alternatives:** Deleting documents that are absent from the manifest.
- **Rationale:** The v1 corpus is fixed at 14 sources, so deletion would add a destructive code path with no current use. Revisit if the source list changes.
- **Date:** 2026-10-19

## 2026-10-19 Frontend stack: React + Vite + TypeScript

**Decision**: The step 11 frontend is a React + Vite + TypeScript single page (question input, answer, cited sources) that calls the FastAPI `/query` endpoint. Claude Code scaffolds it; I write the input and answer components myself.
**Rejected alternatives**: Next.js (the CLAUDE.md stack until now: SSR, SEO, and file-based routing go unused on a single page, and its API routes overlap with the FastAPI backend)
**Rationale**: The frontend is one page with no SEO needs, so a client-side build that Vercel serves as static files is enough. Vite has fewer concepts than Next.js, so I can explain the choice in an interview. The page also gives me hands-on React and TypeScript practice, which full-stack interviews test directly.

## 2026-10-21 Step 08 retrieval and /query

**Decision**: psycopg direct connection for retrieval, sharing one connect() helper with ingest, with `search_path=public,extensions` set on the connection. Query embedding reuses `app/embedding.py` with `RETRIEVAL_QUERY` and no contextual header. `retrieve(question, k)` and `generate(question, chunks)` are separate functions; `/query` composes them. Refusal is prompt-only, no distance threshold. `/query` returns `{answer, sources: [{label, citation_key, title, source_tier, url, distance}]}` with no chunk content. Model name, temperature (baseline 0) and top-k (5) come from env vars. Tests use fake vectors for SQL, mock Gemini for prompt and endpoint, and one live test behind a `live` marker.
**Rejected alternatives**: supabase client via an RPC function (adds a SQL function and a migration, splits retrieval logic across two places); schema-qualified operators in SQL or `ALTER ROLE` search_path (hard to read, or hidden in the database and easy to miss in a new environment); one function doing retrieval and generation together (eval would have to split it later); cosine distance threshold for refusal (no principled value, and it would mix with prompt-based refusal in the refusal experiment); returning chunk content in the response (larger payload, the frontend does not need it, eval calls `retrieve` directly).
**Rationale**: One connection setup for ingest and retrieval, one place to change k or the SQL. The retrieve/generate split lets step 10 compute hit@5 and MRR without the generator and run the bare-Gemini arm with the same prompt minus context. Prompt-only refusal keeps one variable for the baseline. The response carries citation_key for eval and url so a user can open the source and match the number in the answer.
**Note**: `app/ingest/store.py` still casts with `::extensions.vector`; it works and stays until ingest is next touched.
**Caught**: the live test hung for 2h51m because app/embedding.py slept for the full retryDelay Gemini returned on a 429 with no cap; fixed with a 60-second cap and 5-attempt limit. The live test also re-embedded all 266 chunks on every run, burning quota; it now uses the existing local data and skips when the corpus is missing. app/generation.py had the same uncapped retryDelay sleep; it now uses the same 60-second cap and a 5-attempt limit.

## Step 08: Retrieval and /query

### eCFR source links use the stored citation key as the anchor
- **Decision:** Tier 1 source URL is `documents.url + "#p-" + citation_key`, e.g. `.../section-214.2#p-214.2(f)(10)(ii)(A)`. Tier 2 URL is `documents.url` unchanged. Built in one Python function; no schema change.
- **Rejected alternatives:** `documents.url + "#p-214.2" + citation_key` with the prefix stripped from the key first.
- **Rationale:** Stored eCFR keys already start with `214.2`, and eCFR's paragraph anchors use the same `p-214.2(f)...` form, so the key goes in unchanged.
- **Caught:** The step 08 plan said `"#p-214.2" + citation_key` with example key `(f)(10)(ii)(A)`. Querying the local database before writing code showed stored keys look like `214.2(f)(10)(ii)(A)`, so the plan would have produced `#p-214.2214.2(f)...`. Fixed by using `"#p-" + citation_key`; expected result 5 now uses the stored key form.
- **Date:** 2026-10-21

### Source labels
- **Decision:** Tier 1 label is `[n] 8 CFR <citation_key>` (e.g. `[1] 8 CFR 214.2(f)(10)(ii)(A)`). Tier 2 label is `[n] <documents.title> <citation_key>`. The same string appears in the prompt and in the `/query` response.
- **Rejected alternatives:** `[n] <documents.title> <citation_key>` for both tiers.
- **Rationale:** The 2026-09-01 prompt decision already used the form [1] 8 CFR 214.2(f)(10)(ii)(A). The Tier 1 title is the whole section name, so it adds nothing a reader cannot get from the citation key, and repeating a 200-character title five times per prompt only adds tokens. Tier 2 keeps the title because its citation key is a heading slug that does not identify the page on its own.
- **Date:** 2026-10-21

### Generation model pinned to `gemini-3.6-flash`
- **Decision:** `GEMINI_GENERATION_MODEL=gemini-3.6-flash`, temperature 0, both from env vars. The generator raises if the reply's `modelVersion` differs from the configured model.
- **Rejected alternatives:** `gemini-2.5-flash` (returns 404 "no longer available to new users"; 2.5-pro and 2.5-flash-lite too); a versioned id such as `gemini-2.5-flash-001` (none exist in the API); `gemini-3.8-flash` (newest, less settled; moved to the v2 backlog as an upgrade experiment); `gemini-3.7-flash` (503 high demand when probed).
- **Rationale:** A model name can be served by a newer model: a request to `gemini-3.5-flash` came back with `modelVersion` `gemini-3.6-flash`. The eval baseline must not change models silently, so a mismatch fails loudly. `gemini-3.6-flash` answered as itself.
- **Caught:** Probing `generateContent` before writing code showed the first choice, `gemini-2.5-flash`, is unavailable, and that `gemini-3.5-flash` is silently redirected. Fixed by pinning `gemini-3.6-flash` and adding the `modelVersion` check.
- **Date:** 2026-10-21

### The API server reads DATABASE_URL from the process environment only
- **Decision:** The server reads settings from the process environment, then `.env`, except `DATABASE_URL`, which comes from the process environment only. Locally it is set from `supabase status`; in deployment it is a secret.
- **Rejected alternatives:** Reading `DATABASE_URL` from `.env`.
- **Rationale:** `.env`'s `DATABASE_URL` points at OPT-RAG. Same reasoning as Step 07 "Local ingest reads the database URL from supabase status": a local run cannot reach OPT-RAG by accident.
- **Date:** 2026-10-21

### Ingest caches embeddings in a local file keyed by content hash
- **Decision:** Ingest keys each text by the sha256 of the exact string sent to the API (contextual header included) and stores vectors in `data/cache/embeddings.jsonl`, which is gitignored. The cache is read before calling Gemini; misses go to the API and are appended.
- **Rejected alternatives:** Re-embedding the whole corpus on every database reset; storing vectors in git.
- **Rationale:** The corpus is frozen, so its vectors never change. Four full re-embeds in one day exhausted the free-tier quota.
- **Date:** 2026-10-21

### Embedding cache key includes model settings; long retry hints give up at once
- **Decision:** The cache key is the sha256 of model, dimensions, task type, and text (supersedes "keyed by content hash" above). Loading the cache skips a line that is not valid JSON, lacks a field, or holds a vector that is not 768 long, with a logged warning. `embed()` appends each batch to the cache as soon as it returns. Embedding and generation share one retry helper, `wait_to_retry` in `app/embedding.py`: a `retryDelay` hint over 60 seconds raises `RetryDelayTooLong` without sleeping, a hint of 60 seconds or less is slept plus a 1-second buffer (so at most 61 seconds per wait), and no hint means exponential backoff. The helper also tracks the total slept for one request and raises instead of a sleep that would push it past 120 seconds. 5 attempts at most. `GeminiEmbedder` and `GeminiGenerator` re-raise `RetryDelayTooLong` as `EmbeddingError` / `GenerationError` with the same message, so a too-long retry delay surfaces as the class's own error.
- **Rejected alternatives:** Key by text only (a changed model, size, or task type would silently reuse old vectors); failing the whole load on one bad line; caching only after every batch of a call succeeds; sleeping a capped 60 seconds on a long hint (a daily-quota 429 then held a `/query` request about 4 minutes per call before failing anyway); separate copies of the retry delay logic in embedding and generation; sleeping exactly the hint with no buffer; letting `RetryDelayTooLong` escape both classes; passing the caller's error class into the helper so it raises that class directly; a per-wait cap with no total cap.
- **Rationale:** A cached vector is only valid for the settings that produced it, and an embedding experiment must change one variable without stale vectors mixed in. An interrupted run must not leave a cache that breaks every later ingest, and vectors already paid for must not be lost. A hint over 60 seconds cannot be satisfied within the retry budget, so waiting only delays the error. The hint is the shortest wait Gemini asks for; retrying right at it risks one more 429 that spends an attempt, and 1 second is a small price per retry. Wrapping keeps one error type per class for this failure, so callers that catch `EmbeddingError` or `GenerationError` (ingest, the eval runner) do not need to know about the helper; the helper stays free of caller types. A single-hint cap still let one `/query` call sleep up to 4 minutes per stage (4 waits of 61 seconds, for the query embedding and again for generation); a total cap bounds the whole request.
- **Caught:** A code review found that one half-written cache line made `load_cache` raise before any document was processed, so every later ingest failed until the file was deleted; that the key ignored task type and model; and that the 60-second cap was only tested on the hint path. A second review found that the per-hint cap with the buffer still allowed 244 seconds of sleep per call; the 120-second total cap fixes it. Fixed as above; tests now assert exact sleep values and call counts, and changing 5 attempts to 6 or the 60-second limit to 3600 fails them.
- **Date:** 2026-10-22

## 2026-10-22 Gold set v1: drafting and freeze workflow

**Decision**: Gold set v1 has 41 hand-written questions: 11 single-fact, 6 multi-hop, 6 scenario, 5 neutral/leading pairs, and 8 refusal items (3 out-of-scope, 3 near-miss, 2 time-sensitive). Questions come from what classmates and I asked or wanted to know about OPT; some cover situations I have not reached yet. Questions are written in Notion and exported to evals/questions_v1.csv. Claude Code drafts reference answers by reading data/raw directly, as a short answer, a verbatim source quote, and citation keys. Items the corpus cannot answer are marked NOT_IN_CORPUS and I decide whether to relabel them as near-miss or drop them. Refusal items carry no reference answer or citation and count only toward refusal accuracy, not Factual correctness, hit@5 or MRR. Every citation key must exist in the local chunker output, and every quote must match the corpus text verbatim. I review drafts in a Claude Doc; the verified set is written to evals/gold_v1.jsonl and frozen.
**Rejected alternatives**: drafting answers by running opt-rag itself (the system under test would produce its own ground truth and inflate scores); drafting with Gemini (same family as the generator, so reference wording would favor both opt-rag and the bare Gemini arm); filling corpus gaps from model knowledge (a correct answer grounded in the corpus would be scored wrong); CSV as the frozen format (citation_keys is a list; JSONL keeps one item per line and shows clean diffs); reviewing drafts back in Notion (quote and answer would not sit side by side).
**Rationale**: Ground truth has to come from the corpus and from a model outside the system under test. Deterministic checks on keys and quotes catch drafting errors before any LLM judge sees the set.
**Caught**: Review of the question table found a duplicate qid (two Q29 rows) and inconsistent pair_id values (P01-L, P02-N style or empty), which would have broken pair matching for answer stability; both fixed; a validation test for them is part of step 09a. It also found four questions resting on one paragraph (STEM OPT unemployment carryover); Q14 was replaced with a different multi-hop question.
