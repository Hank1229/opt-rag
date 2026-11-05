"""Wait between retries of a Gemini request: the reply's retryDelay hint, else exponential backoff.

Shared by the embedder and the generator; each decides on its own which errors to retry.
"""

import random
import re

MAX_BACKOFF_SECONDS = 60
MAX_TOTAL_SLEEP_SECONDS = 120  # per request, across all retries
RETRY_DELAY_RE = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')


class RetryDelayTooLong(RuntimeError):
    """The wait Gemini asks for, or the request's total wait, is past the limit."""


def wait_to_retry(attempt: int, reply: str, sleep, slept: float) -> float:
    """Sleep before the next attempt and return the request's new total slept: Gemini's retryDelay
    hint plus 1 s if the reply has one, else backoff. Raises instead of sleeping when the wait would
    exceed 61 s (a daily quota) or push the total past 120 s: no retry would succeed in time."""
    hint = RETRY_DELAY_RE.search(reply)
    delay = float(hint.group(1)) + 1 if hint else backoff_seconds(attempt)
    if hint and delay > MAX_BACKOFF_SECONDS + 1:
        raise RetryDelayTooLong(f"Gemini asked to retry in {delay - 1:g} s, a wait over the {MAX_BACKOFF_SECONDS + 1} s limit: {reply[:300]}")
    if slept + delay > MAX_TOTAL_SLEEP_SECONDS:
        raise RetryDelayTooLong(
            f"retrying in {delay:g} s would bring the wait to {slept + delay:g} s, past the {MAX_TOTAL_SLEEP_SECONDS} s total: {reply[:300]}"
        )
    sleep(delay)
    return slept + delay


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter: about 2, 4, 8, 16, 32, then capped at 60 seconds."""
    return min(MAX_BACKOFF_SECONDS, 2**attempt) + random.uniform(0, 1)
