"""Answer generation: the labeled-source prompt and one Gemini generateContent call over REST.

The four prompt elements are fixed by DECISIONS.md, 2026-09-01 "Generation prompt
structure". The model must answer as the configured version: a model name can be
served by a newer model, which would silently change an eval baseline.
"""

import json
import time

import httpx

from app.embedding import RetryDelayTooLong, wait_to_retry
from app.retrieval import Hit

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRY_STATUSES = {429, 503}
MAX_ATTEMPTS = 5
REFUSAL = (
    "The provided sources do not contain the answer to this question. "
    "Please ask your Designated School Official (DSO)."
)
DISCLAIMER = "This is an informational summary, not legal advice."
INSTRUCTIONS = f"""You answer questions about F-1 student status and OPT using only the numbered sources below.

Rules:
- Use only information from the sources. Do not add facts from your own knowledge.
- Cite the label of every source you rely on, for example [1] or [2][4].
- If the sources do not contain the answer, reply with this sentence instead of an answer: {REFUSAL}
- Answer in English, whatever language the question is in.
- End every reply with this line, word for word: {DISCLAIMER}"""


class GenerationError(RuntimeError):
    pass


def label(n: int, chunk: Hit) -> str:
    """Source label shared by the prompt and the /query response."""
    if chunk.source_tier == "ecfr":
        return f"[{n}] 8 CFR {chunk.citation_key}"
    return f"[{n}] {chunk.title} {chunk.citation_key}"


def build_prompt(question: str, chunks: list[Hit]) -> str:
    sources = "\n\n".join(f"{label(n, c)}\n{c.content}" for n, c in enumerate(chunks, 1))
    return f"{INSTRUCTIONS}\n\nSources:\n\n{sources}\n\nQuestion: {question}"


def generate(question: str, chunks: list[Hit], *, generator) -> str:
    """Answer from the given chunks; an empty list is the bare-Gemini eval arm."""
    return generator.complete(build_prompt(question, chunks))


class GeminiGenerator:
    def __init__(self, api_key: str, model: str, temperature: float, client=None, sleep=time.sleep):
        self.model = model
        self.temperature = temperature
        self.headers = {"x-goog-api-key": api_key}
        self.client = client or httpx.Client(timeout=180)
        self.sleep = sleep

    def complete(self, prompt: str) -> str:
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature},
        }
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = self.client.post(ENDPOINT.format(model=self.model), json=body, headers=self.headers)
            if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                break
            try:
                wait_to_retry(attempt, response.text, self.sleep)
            except RetryDelayTooLong as exc:
                raise GenerationError(str(exc)) from exc
        if response.status_code != 200:
            raise GenerationError(f"Gemini generation failed, HTTP {response.status_code}: {response.text[:300]}")
        reply = response.json()
        if reply.get("modelVersion") != self.model:
            raise GenerationError(f"asked for {self.model}, answered by {reply.get('modelVersion')}")
        candidates = reply.get("candidates") or [{}]
        if "content" not in candidates[0]:
            raise GenerationError(f"Gemini returned no answer: {json.dumps(reply)[:300]}")
        return "".join(part["text"] for part in candidates[0]["content"]["parts"] if not part.get("thought"))
