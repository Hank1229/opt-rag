# opt-rag

A minimal RAG service over F-1/OPT regulations: documents go into Supabase pgvector, and each query retrieves the relevant passages for Gemini to answer from.

The goal is to show that I can design a RAG pipeline that can be evaluated, and use eval numbers to justify every design decision: why the chunks are cut this way, why this top-k, why that prompt was replaced.

Stack: Python 3.12, FastAPI, uv, Gemini API, Supabase (pgvector).

Current state: fetch scripts and a raw corpus snapshot are done (eCFR 8 CFR 214.2 at issue date 2026-09-14, 13 Study in the States pages); the API only has `GET /health`.
