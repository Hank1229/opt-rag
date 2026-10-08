"""Tier 2: fetch a fixed list of Study in the States student pages into data/raw/sits/.

Raw HTML is saved untouched. Each page also gets a content hash over the
visible text of its <article>, so a site redeploy that only changes
boilerplate (hashed CSS file names, view IDs) does not look like a corpus
change. All pages are fetched before anything is written, so a failed run
never leaves a half-updated corpus.

Usage: uv run python scripts/fetch_sits.py
"""

import html
import re
import time

from corpus import RAW_DIR, make_client, manifest_entry, sha256, update_manifest

BASE = "https://studyinthestates.dhs.gov"
PATHS = [
    # OPT core
    "/students/work/working-in-the-united-states",
    "/students/training-opportunities-in-the-united-states",
    "/students/work/applying-for-practical-training",
    "/students/complete/h-1b-status-and-the-cap-gap-extension",
    # STEM OPT
    "/stem-opt-hub/additional-resources/stem-opt-extension-overview",
    "/stem-opt-hub/for-students/students-determining-stem-opt-extension-eligibility",
    "/stem-opt-hub/for-students/students-stem-opt-reporting-requirements",
    "/stem-opt-hub/additional-resources/stem-opt-frequently-asked-questions",
    "/stem-opt-hub/for-students/students-and-the-form-i-983",
    "/stem-opt-hub/additional-resources/form-i-983-overview",
    # Maintaining status (prerequisites for most OPT questions)
    "/students/maintaining-status",
    "/students/study/full-course-of-study",
    "/students/study/traveling-as-an-f-or-m-student",
]
OUT_DIR = RAW_DIR / "sits"
DELAY_SECONDS = 1

ARTICLE_RE = re.compile(r"<article\b[^>]*>(.*?)</article>", re.S)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def article_text(page: str) -> str:
    """Visible text of the page's <article>, tags stripped and whitespace collapsed."""
    match = ARTICLE_RE.search(page)
    if match is None:
        raise ValueError("no <article> element")
    text = TAG_RE.sub(" ", SCRIPT_STYLE_RE.sub(" ", match.group(1)))
    return " ".join(html.unescape(text).split())


def main() -> None:
    pages = []
    with make_client() as client:
        for i, path in enumerate(PATHS):
            if i:
                time.sleep(DELAY_SECONDS)
            resp = client.get(BASE + path)
            resp.raise_for_status()
            pages.append((path, resp, article_text(resp.text)))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for path, resp, text in pages:
        out = OUT_DIR / f"{path.rsplit('/', 1)[-1]}.html"
        out.write_bytes(resp.content)
        entries.append(manifest_entry(2, resp, out, content_sha256=sha256(text.encode())))
        print(f"{len(text):>7,} text chars  {out.relative_to(RAW_DIR)}")
    update_manifest(2, entries)


if __name__ == "__main__":
    main()
