# CLAUDE.md

## What this project is

opt-rag: a RAG QA system over F-1/OPT regulations, built in 14 days as an
interview portfolio piece. The point is not the app itself but the eval
story: every design decision must be explainable and every improvement
must show up as a number.

Stack: FastAPI + Supabase pgvector + Gemini (embedding and generation) +
Ragas + Langfuse + Next.js frontend. Deploy: Fly.io/Railway + Vercel.

## Locked decisions (do not change without asking)

- Corpus: two tiers. Tier 1 = full 8 CFR 214.2(f) via eCFR API.
  Tier 2 = Study in the States student pages from a fixed URL list.
  Fetch scripts + manifest (per file: tier, url, final_url, path,
  fetched_at, bytes, raw_sha256, plus content_sha256 for Tier 2;
  top level: ecfr_issue_date), raw files in data/raw/, committed.
- Chunking: structure-aware. Tier 1 splits on paragraph hierarchy,
  paragraph ID in metadata as citation key. Tier 2 splits on h2/h3.
  Paragraphs over ~800 tokens fall back to fixed-size splits keeping
  the parent ID.
- Embedding: Gemini, truncated to 768 dims (MRL). Cosine distance,
  vector_cosine_ops.
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

- Hank writes no code through you without reviewing the diff. Explain
  what changed and why in plain terms; he must be able to defend every
  line in an interview.
- One variable per experiment. Never bundle a chunking change with a
  prompt change.
- Do not install packages, create databases, or add schema fields
  beyond what the current step needs.
- Never write eval questions. Draft reference answers and citations
  only when Hank explicitly asks, for questions he wrote, in the
  format: short answer + verbatim source quote + citation.
- After any decision-level discussion, output a DECISIONS.md entry:
  Decision / Rejected alternatives / Rationale / Date.
- Any report, plan, or summary longer than a screen goes into a Claude
  Doc; give Hank the link instead of pasting it in the terminal. If
  Claude Docs is unavailable, write it to /tmp/<topic>.md and say so.
- All files, comments, and docs in English.
- Code comments: file header states what the file does, important
  functions get one brief line, skip comments that restate the code.

## Current state

- Skeleton done: uv, FastAPI /health, .env.example, first commit made.
- Fetch scripts and raw corpus snapshot done (eCFR 8 CFR 214.2 at
  issue date 2026-10-01, 13 Study in the States pages).
- Next: Supabase schema, then ingest.
