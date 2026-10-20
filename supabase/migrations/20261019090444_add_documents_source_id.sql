-- Step 07: stable source id on documents, so re-ingest finds the same row.
-- Design: DECISIONS.md, Step 07 "Document identity on re-ingest".
-- NOT NULL without a default: run only while documents is empty.

alter table public.documents
  add column source_id text not null unique;
