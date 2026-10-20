"""Turn the committed raw corpus into chunks, plus the quality gate that checks them.

Tier 1 (eCFR): only paragraph (f) of 8 CFR 214.2, one chunk per numbered
paragraph, keyed by its paragraph ID, e.g. 214.2(f)(10)(ii)(C).
Tier 2 (Study in the States): one chunk per h2-h5 section, and one per accordion
question; keyed by page slug plus heading path. Text before the first heading
that is only in-page anchor links is dropped.
Raw files are checked against the manifest's raw_sha256 before any chunking.
Sections over MAX_TOKENS fall back to size-based splits that keep the parent key.
Everything here is offline and deterministic: same raw files in, same chunks out.
Design: CLAUDE.md "Chunking"; DECISIONS.md, Step 07.
"""

import hashlib
import html
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

MAX_TOKENS = 800
ECFR_PAGE_URL = "https://www.ecfr.gov/on/{issue_date}/title-8/section-214.2"
TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def count_tokens(text: str) -> int:
    """Local token estimate (words plus punctuation marks), shared by the chunker and the gate."""
    return len(TOKEN_RE.findall(text))


@dataclass
class Chunk:
    citation_key: str
    chunk_index: int
    header: str  # document title + paragraph or heading path; embedded, not stored
    content: str  # original source text, stored in chunks.content

    @property
    def embed_text(self) -> str:
        return f"{self.header}\n{self.content}"


@dataclass
class Document:
    source_id: str
    source_tier: str
    title: str
    url: str
    version_date: date
    chunks: list[Chunk]


def read_manifest(raw_dir: Path) -> dict:
    return json.loads((raw_dir / "manifest.json").read_text())


def check_raw_hashes(raw_dir: Path) -> list[str]:
    """One message per raw file that is missing or whose bytes differ from raw_sha256."""
    problems = []
    for entry in read_manifest(raw_dir)["entries"]:
        path = raw_dir / entry["path"]
        if not path.is_file():
            problems.append(f"{entry['path']}: raw file missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["raw_sha256"]:
            problems.append(
                f"{entry['path']}: raw_sha256 mismatch (manifest {entry['raw_sha256'][:12]}..., file {actual[:12]}...)"
            )
    return problems


def load_documents(raw_dir: Path) -> list[Document]:
    """Chunk every source listed in raw_dir/manifest.json."""
    manifest = read_manifest(raw_dir)
    documents = []
    for entry in manifest["entries"]:
        text = (raw_dir / entry["path"]).read_text()
        if entry["tier"] == 1:
            tier = "ecfr"
            title, sections = ecfr_sections(text)
            version = date.fromisoformat(manifest["ecfr_issue_date"])
            # The manifest keeps the API URL as the fetch record; people get the page.
            url = ECFR_PAGE_URL.format(issue_date=manifest["ecfr_issue_date"])
        else:
            tier = "sits"
            title, sections = sits_sections(text, Path(entry["path"]).stem)
            version = datetime.fromisoformat(entry["fetched_at"]).astimezone(timezone.utc).date()
            url = entry["url"]
        chunks = [chunk for key, header, body in sections for chunk in make_chunks(key, header, body)]
        documents.append(Document(entry["source_id"], tier, title, url, version, chunks))
    return documents


def make_chunks(citation_key: str, header: str, text: str) -> list[Chunk]:
    parts = [text] if count_tokens(text) <= MAX_TOKENS else split_oversized(text)
    return [Chunk(citation_key, i, header, part) for i, part in enumerate(parts)]


def split_oversized(text: str, limit: int = MAX_TOKENS) -> list[str]:
    """Fallback split into near-equal parts of at most `limit` tokens.

    Cuts at line breaks first, then sentence ends, then plain whitespace, so no
    word is cut in half.
    """
    units = []  # (text, starts_new_line, tokens)
    for line in text.split("\n"):
        pieces = [line] if count_tokens(line) <= limit else _split_line(line, limit)
        units += [(piece, i == 0, count_tokens(piece)) for i, piece in enumerate(pieces)]

    total = sum(tokens for _, _, tokens in units)
    target = math.ceil(total / math.ceil(total / limit))
    parts, current, current_tokens = [], "", 0
    for piece, new_line, tokens in units:
        if current and current_tokens + tokens > target:
            parts.append(current)
            current, current_tokens = "", 0
        separator = "" if not current else ("\n" if new_line else " ")
        current += separator + piece
        current_tokens += tokens
    if current:
        parts.append(current)
    return parts


def _split_line(line: str, limit: int) -> list[str]:
    pieces = []
    for sentence in re.split(r"(?<=[.;:?!])\s+", line):
        if count_tokens(sentence) <= limit:
            pieces.append(sentence)
            continue
        words, window = sentence.split(), []
        for word in words:
            if window and count_tokens(" ".join(window + [word])) > limit:
                pieces.append(" ".join(window))
                window = []
            window.append(word)
        pieces.append(" ".join(window))
    return pieces


def check_chunks(documents: list[Document]) -> list[str]:
    """Quality gate: one message per problem; an empty list means the corpus may be embedded."""
    problems = []
    seen_ids = set()
    for doc in documents:
        if doc.source_id in seen_ids:
            problems.append(f"{doc.source_id}: duplicate source_id")
        seen_ids.add(doc.source_id)
        if not doc.chunks:
            problems.append(f"{doc.source_id}: no chunks")
        seen_keys = set()
        for chunk in doc.chunks:
            where = f"{doc.source_id} {chunk.citation_key} [{chunk.chunk_index}]"
            if not chunk.content.strip():
                problems.append(f"{where}: empty chunk")
            key = (chunk.citation_key, chunk.chunk_index)
            if key in seen_keys:
                problems.append(f"{where}: duplicate (citation_key, chunk_index)")
            seen_keys.add(key)
            tokens = count_tokens(chunk.content)
            if tokens > MAX_TOKENS:
                problems.append(f"{where}: {tokens} tokens, over the {MAX_TOKENS}-token limit")
    return problems


# --- Tier 1: eCFR ----------------------------------------------------------------

ECFR_SECTION = "214.2"
ECFR_PARAGRAPH = "f"
# A paragraph marker: "(10)", "(ii)", "(C)", or italic "(<I>7</I>)", "(<I>i</I>)".
MARKER_RE = re.compile(r"\((?:<I>(?P<italic>[0-9a-z]+)</I>|(?P<plain>[0-9a-zA-Z]+))\)")
HEADING_RE = re.compile(r"\s*<I>(?P<heading>.*?)</I>", re.S)
CHAIN_GAP_RE = re.compile(r"—|\s+")
ROMAN_RE = re.compile(r"[ivxl]+")
# The first marker of each level; a heading can only be followed inline by one of these.
FIRST_MARKER = {2: "1", 3: "i", 4: "A", 5: "1", 6: "i"}
EMPTY_BODIES = {"", "[Reserved]"}


def marker_level(token: str, italic: bool) -> int:
    """Paragraph depth in 8 CFR: (f) 1, (10) 2, (ii) 3, (C) 4, italic (7) 5, italic (i) 6."""
    if italic:
        return 5 if token.isdigit() else 6
    if token.isdigit():
        return 2
    if token.isupper():
        return 4
    # Inside (f) lowercase markers below level 1 are roman numerals.
    return 3 if ROMAN_RE.fullmatch(token) else 1


def plain_text(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", markup)).split())


def paragraph_chain(markup: str) -> tuple[list[tuple[int, str, str | None]], int]:
    """Leading markers of one <P> as [(level, token, heading)], and where the body starts.

    "(5) <I>Period of stay</I>—(i) <I>General.</I> An F-1 ..." gives
    [(2, "5", "Period of stay"), (3, "i", "General")].
    """
    chain = []
    pos = 0
    match = MARKER_RE.match(markup)
    while match:
        token = match.group("italic") or match.group("plain")
        level = marker_level(token, match.group("italic") is not None)
        pos = match.end()
        heading_match = HEADING_RE.match(markup, pos)
        heading = None
        if heading_match:
            heading = plain_text(heading_match.group("heading")).rstrip(".") or None
            pos = heading_match.end()
        chain.append((level, token, heading))
        if heading is None:
            break
        gap = CHAIN_GAP_RE.match(markup, pos)
        match = MARKER_RE.match(markup, gap.end()) if gap else None
        if match:
            next_token = match.group("italic") or match.group("plain")
            next_level = marker_level(next_token, match.group("italic") is not None)
            if next_level != level + 1 or FIRST_MARKER.get(next_level) != next_token:
                match = None
    return chain, pos


def inner_markup(element: ET.Element) -> str:
    markup = ET.tostring(element, encoding="unicode")
    return markup[markup.index(">") + 1 : markup.rindex("<")].strip()


def ecfr_sections(xml_text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Title and (citation_key, header, text) sections for paragraph (f) of the section XML."""
    root = ET.fromstring(xml_text)
    title = None
    sections = []
    stack = []  # [(level, token, heading)] from (f) down to the current paragraph
    for element in root.findall("P"):  # direct children only: skips the contents tables
        markup = inner_markup(element)
        chain, body_start = paragraph_chain(markup)
        top = chain[0] if chain else None
        if top and top[0] == 1:
            if top[1] == ECFR_PARAGRAPH:
                title = f"8 CFR {ECFR_SECTION}({ECFR_PARAGRAPH}) {top[2]}"
            elif title:
                break  # reached (g)
        if title is None:
            continue
        if not chain:
            raise ValueError(f"unnumbered paragraph inside ({ECFR_PARAGRAPH}): {plain_text(markup)[:80]}")

        for level, token, heading in chain:
            while stack and stack[-1][0] >= level:
                stack.pop()
            if level != (stack[-1][0] + 1 if stack else 1):
                raise ValueError(f"paragraph level skipped at ({token}): {plain_text(markup)[:80]}")
            stack.append((level, token, heading))

        if plain_text(markup[body_start:]).strip(" —") in EMPTY_BODIES:
            continue  # heading-only or [Reserved]: nothing to retrieve
        key = ECFR_SECTION + "".join(f"({token})" for _, token, _ in stack)
        labels = [f"({token}) {heading}" if heading else f"({token})" for _, token, heading in stack[1:]]
        sections.append((key, " > ".join([title, *labels]), plain_text(markup)))

    if title is None:
        raise ValueError(f"paragraph ({ECFR_PARAGRAPH}) not found")
    return title, sections


# --- Tier 2: Study in the States -------------------------------------------------

INLINE_TAGS = {"a", "abbr", "b", "code", "em", "i", "small", "span", "strong", "sub", "sup", "u"}
SKIP_TAGS = {"script", "style", "img", "iframe", "button"}
SECTION_LEVELS = {"h2": 2, "h3": 3, "h4": 4, "h5": 5}
LINK_SEPARATORS_RE = re.compile(r"[\s,;|·•/–—-]+")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def clean(text: str) -> str:
    return " ".join(text.split())


def is_in_page_link(tag: Tag) -> bool:
    return tag.name == "a" and (tag.get("href") or "").startswith("#")


def is_navigation(outside_links: str, in_page_links: int, other_links: int) -> bool:
    """A line made only of in-page anchor links, optionally after a lead-in ending in ":".

    `outside_links` is the line's text minus the in-page links' own text.
    """
    if in_page_links == 0 or other_links:
        return False
    rest = LINK_SEPARATORS_RE.sub(" ", outside_links).strip(" .")
    if not rest:
        return True
    return rest.endswith(":") and len(rest.split()) <= 20 and not re.search(r"[.!?]\s", rest)


def sits_sections(page: str, slug: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Title and (citation_key, header, text) sections of one page's article body."""
    soup = BeautifulSoup(page, "html.parser")
    article = soup.find("article")
    title = clean(article.find(class_="field--name-title").get_text())
    walker = _SitsWalker()
    walker.walk(article.find(class_="field--name-body"))

    sections = []
    for path, lines, navigation in walker.sections:
        has_body = len(lines) > (1 if path else 0)  # line 0 of a titled section is its heading
        if not has_body:
            continue
        if not path and all(navigation):
            continue  # intro that only links to headings further down the page
        key = slug + ("#" + "/".join(slugify(p) for p in path) if path else "")
        sections.append((key, " > ".join([title, *path]), "\n".join(lines)))
    return title, sections


class _Line:
    """Inline content collected for one output line, with what its links point to."""

    def __init__(self):
        self.text: list[str] = []
        self.outside_links: list[str] = []
        self.in_page_links = 0
        self.other_links = 0

    def add_string(self, text: str) -> None:
        self.text.append(text)
        self.outside_links.append(text)

    def add_inline(self, tag: Tag) -> None:
        links = ([tag] if tag.name == "a" else []) + tag.find_all("a")
        self.in_page_links += sum(1 for a in links if is_in_page_link(a))
        self.other_links += sum(1 for a in links if not is_in_page_link(a))
        self.text.append(tag.get_text())
        self.outside_links += [
            s for s in tag.find_all(string=True) if not s.find_parent(is_in_page_link)
        ]


class _SitsWalker:
    """Walks the body in document order, starting a section at each h2-h5 and each <dt>."""

    def __init__(self):
        self.headings: list[tuple[int, str]] = []
        # (heading path, lines, whether each body line is navigation-only)
        self.sections: list[tuple[list[str], list[str], list[bool]]] = []
        self._start([])  # text before the first heading

    def _start(self, path: list[str]) -> None:
        self.lines = [path[-1]] if path else []
        self.navigation: list[bool] = []
        self.sections.append((path, self.lines, self.navigation))

    def walk(self, node: Tag, prefix: str = "") -> None:
        line = _Line()
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                line.add_string(str(child))
            elif child.name == "br":
                line.add_string(" ")
            elif child.name in INLINE_TAGS and not child.find(lambda t: t.name not in INLINE_TAGS):
                line.add_inline(child)
            else:
                self._flush(line, prefix)
                line = _Line()
                self._block(child)
        self._flush(line, prefix)

    def _flush(self, line: _Line, prefix: str) -> None:
        text = clean("".join(line.text))
        if text:
            self.lines.append(prefix + text)
            self.navigation.append(
                is_navigation("".join(line.outside_links), line.in_page_links, line.other_links)
            )

    def _block(self, tag: Tag) -> None:
        if tag.name in SKIP_TAGS:
            return
        if tag.name in SECTION_LEVELS:
            text = clean(tag.get_text())
            if not text:
                return  # the site has a few empty <h3>s
            level = SECTION_LEVELS[tag.name]
            while self.headings and self.headings[-1][0] >= level:
                self.headings.pop()
            self.headings.append((level, text))
            self._start([t for _, t in self.headings])
        elif tag.name == "dl":
            # Accordion: each <dt> question is its own section; afterwards text
            # belongs to the enclosing heading's section again.
            enclosing = self.lines, self.navigation
            self.walk(tag)
            self.lines, self.navigation = enclosing
        elif tag.name == "dt":
            self._start([t for _, t in self.headings] + [clean(tag.get_text())])
        elif tag.name == "li":
            self.walk(tag, prefix="- ")
        else:
            self.walk(tag)
