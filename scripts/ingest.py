"""Entry point for the ingest CLI; the code lives in app/ingest/cli.py.

Usage: uv run python scripts/ingest.py [--dry-run] [--target local|opt-rag]
"""

import sys

from app.ingest.cli import main

if __name__ == "__main__":
    sys.exit(main())
