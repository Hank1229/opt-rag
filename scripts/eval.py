"""Entry point for the step 10 eval CLI; the code lives in app/evals/cli.py.

Usage: uv run --group eval python scripts/eval.py run --arm {opt-rag,bare,both} --runs N [--limit N] --run-id NAME
       uv run --group eval python scripts/eval.py summary --run-id NAME
"""

import sys

from app.evals.cli import main

if __name__ == "__main__":
    sys.exit(main())
