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
  Fetch script + manifest (url, fetched_at, content hash), raw files
  in data/raw/, committed.
- Chunking: structure-aware. Tier 1 splits on paragraph hierarchy,
  paragraph ID in metadata as citation key. Tier 2 splits on h2/h3.
  Paragraphs over ~800 tokens fall back to fixed-size splits keeping
  the parent ID.
- Embedding: Gemini, truncated to 768 dims (MRL). Cosine distance,
  vector_cosine_ops.
- Retrieval: top-k = 5 baseline.
- Generation prompt: labeled sources, mandatory citations, refusal
  when context lacks the answer, fixed non-legal-advice disclaimer,
  English-only answers.
- Eval dataset: LLM drafts candidates, Hank verifies every citation
  by hand, then the set freezes. Frozen set never changes; if it must,
  the baseline is void and reruns.

## Working rules

- Hank writes no code through you without reviewing the diff. Explain
  what changed and why in plain terms; he must be able to defend every
  line in an interview.
- One variable per experiment. Never bundle a chunking change with a
  prompt change.
- Do not install packages, create databases, or add schema fields
  beyond what the current step needs.
- Do not generate eval questions or ground truths on your own
  initiative. Drafting happens only when Hank explicitly asks, in the
  format: question + short answer + verbatim source quote + citation.
- After any decision-level discussion, output a DECISIONS.md entry:
  Decision / Rejected alternatives / Rationale / Date.
- All files, comments, and docs in English.
- Code comments: file header states what the file does, important
  functions get one brief line, skip comments that restate the code.

## Current state

- Skeleton done: uv, FastAPI /health, .env.example, first commit made.
- Next: fetch scripts for the two corpus tiers, then Supabase schema,
  then ingest.
