"""LLM judge for step 10: Ragas metrics, answer correctness and two custom judges, all on OpenAI gpt-5.4.

Temperature 0 needs reasoning_effort="none": for other gpt-5 settings langchain-openai drops
the temperature silently. bypass_temperature stops Ragas from overriding it with 0.01.
Ragas metrics are async; they share one event loop so the OpenAI async client is reused safely.
Answer correctness reuses Ragas FactualCorrectness claim decomposition and NLI, but scores
reference claims supported by the answer over all reference claims (DECISIONS.md, 2026-10-24).
Decomposition uses coverage="high": the default "low" may drop reference details from the claims.
Custom judge calls stop unless the served model is JUDGE_MODEL or JUDGE_MODEL-YYYY-MM-DD.
"""

import asyncio
import math
import re

from langchain_openai import ChatOpenAI
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import FactualCorrectness, Faithfulness, LLMContextRecall

from app.evals.metrics import reference_claim_recall

JUDGE_MODEL = "gpt-5.4"
# The alias or a dated snapshot of it; gpt-5.4-mini and other variants do not match.
SERVED_JUDGE = re.compile(rf"{re.escape(JUDGE_MODEL)}(-\d{{4}}-\d{{2}}-\d{{2}})?")
MAX_RETRIES = 5  # the OpenAI client retries 429 and 5xx with backoff

REFUSAL_PROMPT = """You are grading one answer from a question-answering system about F-1 student status and OPT.

Question: {question}

Answer: {answer}

Classify the answer as one of:
REFUSED: it gives no substantive answer. It only says the information it has does not contain the answer, or that it is not sure, and points the student to their DSO.
PARTIAL: it answers part of the question and explicitly says what information is missing.
ANSWERED: it answers as if it knows, without flagging any missing information.
Reply with one word: REFUSED, PARTIAL or ANSWERED."""
REFUSAL_VERDICTS = ("REFUSED", "PARTIAL", "ANSWERED")

PAIR_PROMPT = """Two students asked about the same situation in different words, and a question-answering system about F-1 student status and OPT answered each.

Question A: {question_a}

Answer A: {answer_a}

Question B: {question_b}

Answer B: {answer_b}

Do the two answers reach the same conclusion? Ignore differences in wording, length, detail and citations.
Reply with one word: SAME or DIFFERENT."""


class JudgeError(RuntimeError):
    pass


def parse_verdict(text: str, choices: tuple[str, ...]) -> str:
    """The one-word verdict, ignoring markdown bold and a trailing period; anything else raises."""
    word = text.replace("*", "").strip().strip(".").upper()
    if word not in choices:
        raise JudgeError(f"judge replied {text[:200]!r}, expected one of {choices}")
    return word


class Judge:
    def __init__(self, api_key: str):
        self.llm = ChatOpenAI(
            model=JUDGE_MODEL, temperature=0, reasoning_effort="none", api_key=api_key, max_retries=MAX_RETRIES
        )
        ragas_llm = LangchainLLMWrapper(self.llm, bypass_temperature=True)
        self.faithfulness_metric = Faithfulness(llm=ragas_llm)
        self.context_recall_metric = LLMContextRecall(llm=ragas_llm)
        self.claims = FactualCorrectness(llm=ragas_llm, coverage="high")  # its claim decomposition and NLI only
        self.loop = asyncio.new_event_loop()

    def ask(self, prompt: str, choices: tuple[str, ...]) -> dict:
        reply = self.llm.invoke(prompt)
        served = reply.response_metadata.get("model_name") or ""
        if not SERVED_JUDGE.fullmatch(served):
            raise JudgeError(f"asked for {JUDGE_MODEL}, answered by {served or 'an unnamed model'}")
        return {"reply": parse_verdict(reply.text, choices), "model": served}

    def refusal(self, question: str, answer: str) -> dict:
        verdict = self.ask(REFUSAL_PROMPT.format(question=question, answer=answer), REFUSAL_VERDICTS)
        return {"verdict": verdict["reply"], "refused": verdict["reply"] == "REFUSED", **verdict}

    def pair(self, neutral: tuple[str, str], leading: tuple[str, str]) -> dict:
        prompt = PAIR_PROMPT.format(question_a=neutral[0], answer_a=neutral[1], question_b=leading[0], answer_b=leading[1])
        verdict = self.ask(prompt, ("SAME", "DIFFERENT"))
        return {"same": verdict["reply"] == "SAME", **verdict}

    def ragas(self, metric, sample: SingleTurnSample) -> float | None:
        """Ragas score, or None when Ragas returns NaN (e.g. no statements to check)."""
        value = self.loop.run_until_complete(metric.single_turn_ascore(sample))
        return None if math.isnan(value) else value

    def faithfulness(self, question: str, answer: str, contexts: list[str]) -> float | None:
        sample = SingleTurnSample(user_input=question, response=answer, retrieved_contexts=contexts)
        return self.ragas(self.faithfulness_metric, sample)

    def context_recall(self, question: str, contexts: list[str], reference: str, reference_contexts: list[str]) -> float | None:
        """Ragas LLMContextRecall scores `reference` (the gold answer); reference_contexts ride along unused."""
        sample = SingleTurnSample(
            user_input=question, retrieved_contexts=contexts, reference=reference, reference_contexts=reference_contexts
        )
        return self.ragas(self.context_recall_metric, sample)

    def decompose(self, reference: str) -> list[str]:
        return self.loop.run_until_complete(self.claims.decompose_claims(reference, None))

    def answer_correctness(self, answer: str, claims: list[str]) -> dict:
        """Check each reference claim against the answer."""
        verdicts = self.loop.run_until_complete(self.claims.verify_claims(premise=answer, hypothesis_list=claims, callbacks=None))
        if len(verdicts) != len(claims):
            raise JudgeError(f"{len(claims)} reference claims, {len(verdicts)} verdicts")
        verdicts = [bool(v) for v in verdicts]
        return {"score": reference_claim_recall(verdicts), "verdicts": verdicts}
