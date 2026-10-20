"""Step 07 ingest tests: chunking, quality gate, dry-run, and re-ingest into local Supabase.

Numbered tests map to Hank's expected results 1-10 (7-10: follow-up 1). Tests marked "extra" are
edge cases added by Claude. Embeddings come from FakeEmbedder; no Gemini calls.
Tests never modify data/raw/; edits happen on a copy (the raw_copy fixture).
"""

import hashlib
import html as html_lib
import json
import re
from datetime import date, datetime, timezone

import pytest

from app.ingest import chunking
from app.ingest.chunking import MAX_TOKENS, Chunk, Document, check_chunks, load_documents
from app.ingest.cli import main
from conftest import RAW_DIR
from helpers import EMBEDDING_DIMS, FakeEmbedder

FAQ_PAGE = "sits-stem-opt-frequently-asked-questions"
PRACTICAL_PAGE = "sits-applying-for-practical-training"
ECFR_PAGE_URL = "https://www.ecfr.gov/on/2026-10-01/title-8/section-214.2"
STATUS_PAGE = "sits-maintaining-status"
REMOVED_HEADING = "Annual Vacation for F-1 Students"


@pytest.fixture
def run_ingest(tmp_path):
    """Run the ingest CLI against local Supabase; returns its exit code."""

    def run(raw_dir=RAW_DIR, embedder=None, *extra_args):
        args = ["--target", "local", "--raw-dir", str(raw_dir), "--report", str(tmp_path / "report.json")]
        return main([*args, *extra_args], embedder=embedder or FakeEmbedder())

    return run


def read_manifest(raw_dir=RAW_DIR) -> dict:
    return json.loads((raw_dir / "manifest.json").read_text())


def table_counts(conn) -> tuple[int, int]:
    return (
        conn.execute("select count(*) from documents").fetchone()[0],
        conn.execute("select count(*) from chunks").fetchone()[0],
    )


def chunk_rows(conn, source_id=None, exclude=None) -> list[tuple]:
    """(source_id, citation_key, chunk_index, content, embedding) rows, in a stable order."""
    return conn.execute(
        """
        select d.source_id, c.citation_key, c.chunk_index, c.content, c.embedding::text
        from chunks c join documents d on d.id = c.document_id
        where (%(only)s::text is null or d.source_id = %(only)s)
          and (%(skip)s::text is null or d.source_id <> %(skip)s)
        order by d.source_id, c.citation_key, c.chunk_index
        """,
        {"only": source_id, "skip": exclude},
    ).fetchall()


def version_dates(conn) -> dict[str, date]:
    return dict(conn.execute("select source_id, version_date from documents").fetchall())


def document(raw_dir, source_id) -> Document:
    return next(d for d in load_documents(raw_dir) if d.source_id == source_id)


def edit_raw_file(raw_dir, relative_path, text) -> None:
    """Write a raw file in a corpus copy and record its new hash in the copy's manifest."""
    (raw_dir / relative_path).write_text(text)
    manifest = read_manifest(raw_dir)
    for entry in manifest["entries"]:
        if entry["path"] == relative_path:
            entry["raw_sha256"] = hashlib.sha256((raw_dir / relative_path).read_bytes()).hexdigest()
    (raw_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def remove_h2_section(raw_dir, relative_path, heading) -> None:
    """Delete one <h2> and everything up to the next <h2> from an HTML file in a corpus copy."""
    html = (raw_dir / relative_path).read_text()
    pattern = re.compile(rf"<h2>{re.escape(heading)}</h2>.*?(?=<h2)", re.S)
    edited, count = pattern.subn("", html)
    assert count == 1
    edit_raw_file(raw_dir, relative_path, edited)


# 1. Ingest into local Supabase: one documents row per manifest source, version_date
# from the manifest, every embedding 768 dims.
def test_01_ingest_loads_every_manifest_source(ingest_db, run_ingest):
    manifest = read_manifest()
    assert run_ingest() == 0

    expected = {}
    for entry in manifest["entries"]:
        if entry["tier"] == 1:
            expected[entry["source_id"]] = date.fromisoformat(manifest["ecfr_issue_date"])
        else:
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
            expected[entry["source_id"]] = fetched_at.astimezone(timezone.utc).date()

    assert table_counts(ingest_db)[0] == len(manifest["entries"])
    assert version_dates(ingest_db) == expected

    dims = ingest_db.execute("select distinct vector_dims(embedding) from chunks").fetchall()
    assert dims == [(EMBEDDING_DIMS,)]


# 2. eCFR chunks come only from paragraph (f).
def test_02_ecfr_chunks_only_from_paragraph_f(ingest_db, run_ingest):
    assert run_ingest() == 0
    rows = ingest_db.execute(
        """
        select c.citation_key, c.content
        from chunks c join documents d on d.id = c.document_id
        where d.source_tier = 'ecfr'
        """
    ).fetchall()

    assert rows
    assert all(key.startswith("214.2(f)") for key, _ in rows)
    # Extra (Claude): opening text of (e) and (g) is not in any chunk either.
    for neighbor in ("Treaty traders and investors", "Representatives to international organizations"):
        assert not any(neighbor in content for _, content in rows)


# 3. Running ingest twice gives the same row counts as running it once.
def test_03_reingest_is_idempotent(ingest_db, run_ingest):
    assert run_ingest() == 0
    once = table_counts(ingest_db)
    rows_once = chunk_rows(ingest_db)

    assert run_ingest() == 0
    assert table_counts(ingest_db) == once
    # Extra (Claude): the rows themselves are identical too, not just the counts.
    assert chunk_rows(ingest_db) == rows_once


# 4. Edge: a heading section removed from one page disappears on re-ingest; other
# documents' chunks are unchanged.
def test_04_removed_section_is_gone_after_reingest(ingest_db, run_ingest, raw_copy):
    removed = [
        c for c in document(raw_copy, STATUS_PAGE).chunks if c.header.endswith(REMOVED_HEADING)
    ]
    assert removed, "the section to remove must exist before the edit"

    assert run_ingest(raw_copy) == 0
    others_before = chunk_rows(ingest_db, exclude=STATUS_PAGE)

    remove_h2_section(raw_copy, "sits/maintaining-status.html", REMOVED_HEADING)
    assert run_ingest(raw_copy) == 0

    expected = [(c.citation_key, c.chunk_index, c.content) for c in document(raw_copy, STATUS_PAGE).chunks]
    actual = [row[1:4] for row in chunk_rows(ingest_db, source_id=STATUS_PAGE)]
    assert sorted(actual) == sorted(expected)

    removed_lines = [line for c in removed for line in c.content.splitlines()[1:] if line]
    all_content = [row[3] for row in chunk_rows(ingest_db)]
    for line in removed_lines:
        assert not any(line in content for content in all_content)

    assert chunk_rows(ingest_db, exclude=STATUS_PAGE) == others_before


# 5. Edge: Gemini fails on one document. It keeps its old chunks and version_date,
# the others still update, the failure is printed, and the run exits non-zero.
def test_05_embedding_failure_keeps_old_document(ingest_db, run_ingest, raw_copy, capsys):
    assert run_ingest(raw_copy) == 0
    old_rows = chunk_rows(ingest_db, source_id=STATUS_PAGE)
    old_date = version_dates(ingest_db)[STATUS_PAGE]
    assert old_rows

    # A refetch on a later day: every Study in the States page gets a new version date.
    manifest = read_manifest(raw_copy)
    for entry in manifest["entries"]:
        if entry["tier"] == 2:
            entry["fetched_at"] = "2026-10-18T12:00:00Z"
    (raw_copy / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    capsys.readouterr()

    failing = FakeEmbedder(fail_if=lambda text: text.startswith("Maintaining Status"))
    assert run_ingest(raw_copy, failing) != 0

    output = capsys.readouterr()
    assert STATUS_PAGE in output.out + output.err

    assert chunk_rows(ingest_db, source_id=STATUS_PAGE) == old_rows
    dates = version_dates(ingest_db)
    assert dates[STATUS_PAGE] == old_date
    for entry in manifest["entries"]:
        if entry["tier"] == 2 and entry["source_id"] != STATUS_PAGE:
            assert dates[entry["source_id"]] == date(2026, 10, 18)


# 6a. Edge: dry-run makes no Gemini call and no database write, and writes a chunk
# report with per-document counts, lengths, citation_keys, and previews.
def test_06a_dry_run_writes_report_only(ingest_db, run_ingest, tmp_path):
    embedder = FakeEmbedder()
    assert run_ingest(RAW_DIR, embedder, "--dry-run") == 0

    assert embedder.calls == 0
    assert table_counts(ingest_db) == (0, 0)

    report = json.loads((tmp_path / "report.json").read_text())
    manifest_ids = {e["source_id"] for e in read_manifest()["entries"]}
    assert {d["source_id"] for d in report["documents"]} == manifest_ids
    assert report["problems"] == []
    for doc in report["documents"]:
        assert doc["chunk_count"] == len(doc["chunks"]) > 0
        assert 0 < doc["min_tokens"] <= doc["max_tokens"] <= MAX_TOKENS
        assert doc["citation_keys"]
        for chunk in doc["chunks"]:
            assert chunk["preview"].startswith(chunk["header"])


# 6b. Edge: an empty chunk, a duplicate (citation_key, chunk_index), or a chunk over
# the size limit makes dry-run exit non-zero, and a real ingest stops before Gemini.
@pytest.mark.parametrize("problem", ["empty", "duplicate", "oversized"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_06b_quality_gate_blocks_bad_chunks(ingest_db, run_ingest, monkeypatch, problem, dry_run):
    real_documents = load_documents(RAW_DIR)

    def with_bad_chunk(raw_dir):
        doc = real_documents[0]
        first = doc.chunks[0]
        bad = {
            "empty": Chunk(first.citation_key, 99, first.header, "   "),
            "duplicate": Chunk(first.citation_key, first.chunk_index, first.header, "copy"),
            "oversized": Chunk(first.citation_key, 99, first.header, "word " * (MAX_TOKENS + 1)),
        }[problem]
        doc.chunks.append(bad)
        return real_documents

    monkeypatch.setattr(chunking, "load_documents", with_bad_chunk)
    embedder = FakeEmbedder()
    args = ["--dry-run"] if dry_run else []

    assert run_ingest(RAW_DIR, embedder, *args) != 0
    assert embedder.calls == 0
    assert table_counts(ingest_db) == (0, 0)


# Extra (Claude): the gate reports each kind of problem on its own.
def test_extra_check_chunks_names_each_problem():
    doc = Document("doc", "sits", "Title", "https://example.test", date(2026, 10, 1), [
        Chunk("doc#a", 0, "Title > A", "fine text"),
        Chunk("doc#a", 0, "Title > A", "duplicate key"),
        Chunk("doc#b", 0, "Title > B", ""),
        Chunk("doc#c", 0, "Title > C", "word " * (MAX_TOKENS + 1)),
    ])
    problems = "\n".join(check_chunks([doc]))
    assert "duplicate" in problems
    assert "empty" in problems
    assert "over" in problems


# Extra (Claude): a page with two identical headings produces duplicate keys, which
# the gate catches in a real ingest before any Gemini call.
def test_extra_duplicate_heading_stops_real_ingest(ingest_db, run_ingest, raw_copy):
    path = "sits/maintaining-status.html"
    html = (raw_copy / path).read_text()
    edit_raw_file(raw_copy, path, html.replace(
        f"<h2>{REMOVED_HEADING}</h2>",
        f"<h2>{REMOVED_HEADING}</h2><p>First copy.</p><h2>{REMOVED_HEADING}</h2>",
    ))
    embedder = FakeEmbedder()
    assert run_ingest(raw_copy, embedder) != 0
    assert embedder.calls == 0
    assert table_counts(ingest_db) == (0, 0)


# Extra (Claude): every manifest entry has a source_id, and they are unique.
def test_extra_manifest_ids():
    ids = [e["source_id"] for e in read_manifest()["entries"]]
    assert len(ids) == len(set(ids))
    assert "ecfr-214.2f" in ids
    assert all(i.startswith(("ecfr-", "sits-")) for i in ids)


# Extra (Claude): deeper eCFR levels use the italic markers, e.g. (C)(7)(i); all 20
# numbered paragraphs of (f) are present; heading-only and [Reserved] paragraphs
# are not chunks.
def test_extra_ecfr_keys_follow_paragraph_hierarchy():
    chunks = document(RAW_DIR, "ecfr-214.2f").chunks
    keys = {c.citation_key for c in chunks}
    for key in (
        "214.2(f)(1)(i)",
        "214.2(f)(5)(vii)(A)(1)",
        "214.2(f)(10)(ii)(C)(7)(i)",
        "214.2(f)(10)(ii)(E)",
        "214.2(f)(15)(ii)(A)(1)",
        "214.2(f)(20)",
    ):
        assert key in keys
    for n in range(1, 21):
        assert any(k == f"214.2(f)({n})" or k.startswith(f"214.2(f)({n})(") for k in keys), n
    assert "214.2(f)" not in keys
    assert not any(c.content.endswith("[Reserved]") for c in chunks)


# Extra (Claude): each accordion question on the FAQ page is its own section.
def test_extra_faq_questions_are_separate_sections():
    chunks = document(RAW_DIR, FAQ_PAGE).chunks
    headers = [c.header for c in chunks]
    assert any(h.endswith("Students > Will my training be evaluated during my STEM OPT opportunity?") for h in headers)
    assert any(h.endswith("Cap-Gap Extensions and H-1B Visas > What is a \"Cap-Gap\" extension?") for h in headers)
    assert len({c.citation_key for c in chunks}) >= 19  # 19 questions on the page


# Extra (Claude): an oversized section splits into parts under the limit that keep
# the parent citation_key and header, numbered from 0.
def test_extra_fallback_split_keeps_parent_key():
    sentence = "The student must report any change to the DSO within 10 days. "
    text = "Heading\n" + sentence * 200
    parts = chunking.make_chunks("page#heading", "Title > Heading", text)

    assert len(parts) > 1
    assert [p.chunk_index for p in parts] == list(range(len(parts)))
    assert {p.citation_key for p in parts} == {"page#heading"}
    assert {p.header for p in parts} == {"Title > Heading"}
    assert all(chunking.count_tokens(p.content) <= MAX_TOKENS for p in parts)
    assert " ".join(p.content for p in parts).split() == text.split()


# Extra (Claude): a database error after the old chunks were deleted rolls the whole
# document back. A 767-dim vector passes the embedder but fails the vector(768) column.
def test_extra_database_error_rolls_back_document(ingest_db, run_ingest, raw_copy):
    assert run_ingest(raw_copy) == 0
    old_rows = chunk_rows(ingest_db, source_id=STATUS_PAGE)

    class ShortVectorEmbedder(FakeEmbedder):
        def embed(self, texts):
            vectors = super().embed(texts)
            if texts[0].startswith("Maintaining Status"):
                vectors[-1] = vectors[-1][:-1]
            return vectors

    assert run_ingest(raw_copy, ShortVectorEmbedder()) != 0
    assert chunk_rows(ingest_db, source_id=STATUS_PAGE) == old_rows


# --- Follow-up 1 --------------------------------------------------------------------


# 7. Edge: a raw file whose bytes don't match its manifest raw_sha256 stops both
# dry-run and real ingest, naming the file, before any Gemini call or write.
@pytest.mark.parametrize("dry_run", [True, False])
def test_07_raw_hash_mismatch_fails_gate(ingest_db, run_ingest, raw_copy, capsys, dry_run):
    path = "sits/working-in-the-united-states.html"
    (raw_copy / path).write_text((raw_copy / path).read_text() + "<!-- edited -->")
    embedder = FakeEmbedder()
    args = ["--dry-run"] if dry_run else []

    assert run_ingest(raw_copy, embedder, *args) != 0
    output = capsys.readouterr()
    assert path in output.out + output.err
    assert embedder.calls == 0
    assert table_counts(ingest_db) == (0, 0)


def h4_segments(page_html: str) -> list[str]:
    """Text of each <h4> section in the page's <article> (to the next h2-h4), whitespace removed."""
    page_html = re.search(r"<article\b.*?</article>", page_html, re.S).group(0)
    starts = [m.start() for m in re.finditer(r"<h4\b", page_html)]
    ends = [m.start() for m in re.finditer(r"<h[234]\b", page_html)] + [len(page_html)]
    segments = []
    for start in starts:
        end = min(e for e in ends if e > start)
        text = html_lib.unescape(re.sub(r"<[^>]+>", "", page_html[start:end]))
        segments.append(re.sub(r"\s+", "", text))
    return segments


# 8. applying-for-practical-training: CPT, OPT, and STEM OPT each get their own key
# path, no chunk mixes text from two h4 sections, and the repeated "Application
# Steps" h5 headings get distinct keys.
def test_08_h4_h5_start_sections():
    chunks = document(RAW_DIR, PRACTICAL_PAGE).chunks
    keys = [c.citation_key for c in chunks]
    base = "applying-for-practical-training#practical-training-for-f-students/"
    for h4 in ("curricular-practical-training", "optional-practical-training", "stem-opt-extension"):
        assert any(k == base + h4 or k.startswith(base + h4 + "/") for k in keys), h4

    segments = h4_segments((RAW_DIR / "sits" / "applying-for-practical-training.html").read_text())
    assert len(segments) >= 3
    for chunk in chunks:
        lines = [re.sub(r"\s+", "", line.removeprefix("- ")) for line in chunk.content.splitlines()]
        # The page repeats some sentences word for word in several h4 sections; only
        # text found in exactly one section can tell which section a chunk came from.
        sources = set()
        for line in lines:
            found_in = {i for i, seg in enumerate(segments) if line in seg}
            if len(line) >= 40 and len(found_in) == 1:
                sources |= found_in
        assert len(sources) <= 1, chunk.citation_key

    page_html = (RAW_DIR / "sits" / "applying-for-practical-training.html").read_text()
    step_headings = len(re.findall(r"<h5[^>]*>\s*Application Steps\s*</h5>", page_html))
    step_keys = {k for k in keys if k.endswith("/application-steps")}
    assert step_headings >= 2
    assert len({k for k in step_keys if k.startswith(base)}) == step_headings


# 9. stem-opt-frequently-asked-questions: 19 chunks, every one a question; the
# anchor-link intro is gone.
def test_09_faq_page_is_only_question_chunks():
    chunks = document(RAW_DIR, FAQ_PAGE).chunks
    assert len(chunks) == 19
    for chunk in chunks:
        assert chunk.citation_key.startswith("stem-opt-frequently-asked-questions#")
        question = chunk.header.split(" > ")[-1]
        assert question.rstrip("”\"").endswith("?")
        assert chunk.content.splitlines()[0] == question
    assert not any("topic of your choice" in c.content for c in chunks)


# 10. The eCFR documents row points at the point-in-time page for 2026-10-01.
def test_10_ecfr_url_is_point_in_time_page(ingest_db, run_ingest):
    assert run_ingest() == 0
    url = ingest_db.execute("select url from documents where source_id = 'ecfr-214.2f'").fetchone()[0]
    assert url == ECFR_PAGE_URL
    # Extra (Claude): the manifest keeps the versioner API URL.
    manifest_url = next(e["url"] for e in read_manifest()["entries"] if e["source_id"] == "ecfr-214.2f")
    assert manifest_url.startswith("https://www.ecfr.gov/api/versioner/")


def page(body: str) -> str:
    return (
        '<html><body><article><h2><span class="field--name-title">Test Page</span></h2>'
        f'<div class="field--name-body">{body}</div></article></body></html>'
    )


# Extra (Claude): the anchor-link rule is general: an intro made of in-page links
# (with at most a lead-in ending in a colon) is dropped; an intro with real text or
# an outside link is kept.
@pytest.mark.parametrize(
    ("intro", "dropped"),
    [
        ('<p><a href="#a">A</a> | <a href="#b">B</a></p>', True),
        ('<p>Jump to a topic: <a href="#a">A</a>, <a href="#b">B</a>.</p>', True),
        ('<ul><li><a href="#a">A</a></li><li><a href="#b">B</a></li></ul>', True),
        ('<p>Students must report changes. See <a href="#a">A</a>.</p>', False),
        ('<p>Topics: <a href="https://example.test">outside</a>, <a href="#b">B</a></p>', False),
        ('<p>Plain intro text with no links at all.</p>', False),
    ],
)
def test_extra_anchor_only_intro_rule(intro, dropped):
    _, sections = chunking.sits_sections(page(intro + "<h2>Topic</h2><p>Body text.</p>"), "test-page")
    keys = [key for key, _, _ in sections]
    assert ("test-page" not in keys) == dropped
    assert "test-page#topic" in keys
