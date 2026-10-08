"""Tier 1: fetch 8 CFR 214.2 from the eCFR API into data/raw/ecfr/.

The API's smallest unit is a section, so the whole of 214.2 is saved untouched;
extracting paragraph (f) is the chunker's job. Re-running overwrites the file
and the tier 1 manifest entry.

Usage: uv run python scripts/fetch_ecfr.py
"""

import httpx

from corpus import RAW_DIR, make_client, manifest_entry, update_manifest

API = "https://www.ecfr.gov/api/versioner/v1"
HIERARCHY = {"chapter": "I", "subchapter": "B", "part": "214", "section": "214.2"}
OUT = RAW_DIR / "ecfr" / "8-cfr-214.2.xml"


def latest_issue_date(client: httpx.Client) -> str:
    titles = client.get(f"{API}/titles.json").raise_for_status().json()["titles"]
    return next(t["latest_issue_date"] for t in titles if t["number"] == 8)


def main() -> None:
    with make_client() as client:
        issue_date = latest_issue_date(client)
        # eCFR answers 406 to uncompressed requests; httpx sends Accept-Encoding: gzip by default.
        resp = client.get(f"{API}/full/{issue_date}/title-8.xml", params=HIERARCHY)
        resp.raise_for_status()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(resp.content)
    update_manifest(1, [manifest_entry(1, resp, OUT)], ecfr_issue_date=issue_date)
    print(f"issue date {issue_date}: {len(resp.content):,} bytes -> {OUT.relative_to(RAW_DIR)}")


if __name__ == "__main__":
    main()
