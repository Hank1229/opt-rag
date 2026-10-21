# CLAUDE.md

## What this project is

opt-rag: a RAG QA system over F-1/OPT regulations, built as an interview
portfolio piece. The point is not the app itself but the eval story:
every design decision must be explainable and every improvement must
show up as a number.

Stack: FastAPI + Supabase pgvector + Gemini (embedding and generation) +
Ragas + React + Vite + TypeScript frontend. Deploy: Fly.io/Railway + Vercel.

## Locked decisions (do not change without asking)

- Corpus: two tiers. Tier 1 = full 8 CFR 214.2(f) via eCFR API.
  Tier 2 = Study in the States student pages from a fixed URL list.
  Fetch scripts + manifest (per file: source_id, tier, url, final_url, path,
  fetched_at, bytes, raw_sha256, plus content_sha256 for Tier 2;
  top level: ecfr_issue_date), raw files in data/raw/, committed.
- Chunking: structure-aware. Tier 1 splits on paragraph hierarchy,
  paragraph ID in metadata as citation key. Tier 2: h2-h5 headings and
  each accordion question start a section.
  Paragraphs over ~800 tokens fall back to fixed-size splits keeping
  the parent ID.
- Embedding: Gemini `gemini-embedding-001`, truncated to 768 dims
  (MRL), L2-normalized. Task type RETRIEVAL_DOCUMENT for chunks,
  RETRIEVAL_QUERY for questions. Cosine distance, vector_cosine_ops.
- Retrieval: top-k = 5 baseline.
- Query endpoint: /query (the name used in code, docs, and diagrams).
- Generation prompt: labeled sources, mandatory citations, refusal
  when context lacks the answer, fixed non-legal-advice disclaimer,
  English-only answers.
- Eval dataset: Hank writes every question by hand, seeded from real
  student questions, including refusal questions and paired neutral /
  preference-leading questions. An LLM may draft reference answers and
  citations; Hank verifies each against the source, then the set
  freezes. Frozen set never changes; if it must, the baseline is void
  and reruns.

## Working rules

- This session is for implementation only. Concept explanations and
  design discussion happen in a separate place. Keep chat explanations
  short unless Hank asks for more; he will bring questions elsewhere.
- Work in small steps. Before each step, Hank gives a short list of
  expected results, written as plain sentences ("input -> expected
  result"). Turn each one into a test first, then implement. Do not
  change his expected results. You may add extra edge cases, but label
  them as yours in the test name or a comment.
- pytest is an allowed dev dependency; tests live in tests/.
- Tests run against local Supabase only. `pytest --target opt-rag` is
  retired and exits without running anything (DECISIONS.md, Step 07
  "Cloud mode for test 8 retired").
- After each step, report:
  1. files changed and the diff
  2. the exact command Hank should run to check it himself, and what
     output to expect
  3. test results
  4. a short list of ways this code could fail (edge cases not
     covered, assumptions it makes, inputs that would break it)
- Never overwrite a manual edit Hank made. If his edit conflicts with
  your change, stop and ask.
- One variable per experiment. Never bundle a chunking change with a
  prompt change.
- Do not install packages, create databases, or add schema fields
  beyond what the current step needs.
- Any migration that creates a table must revoke all privileges from
  anon and authenticated and grant only what the backend needs to
  service_role, following
  supabase/migrations/20261017004311_create_documents_and_chunks.sql.
  Do not use Supabase's default grant template (it grants anon
  select). If a step adds a SQL function called through the Data API,
  revoke execute from public, anon, and authenticated and grant it to
  service_role.
- Never write eval questions. Draft reference answers and citations
  only when Hank explicitly asks, for questions he wrote, in the
  format: short answer + verbatim source quote + citation.
- After any decision-level discussion, output a DECISIONS.md entry:
  Decision / Rejected alternatives / Rationale / Date. Add a "Caught"
  line only when a test or review actually caught a problem: what it
  was and how it was fixed.
- The v2 backlog lives in DECISIONS.md. Something missing from
  CLAUDE.md or the code is not cancelled; check DECISIONS.md before
  treating it as removed.
- Any report, plan, or summary longer than a screen goes into a Claude
  Doc; give Hank the link instead of pasting it in the terminal. If
  Claude Docs is unavailable, write it to /tmp/<topic>.md and say so.
- All files, comments, and docs in English.
- Code comments: file header states what the file does, important
  functions get one brief line, skip comments that restate the code.
- Load the pragmatic-code-style skill before writing or editing any
  code, and apply it to the diff you produce. Do not refactor files
  outside the current step's scope.
- Before reporting a step as done, re-read your own diff against that
  skill and fix what it flags.

## Current state

- Skeleton done: uv, FastAPI /health, .env.example, first commit made.
- Fetch scripts and raw corpus snapshot done (eCFR 8 CFR 214.2 at
  issue date 2026-10-01, 13 Study in the States pages).
- Steps 06-08 done: Supabase schema, ingest, retrieval + /query.
- Next: step 09 (eval dataset).
