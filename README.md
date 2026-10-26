# opt-rag

A minimal RAG service over F-1/OPT regulations: documents go into Supabase pgvector, and each query retrieves the relevant passages for Gemini to answer from.

The goal is to show that I can design a RAG pipeline that can be evaluated, and use eval numbers to justify every design decision: why the chunks are cut this way, why this top-k, why that prompt was replaced.

Stack: Python 3.12, FastAPI, uv, Gemini API, Supabase (pgvector).

Current state: fetch scripts and a raw corpus snapshot are done (eCFR 8 CFR 214.2 at issue date 2026-09-14, 13 Study in the States pages); the API only has `GET /health`.

## Frontend

React + Vite + TypeScript single page in `frontend/`. It calls the FastAPI `/query` endpoint directly (no Vite proxy).

```sh
cd frontend
npm install        # install
npm run dev        # dev server on http://localhost:5173
npm test           # Vitest, fetch mocked
npm run typecheck  # tsc --noEmit
```

Environment variables:

- `VITE_API_URL` (frontend, read at build/dev time from `frontend/.env` or the shell): base URL of the API. Default `http://localhost:8000`.
- `CORS_ALLOWED_ORIGINS` (backend, in `.env` or the process environment): comma-separated browser origins allowed to call the API, e.g. `http://localhost:5173`. Unset, no origin gets CORS headers and the browser blocks the frontend's requests.
