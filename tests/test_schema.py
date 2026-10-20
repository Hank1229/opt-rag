"""Step 06 schema tests: tables, constraints, cascade, cosine distance, RLS and grants.

Numbered tests map to Hank's expected results 1-8. Tests marked "extra" are
edge cases added by Claude. Vectors are synthetic; no Gemini calls.
"""

import httpx
import pytest
from psycopg import errors

from helpers import (
    EMBEDDING_DIMS,
    chunk_count,
    insert_chunk,
    insert_document,
    unit_vector,
    vector_literal,
)


# 1. Migration on an empty database: tables exist, pgvector enabled, RLS on both.
def test_01_migration_creates_tables_extension_and_rls(db):
    tables = db.execute(
        """
        select c.relname, c.relrowsecurity
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r'
          and c.relname in ('documents', 'chunks')
        """
    ).fetchall()
    assert dict(tables) == {"documents": True, "chunks": True}

    extension = db.execute("select 1 from pg_extension where extname = 'vector'").fetchone()
    assert extension is not None


# 2. 768 dims accepted; 767 and 3072 rejected.
def test_02_embedding_must_have_768_dims(db):
    document_id = insert_document(db)
    insert_chunk(db, document_id, [0.1] * 768, chunk_index=0)
    assert chunk_count(db, document_id) == 1

    for bad_dims in (767, 3072):
        with pytest.raises(errors.DataException, match="dimensions"):
            with db.transaction():
                insert_chunk(db, document_id, [0.1] * bad_dims, chunk_index=1)
    assert chunk_count(db, document_id) == 1


# 3a. Duplicate (document_id, citation_key, chunk_index) rejected, count unchanged.
def test_03a_duplicate_chunk_key_rejected(db):
    document_id = insert_document(db)
    insert_chunk(db, document_id, unit_vector(0), citation_key="214.2(f)(10)", chunk_index=0)

    with pytest.raises(errors.UniqueViolation):
        with db.transaction():
            insert_chunk(db, document_id, unit_vector(1), citation_key="214.2(f)(10)", chunk_index=0)
    assert chunk_count(db, document_id) == 1


# 3b. Same citation_key with different chunk_index (split paragraph) both insert.
def test_03b_same_citation_key_different_index_allowed(db):
    document_id = insert_document(db)
    insert_chunk(db, document_id, unit_vector(0), citation_key="214.2(f)(10)", chunk_index=0)
    insert_chunk(db, document_id, unit_vector(1), citation_key="214.2(f)(10)", chunk_index=1)
    assert chunk_count(db, document_id) == 2


# 4. Deleting a document deletes its chunks.
def test_04_delete_document_cascades_to_chunks(db):
    document_id = insert_document(db)
    insert_chunk(db, document_id, unit_vector(0), chunk_index=0)
    insert_chunk(db, document_id, unit_vector(1), chunk_index=1)

    db.execute("delete from documents where id = %s", (document_id,))
    assert chunk_count(db, document_id) == 0


# 5. v and 2v are both at the top of a cosine-distance query for v, distance ~0.
# The orthogonal and opposite vectors are Claude's additions so "top" means something.
def test_05_cosine_distance_ignores_vector_length(db):
    document_id = insert_document(db)
    v = [0.0] * EMBEDDING_DIMS
    v[0], v[1] = 0.6, 0.8
    v_id = insert_chunk(db, document_id, v, citation_key="v", chunk_index=0)
    v2_id = insert_chunk(db, document_id, [2 * x for x in v], citation_key="2v", chunk_index=0)
    insert_chunk(db, document_id, unit_vector(2), citation_key="orthogonal", chunk_index=0)
    insert_chunk(db, document_id, [-x for x in v], citation_key="opposite", chunk_index=0)

    rows = db.execute(
        """
        select id, embedding <=> %s::vector as distance
        from chunks
        order by distance
        """,
        (vector_literal(v),),
    ).fetchall()

    assert {rows[0][0], rows[1][0]} == {v_id, v2_id}
    assert rows[0][1] == pytest.approx(0, abs=1e-6)
    assert rows[1][1] == pytest.approx(0, abs=1e-6)
    assert rows[2][1] == pytest.approx(1, abs=1e-6)
    assert rows[3][1] == pytest.approx(2, abs=1e-6)


# 6. version_date is required. Every other NOT NULL column is supplied, so the
# error can only come from version_date.
def test_06_document_requires_version_date(db):
    with pytest.raises(errors.NotNullViolation, match="version_date"):
        db.execute(
            """
            insert into documents (source_id, source_tier, title, url)
            values ('test-no-date', 'ecfr', 'No date', 'https://example.test/no-date')
            """
        )


# 7. source_tier is case-sensitive: 'eCFR' rejected, 'ecfr' and 'sits' accepted.
def test_07_source_tier_check(db):
    with pytest.raises(errors.CheckViolation):
        with db.transaction():
            insert_document(db, source_tier="eCFR")

    insert_document(db, source_tier="ecfr", url="https://example.test/ecfr")
    insert_document(db, source_tier="sits", url="https://example.test/sits")


# Extra (Claude): source_id is required.
def test_extra_document_requires_source_id(db):
    with pytest.raises(errors.NotNullViolation, match="source_id"):
        db.execute(
            """
            insert into documents (source_tier, title, url, version_date)
            values ('ecfr', 'No id', 'https://example.test/no-id', '2026-10-01')
            """
        )


# Extra (Claude): two documents cannot share a source_id.
def test_extra_source_id_unique(db):
    insert_document(db, source_id="ecfr-214.2f")
    with pytest.raises(errors.UniqueViolation):
        insert_document(db, source_id="ecfr-214.2f", url="https://example.test/other")


# Extra (Claude): a chunk pointing to a missing document is rejected.
def test_extra_chunk_requires_existing_document(db):
    with pytest.raises(errors.ForeignKeyViolation):
        insert_chunk(db, -1, unit_vector(0))


# Extra (Claude): NULL embedding is rejected.
def test_extra_embedding_not_null(db):
    document_id = insert_document(db)
    with pytest.raises(errors.NotNullViolation):
        db.execute(
            """
            insert into chunks (document_id, citation_key, chunk_index, content)
            values (%s, '214.2(f)(1)', 0, 'No embedding')
            """,
            (document_id,),
        )


# Extra (Claude): only service_role holds table privileges among Data API roles.
def test_extra_grants_only_to_service_role(db):
    rows = db.execute(
        """
        select grantee, table_name, privilege_type
        from information_schema.role_table_grants
        where table_schema = 'public'
          and table_name in ('documents', 'chunks')
          and grantee in ('anon', 'authenticated', 'service_role')
        """
    ).fetchall()
    grantees = {grantee for grantee, _, _ in rows}
    assert grantees == {"service_role"}
    for table in ("documents", "chunks"):
        privileges = {p for g, t, p in rows if t == table}
        assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= privileges


# 8. Publishable key gets a permission error on chunks; secret key reads the data.
# Local stack only; the OPT-RAG mode was retired in step 07 (DECISIONS.md,
# "Cloud mode for test 8 retired"). Writes one marked test document through the
# secret key and deletes it afterwards.
def test_08_data_api_access_by_key(env):
    rest = f"{env['SUPABASE_URL']}/rest/v1"
    secret = {"apikey": env["SUPABASE_SECRET_KEY"]}
    publishable = {"apikey": env["SUPABASE_PUBLISHABLE_KEY"]}
    secret_with_return = {**secret, "Prefer": "return=representation"}

    response = httpx.post(
        f"{rest}/documents",
        headers=secret_with_return,
        json={
            "source_id": "pytest-step-06-access-check",
            "source_tier": "ecfr",
            "title": "pytest step 06 access check (safe to delete)",
            "url": "https://example.test/pytest-step-06",
            "version_date": "2026-10-01",
        },
    )
    assert response.status_code == 201, response.text
    document_id = response.json()[0]["id"]
    try:
        response = httpx.post(
            f"{rest}/chunks",
            headers=secret_with_return,
            json={
                "document_id": document_id,
                "citation_key": "214.2(f)(1)",
                "chunk_index": 0,
                "content": "pytest access check",
                "embedding": vector_literal(unit_vector(0)),
            },
        )
        assert response.status_code == 201, response.text
        chunk_id = response.json()[0]["id"]

        denied = httpx.get(f"{rest}/chunks", params={"select": "id"}, headers=publishable)
        assert denied.status_code in (401, 403), denied.text
        assert denied.json()["code"] == "42501"  # insufficient_privilege

        allowed = httpx.get(
            f"{rest}/chunks", params={"select": "id", "id": f"eq.{chunk_id}"}, headers=secret
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json() == [{"id": chunk_id}]
    finally:
        httpx.delete(f"{rest}/documents", params={"id": f"eq.{document_id}"}, headers=secret)
