-- Step 06: documents + chunks tables for retrieval, with RLS and backend-only access.
-- Design: DECISIONS.md, "Step 06: Database schema".

create extension if not exists vector with schema extensions;

create table public.documents (
  id bigint generated always as identity primary key,
  source_tier text not null check (source_tier in ('ecfr', 'sits')),
  title text not null,
  url text not null,
  -- eCFR: official issue date. Study in the States: fetch date.
  version_date date not null
);

-- No vector index on embedding: exact cosine scan at this corpus size.
create table public.chunks (
  id bigint generated always as identity primary key,
  document_id bigint not null references public.documents (id) on delete cascade,
  citation_key text not null,
  chunk_index integer not null,
  content text not null,
  embedding extensions.vector(768) not null,
  unique (document_id, citation_key, chunk_index)
);

-- RLS on with no policies: only roles that bypass RLS (service_role) can read or write.
alter table public.documents enable row level security;
alter table public.chunks enable row level security;

-- Local Supabase auto-exposes new tables to anon and authenticated through default
-- privileges; the OPT-RAG project does not. Revoke explicitly so both environments
-- end up the same, then grant only to service_role (the role the secret key uses).
revoke all on table public.documents, public.chunks from anon, authenticated;
grant select, insert, update, delete on table public.documents, public.chunks to service_role;
