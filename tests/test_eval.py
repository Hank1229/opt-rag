"""Step 10 tests: deterministic eval metrics, resume, and the summary.

Numbered tests map to Hank's step 10 expected results:
1 hit@5 and MRR, 2 citation accuracy, 3 refuse items excluded from scored metrics,
4 resume without duplicates, 5 summary mean/min/max over 3 runs.
Tests marked "extra" are edge cases added by Claude.
Gemini, OpenAI and the database are all faked: no API calls, no Supabase.
"""

import hashlib
import json
import re
import subprocess
import sys

import numpy as np
import pytest

from app.evals.metrics import (
    bare_citations,
    citation_accuracy,
    hit_at_k,
    ANSWER_CORRECTNESS_LABEL,
    METRIC_VERSION,
    rag_citations,
    reciprocal_rank,
    reference_claim_recall,
    strip_disclaimer,
    unknown_keys,
)
from app.evals import cli
from app.evals.cli import frozen_gold_sha256, git_state, run_models, select
from app.evals.judge import JUDGE_MODEL, REFUSAL_PROMPT, REFUSAL_VERDICTS, Judge, JudgeError, parse_verdict
from app.evals.runner import BARE_INSTRUCTIONS, RateLimit, append_jsonl, arm_prompts, read_jsonl, run, score
from app.evals.summary import summarize
from app.generation import DISCLAIMER, INSTRUCTIONS
from app.gold import EVALS_README
from app.gold import GOLD as GOLD_FILE
from app.retrieval import Hit

GOLD = ["214.2(f)(10)", "214.2(f)(11)(i)(B)(2)"]
KNOWN = {
    "214.2(f)(10)": "Text of (f)(10)",
    "214.2(f)(11)(i)(B)(2)": "Text of (f)(11)(i)(B)(2)",
    "214.2(f)(5)(iv)": "Text of (f)(5)(iv)",
    "214.2(f)(10)(ii)(E)": "Text of (f)(10)(ii)(E)",
}
MODELS = {"generation_model": "gemini-test", "judge_model": "judge-test", "embedding_model": "embed-test"}
GIT = {"head": "a" * 40, "dirty": False}
GOLD_SHA256 = "d" * 64
CLAIMS = ["Claim A.", "Claim B."]


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def item(qid="Q1", expected="answer", category="Single-fact", pair_id="", keys=GOLD):
    return {
        "qid": qid,
        "question": f"Question {qid}?",
        "category": category,
        "expected": expected,
        "pair_id": pair_id,
        "reference_answer": "" if expected == "refuse" else f"Reference for {qid}.",
        "citation_keys": [] if expected == "refuse" else keys,
    }


def hit(key, n=1):
    return Hit(id=n, citation_key=key, title="8 CFR 214.2(f)", source_tier="ecfr", url="u", content=KNOWN.get(key, ""), distance=0.1 * n)


class FakeJudge:
    """Records which judge calls were made; fixed scores."""

    def __init__(self, verdict="ANSWERED", correctness=0.5):
        self.calls = []
        self.verdict = verdict
        self.correctness = correctness

    def refusal(self, question, answer):
        self.calls.append("refusal")
        return {"verdict": self.verdict, "refused": self.verdict == "REFUSED", "reply": self.verdict, "model": "judge-served"}

    def pair(self, neutral, leading):
        self.calls.append("pair")
        return {"same": True, "reply": "SAME", "model": "judge-served"}

    def faithfulness(self, question, answer, contexts):
        self.calls.append("faithfulness")
        return 1.0

    def context_recall(self, question, contexts, reference, reference_contexts):
        self.calls.append("context_recall")
        return 1.0

    def decompose(self, reference):
        self.calls.append("decompose")
        return CLAIMS

    def answer_correctness(self, answer, claims):
        self.calls.append("answer_correctness")
        return {"score": self.correctness, "verdicts": [True, False]}


class FakeGenerator:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return f"Answer [1].\n\n{DISCLAIMER}"


class NoWait:
    def wait(self):
        pass


# 1. hit@5 and MRR from top-5 citation keys vs gold, exact match.
def test_01_hit_and_mrr_gold_at_rank_2():
    retrieved = ["214.2(f)(5)(iv)", "214.2(f)(10)", "214.2(f)(10)(ii)(E)"]
    assert hit_at_k(retrieved, GOLD) == 1
    assert reciprocal_rank(retrieved, GOLD) == 0.5


def test_01_hit_and_mrr_gold_absent():
    retrieved = ["214.2(f)(5)(iv)", "214.2(f)(10)(ii)(E)"]
    assert hit_at_k(retrieved, GOLD) == 0
    assert reciprocal_rank(retrieved, GOLD) == 0


def test_01_extra_gold_at_rank_6_is_outside_top_5():
    retrieved = ["a", "b", "c", "d", "e", "214.2(f)(10)"]
    assert hit_at_k(retrieved, GOLD) == 0
    assert reciprocal_rank(retrieved, GOLD) == 0


def test_01_extra_parent_key_is_not_a_match():
    # Exact match only: (f)(10)(ii)(E) is not the gold (f)(10).
    assert hit_at_k(["214.2(f)(10)(ii)(E)"], ["214.2(f)(10)"]) == 0


# 2. Citation accuracy: fraction of cited keys in gold; no citations = 0.
def test_02_rag_citations_half_match():
    sources = ["214.2(f)(10)", "214.2(f)(5)(iv)", "214.2(f)(10)(ii)(E)"]
    cited = rag_citations("You need one year [1]. See also [3].", sources)
    assert cited == ["214.2(f)(10)", "214.2(f)(10)(ii)(E)"]
    assert citation_accuracy(cited, GOLD) == 0.5


def test_02_no_citation_scores_zero():
    assert rag_citations("You need one year.", ["214.2(f)(10)"]) == []
    assert citation_accuracy([], GOLD) == 0


def test_02_bare_regex_normalizes_to_citation_keys():
    answer = (
        "Under 8 CFR 214.2(f)(10) you need a year. The filing window is in "
        "8 C.F.R. § 214.2(f)(11)(i)(B)(2), and see 8 CFR §214.2 (f) (5) (iv)."
    )
    cited = bare_citations(answer)
    assert cited == ["214.2(f)(10)", "214.2(f)(11)(i)(B)(2)", "214.2(f)(5)(iv)"]
    assert citation_accuracy(cited, GOLD) == pytest.approx(2 / 3)


def test_02_unknown_key_counts_against_accuracy_and_as_unknown():
    cited = bare_citations("See 8 CFR 214.2(f)(10) and 8 CFR 214.2(f)(99)(z).")
    assert cited == ["214.2(f)(10)", "214.2(f)(99)(z)"]
    assert citation_accuracy(cited, GOLD) == 0.5
    assert unknown_keys(cited, KNOWN) == ["214.2(f)(99)(z)"]


def test_02_extra_label_beyond_sources_is_unknown():
    cited = rag_citations("Yes [1][7].", ["214.2(f)(10)"])
    assert cited == ["214.2(f)(10)", "[7]"]
    assert unknown_keys(cited, KNOWN) == ["[7]"]


def test_02_extra_repeated_and_grouped_labels_count_once():
    sources = ["214.2(f)(10)", "214.2(f)(10)", "214.2(f)(5)(iv)"]
    assert rag_citations("A [1][2]. B [1, 3]. C [1].", sources) == ["214.2(f)(10)", "214.2(f)(5)(iv)"]


def test_02_extra_bare_ignores_bracket_labels():
    assert bare_citations("Yes [1].") == []


def test_extra_disclaimer_stripped_only_when_exact():
    assert strip_disclaimer(f"Yes [1].\n\n{DISCLAIMER}") == ("Yes [1].", True)
    assert strip_disclaimer("Yes [1]. This is not legal advice.") == ("Yes [1]. This is not legal advice.", False)


# 3. Refuse items get only the refusal metric.
def test_03_refuse_item_gets_only_refusal():
    judge = FakeJudge(verdict="REFUSED")
    scored = score(item("Q12", expected="refuse"), "opt-rag", "Ask your DSO.", [hit("214.2(f)(10)")], known=KNOWN, judge=judge, claims=None)
    assert scored["metrics"] == {"refused": True, "refusal_verdict": "REFUSED"}
    assert judge.calls == ["refusal"]


def test_03_answer_item_gets_every_opt_rag_metric():
    judge = FakeJudge()
    hits = [hit("214.2(f)(5)(iv)", 1), hit("214.2(f)(10)", 2)]
    scored = score(item(), "opt-rag", f"One year [2].\n\n{DISCLAIMER}", hits, known=KNOWN, judge=judge, claims=CLAIMS)
    assert scored["metrics"] == {
        "refused": False,
        "refusal_verdict": "ANSWERED",
        "hit_at_5": 1,
        "mrr": 0.5,
        "citation_accuracy": 1.0,
        "faithfulness": 1.0,
        "context_recall": 1.0,
        "answer_correctness": 0.5,
    }
    assert scored["disclaimer_stripped"] is True


def test_03_extra_bare_answer_item_has_no_retrieval_metrics():
    judge = FakeJudge()
    scored = score(item(), "bare", "See 8 CFR 214.2(f)(10).", [], known=KNOWN, judge=judge, claims=CLAIMS)
    assert set(scored["metrics"]) == {"refused", "refusal_verdict", "citation_accuracy", "answer_correctness"}
    assert sorted(judge.calls) == ["answer_correctness", "refusal"]


def test_03_summary_ignores_refuse_items_in_scored_metrics():
    answer = record("opt-rag", 1, "Q1", correctness=0.4)
    refuse = record("opt-rag", 1, "Q12", expected="refuse", verdict="REFUSED")
    refuse["metrics"]["answer_correctness"] = 0.0  # must not pull the mean down
    summary = summarize([answer, refuse], [])
    assert "| Answer correctness (reference-claim recall) | 0.400 | 0.400 | 0.400 | 1/1 |" in summary
    assert "| Refuse items judged REFUSED | 1.000 | 1/1 | 1/1 | 1 |" in summary


# 4. Resume: completed (arm, run, qid) lines are skipped, nothing is duplicated.
def test_04_resume_skips_completed_lines(tmp_path):
    items = [item("Q1"), item("Q2")]
    done = {"arm": "opt-rag", "run": 1, "qid": "Q1", "answer": "earlier answer", "metric_version": METRIC_VERSION}
    (tmp_path / "raw.jsonl").write_text(json.dumps(done) + "\n")
    generator = FakeGenerator()
    kwargs = dict(
        retrieve=lambda q: [hit("214.2(f)(10)")], generator=generator, judge=FakeJudge(),
        known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256,
    )

    run(items, ["opt-rag"], 1, tmp_path, **kwargs)
    rows = read_jsonl(tmp_path / "raw.jsonl")
    assert [(r["arm"], r["run"], r["qid"]) for r in rows] == [("opt-rag", 1, "Q1"), ("opt-rag", 1, "Q2")]
    assert rows[0] == done
    assert len(generator.prompts) == 1

    run(items, ["opt-rag"], 1, tmp_path, **kwargs)
    assert len(read_jsonl(tmp_path / "raw.jsonl")) == 2
    assert len(generator.prompts) == 1


def test_04_extra_pairs_judged_once_per_arm_and_run(tmp_path):
    items = [item("P01-N", category="Paired neutral", pair_id="P01"), item("P01-L", category="Paired leading", pair_id="P01")]
    judge = FakeJudge()
    kwargs = dict(
        retrieve=lambda q: [hit("214.2(f)(10)")], generator=FakeGenerator(), judge=judge,
        known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256,
    )
    run(items, ["opt-rag", "bare"], 2, tmp_path, **kwargs)
    run(items, ["opt-rag", "bare"], 2, tmp_path, **kwargs)
    pairs = read_jsonl(tmp_path / "pairs.jsonl")
    assert sorted((p["arm"], p["run"], p["pair_id"]) for p in pairs) == [
        ("bare", 1, "P01"), ("bare", 2, "P01"), ("opt-rag", 1, "P01"), ("opt-rag", 2, "P01"),
    ]
    assert judge.calls.count("pair") == 4


def test_04_extra_failure_is_recorded_and_raised(tmp_path):
    class Broken:
        def complete(self, prompt):
            raise RuntimeError("HTTP 400")

    with pytest.raises(RuntimeError):
        run([item("Q1")], ["bare"], 1, tmp_path, retrieve=None, generator=Broken(), judge=FakeJudge(),
            known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    [failure] = read_jsonl(tmp_path / "failures.jsonl")
    assert (failure["arm"], failure["run"], failure["qid"]) == ("bare", 1, "Q1")
    assert "HTTP 400" in failure["error"]
    assert not (tmp_path / "raw.jsonl").exists()


def test_extra_rate_limit_waits_for_the_oldest_call_to_leave_the_window():
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimit(5, 60, clock=lambda: now[0], sleep=sleep)
    for _ in range(5):
        limiter.wait()
        now[0] += 1
    limiter.wait()
    assert slept == [55]


# 5. Summary: mean, min and max over runs.
def record(arm, run_no, qid, expected="answer", correctness=None, verdict="ANSWERED", disclaimer=True):
    metrics = {"refused": verdict == "REFUSED", "refusal_verdict": verdict}
    if expected == "answer":
        metrics |= {"citation_accuracy": 1.0, "answer_correctness": correctness}
        if arm == "opt-rag":
            metrics |= {"hit_at_5": 1, "mrr": 1.0, "faithfulness": 1.0, "context_recall": 1.0}
    return {
        "arm": arm, "run": run_no, "qid": qid, "expected": expected, "question": f"Question {qid}?",
        "answer": f"Answer to {qid}", "cited_keys": ["214.2(f)(10)"], "unknown_keys": [],
        "disclaimer_stripped": disclaimer, "metrics": metrics, **MODELS,
    }


def test_05_summary_mean_min_max_over_three_runs():
    records = [record("bare", n, "Q1", correctness=f) for n, f in [(1, 0.2), (2, 0.5), (3, 0.8)]]
    pairs = [{"arm": "bare", "run": n, "pair_id": "P01", "same": n != 2} for n in (1, 2, 3)]
    summary = summarize(records, pairs)
    assert "| Answer correctness (reference-claim recall) | 0.500 | 0.200 | 0.800 | 1/1, 1/1, 1/1 |" in summary
    assert "| Pair stability | 0.667 | 0/1 | 1/1 | 1, 1, 1 |" in summary
    assert "judge-test" in summary and "gemini-test" in summary


def test_05_extra_summary_lists_worst_items_and_missing_disclaimers():
    records = [
        record("opt-rag", 1, qid, correctness=f, disclaimer=qid != "Q3")
        for qid, f in [("Q1", 0.9), ("Q2", 0.1), ("Q3", 0.5), ("Q4", 0.7), ("Q5", 0.3), ("Q6", 0.2), ("Q7", 0.95)]
    ]
    summary = summarize(records, [])
    worst = [line.split()[1] for line in summary.split("worst answer items")[1].splitlines() if line.startswith("- ")]
    assert worst == ["Q2", "Q6", "Q5", "Q3", "Q4"]
    assert "| Answer items without the disclaimer | 0.143 | 1/7 | 1/7 | 7 |" in summary


def test_05_extra_n_shows_items_ragas_could_not_score():
    records = [record("opt-rag", 1, "Q1", correctness=0.6), record("opt-rag", 1, "Q2", correctness=None)]
    records[1]["metrics"]["faithfulness"] = None
    summary = summarize(records, [])
    assert "| Answer correctness (reference-claim recall) | 0.600 | 0.600 | 0.600 | 1/2 |" in summary
    assert "| Faithfulness | 1.000 | 1.000 | 1.000 | 1/2 |" in summary
    assert "| Unknown citation rate | 0.000 | 0.000 | 0.000 | 2 keys |" in summary


# Step 10b (Hank's decisions of 2026-10-24); all edge cases below are Claude's.
def test_extra_bare_arm_uses_its_own_prompt_and_opt_rag_keeps_the_shared_one(tmp_path):
    generator = FakeGenerator()
    run([item("Q1")], ["opt-rag", "bare"], 1, tmp_path, retrieve=lambda q: [hit("214.2(f)(10)")],
        generator=generator, judge=FakeJudge(), known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    rag_prompt, bare_prompt = generator.prompts
    assert rag_prompt.startswith(INSTRUCTIONS)
    assert bare_prompt == f"{BARE_INSTRUCTIONS}\n\nQuestion: Question Q1?"
    assert "only the numbered sources" not in bare_prompt and "Sources:" not in bare_prompt
    assert '"8 CFR 214.2(f)(...)"' in bare_prompt and "DSO" in bare_prompt
    assert DISCLAIMER in bare_prompt and "Answer in English" in bare_prompt


def test_extra_prompts_written_to_run_dir_and_hashed_into_rows(tmp_path):
    run([item("Q1")], ["opt-rag", "bare"], 1, tmp_path, retrieve=lambda q: [hit("214.2(f)(10)")],
        generator=FakeGenerator(), judge=FakeJudge(), known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    prompts = json.loads((tmp_path / "prompts.json").read_text())
    assert prompts["opt-rag"]["instructions"] == INSTRUCTIONS
    assert prompts["bare"]["instructions"] == BARE_INSTRUCTIONS
    rows = {r["arm"]: r for r in read_jsonl(tmp_path / "raw.jsonl")}
    assert {arm: rows[arm]["prompt_sha256"] for arm in rows} == {arm: prompts[arm]["sha256"] for arm in ("opt-rag", "bare")}
    assert rows["opt-rag"]["prompt_sha256"] != rows["bare"]["prompt_sha256"]


def test_extra_resume_refuses_a_changed_prompt(tmp_path):
    prompts = {"bare": {"sha256": "old", "instructions": "an older bare prompt"}}
    (tmp_path / "prompts.json").write_text(json.dumps(prompts))
    with pytest.raises(RuntimeError, match="bare prompt changed"):
        run([item("Q1")], ["bare"], 1, tmp_path, retrieve=None, generator=FakeGenerator(), judge=FakeJudge(),
            known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    assert not (tmp_path / "raw.jsonl").exists()


@pytest.mark.parametrize("reply", ["REFUSED", "**REFUSED**", " *Refused.* ", "REFUSED."])
def test_extra_verdict_ignores_markdown_asterisks(reply):
    assert parse_verdict(reply, ("ANSWERED", "REFUSED")) == "REFUSED"


def test_extra_verdict_outside_choices_raises():
    with pytest.raises(JudgeError):
        parse_verdict("**Mostly refused**", ("ANSWERED", "REFUSED"))


def test_extra_select_keeps_gold_order_then_limits():
    items = [item("Q1"), item("Q2"), item("Q12", expected="refuse"), item("P01-N")]
    assert [i["qid"] for i in select(items, ["P01-N", "Q1", "Q12"], None)] == ["Q1", "Q12", "P01-N"]
    assert [i["qid"] for i in select(items, None, 2)] == ["Q1", "Q2"]
    with pytest.raises(SystemExit, match="Q99"):
        select(items, ["Q1", "Q99"], None)


# Step 10c (Hank's decisions of 2026-10-24, second round).
# 1. Answer correctness = reference claims supported by the answer / all reference claims.
def test_10c_1_reference_claim_recall():
    assert reference_claim_recall([True, False, True]) == pytest.approx(2 / 3)
    assert reference_claim_recall([True]) == 1.0
    assert reference_claim_recall([False, False]) == 0.0


def test_10c_1_extra_no_reference_claims_is_unscored():
    assert reference_claim_recall([]) is None


def test_10c_1_label_is_defined_once_and_used_by_the_summary():
    assert ANSWER_CORRECTNESS_LABEL == "Answer correctness (reference-claim recall)"
    assert f"| {ANSWER_CORRECTNESS_LABEL} |" in summarize([record("bare", 1, "Q1", correctness=1.0)], [])


def test_10c_1_claims_and_verdicts_stored_in_the_row_with_metric_version(tmp_path):
    run([item("Q1")], ["bare"], 1, tmp_path, retrieve=None, generator=FakeGenerator(), judge=FakeJudge(),
        known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    [row] = read_jsonl(tmp_path / "raw.jsonl")
    assert row["metrics"]["answer_correctness"] == 0.5
    assert row["judge"]["answer_correctness"] == {"reference_claims": ["Claim A.", "Claim B."], "verdicts": [True, False]}
    assert row["metric_version"] == METRIC_VERSION
    assert f"- metric_version: {METRIC_VERSION}" in summarize([row], [])


class FakeClaims:
    """Stands in for the Ragas claim decomposition and NLI calls."""

    def __init__(self, claims, verdicts):
        self.claims, self.verdicts, self.seen = claims, verdicts, {}

    async def decompose_claims(self, text, callbacks):
        self.seen["decomposed"] = text
        return self.claims

    async def verify_claims(self, premise, hypothesis_list, callbacks):
        self.seen["premise"], self.seen["hypotheses"] = premise, hypothesis_list
        return np.array(self.verdicts, dtype=bool)


def test_10c_1_extra_judge_decomposes_the_reference_and_checks_it_against_the_answer():
    judge = Judge("test-key")
    judge.claims = FakeClaims(["You can apply 90 days early.", "Not after 60 days."], [True, False])
    claims = judge.decompose("The reference.")
    result = judge.answer_correctness("The answer.", claims)
    assert judge.claims.seen == {
        "decomposed": "The reference.", "premise": "The answer.",
        "hypotheses": ["You can apply 90 days early.", "Not after 60 days."],
    }
    assert result == {"score": 0.5, "verdicts": [True, False]}


def test_10c_1_extra_verdict_count_mismatch_raises():
    judge = Judge("test-key")
    judge.claims = FakeClaims(["Claim A.", "Claim B."], [True])
    with pytest.raises(JudgeError, match="2 reference claims, 1 verdicts"):
        judge.answer_correctness("The answer.", ["Claim A.", "Claim B."])


# 2. Refusal judge: REFUSED, PARTIAL or ANSWERED.
@pytest.mark.parametrize("reply,verdict", [
    ("REFUSED", "REFUSED"), ("PARTIAL", "PARTIAL"), ("ANSWERED", "ANSWERED"), ("**Partial.**", "PARTIAL"),
])
def test_10c_2_three_class_verdict_parsing(reply, verdict):
    assert parse_verdict(reply, REFUSAL_VERDICTS) == verdict


def test_10c_2_unknown_verdict_raises():
    with pytest.raises(JudgeError):
        parse_verdict("PARTIALLY ANSWERED", REFUSAL_VERDICTS)


SERVED_JUDGE = f"{JUDGE_MODEL}-2026-03-05"


class Reply:
    def __init__(self, text, model):
        self.text, self.response_metadata = text, {"model_name": model}


class FakeLLM:
    def __init__(self, text, model=SERVED_JUDGE):
        self.text, self.model, self.prompts = text, model, []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return Reply(self.text, self.model)


@pytest.mark.parametrize("reply,refused", [("REFUSED", True), ("PARTIAL", False), ("ANSWERED", False)])
def test_10c_2_only_refused_counts_as_refused(reply, refused):
    judge = Judge("test-key")
    judge.llm = FakeLLM(reply)
    assert judge.refusal("Question?", "Answer.") == {"verdict": reply, "refused": refused, "reply": reply, "model": SERVED_JUDGE}


def test_10c_2_extra_prompt_fits_both_arms():
    assert "provided material" not in REFUSAL_PROMPT
    assert all(word in REFUSAL_PROMPT for word in ("REFUSED", "PARTIAL", "ANSWERED", "not sure", "DSO"))


def test_10c_2_summary_reports_three_rates_on_refuse_items_and_refused_only_as_false_refusal():
    records = [
        record("opt-rag", 1, "Q12", expected="refuse", verdict="REFUSED"),
        record("opt-rag", 1, "Q24", expected="refuse", verdict="PARTIAL"),
        record("opt-rag", 1, "Q30", expected="refuse", verdict="PARTIAL"),
        record("opt-rag", 1, "Q1", correctness=1.0, verdict="PARTIAL"),
        record("opt-rag", 1, "Q2", correctness=1.0, verdict="REFUSED"),
    ]
    summary = summarize(records, [])
    assert "| Refuse items judged REFUSED | 0.333 | 1/3 | 1/3 | 3 |" in summary
    assert "| Refuse items judged PARTIAL | 0.667 | 2/3 | 2/3 | 3 |" in summary
    assert "| Refuse items judged ANSWERED | 0.000 | 0/3 | 0/3 | 3 |" in summary
    assert "| False refusal rate, answer items | 0.500 | 1/2 | 1/2 | 2 |" in summary


# 3. Unknown citation rate: an ancestor paragraph of a chunk key counts as known.
def test_10c_3_ancestor_paragraph_is_known():
    # KNOWN has 214.2(f)(10)(ii)(E); (f)(10)(ii) is its parent and has no chunk of its own.
    assert unknown_keys(["214.2(f)(10)(ii)", "214.2(f)"], KNOWN) == []


def test_10c_3_unrelated_key_is_unknown():
    assert unknown_keys(["214.2(f)(10)(ii)", "214.2(f)(99)"], KNOWN) == ["214.2(f)(99)"]


def test_10c_3_extra_number_prefix_and_descendant_are_not_ancestors():
    # (f)(1) is not an ancestor of (f)(10); a child of a chunk key is not a chunk.
    assert unknown_keys(["214.2(f)(1)", "214.2(f)(10)(ii)(E)(1)"], KNOWN) == ["214.2(f)(1)", "214.2(f)(10)(ii)(E)(1)"]


# Step 10d (Hank's decisions of 2026-10-24, third round).
def fake_run(tmp_path, items, arms=("opt-rag", "bare"), runs=1, judge=None, git=GIT, gold_sha256=GOLD_SHA256):
    judge = judge or FakeJudge()
    run(items, list(arms), runs, tmp_path, retrieve=lambda q: [hit("214.2(f)(10)")], generator=FakeGenerator(),
        judge=judge, known=KNOWN, models=MODELS, limiter=NoWait(), git=git, gold_sha256=GOLD_SHA256)
    return judge


# 1. Each reference is decomposed once per qid and shared across arms and runs, cached in the run dir.
def test_10d_1_reference_decomposed_once_across_arms_and_runs(tmp_path):
    judge = fake_run(tmp_path, [item("Q1")], runs=2)
    assert judge.calls.count("decompose") == 1
    [cached] = read_jsonl(tmp_path / "reference_claims.jsonl")
    assert cached == {"qid": "Q1", "reference_sha256": sha256_hex("Reference for Q1."), "claims": CLAIMS}
    rows = read_jsonl(tmp_path / "raw.jsonl")
    assert len(rows) == 4
    assert all(r["judge"]["answer_correctness"]["reference_claims"] == CLAIMS for r in rows)


def test_10d_1_resume_reads_claims_from_the_run_dir(tmp_path):
    fake_run(tmp_path, [item("Q1")], runs=1)
    judge = fake_run(tmp_path, [item("Q1")], runs=2)
    assert "decompose" not in judge.calls
    assert judge.calls.count("answer_correctness") == 2  # run 2, both arms


def test_10d_1_extra_changed_reference_text_is_decomposed_again(tmp_path):
    fake_run(tmp_path, [item("Q1")], arms=["bare"])
    changed = item("Q1") | {"reference_answer": "A corrected reference."}
    judge = fake_run(tmp_path, [changed], arms=["bare"], runs=2)
    assert judge.calls.count("decompose") == 1
    assert [c["reference_sha256"] for c in read_jsonl(tmp_path / "reference_claims.jsonl")] == [
        sha256_hex("Reference for Q1."), sha256_hex("A corrected reference."),
    ]


def test_10d_1_extra_refuse_items_are_not_decomposed(tmp_path):
    judge = fake_run(tmp_path, [item("Q12", expected="refuse")])
    assert "decompose" not in judge.calls
    assert not (tmp_path / "reference_claims.jsonl").exists()


# 2. Resume refuses a run id whose rows have a different metric_version.
def test_10d_2_resume_refuses_another_metric_version(tmp_path):
    old = {"arm": "bare", "run": 1, "qid": "Q1", "metric_version": "step10-older"}
    (tmp_path / "raw.jsonl").write_text(json.dumps(old) + "\n")
    generator = FakeGenerator()
    with pytest.raises(RuntimeError, match="metric_version step10-older"):
        run([item("Q1"), item("Q2")], ["bare"], 1, tmp_path, retrieve=None, generator=generator, judge=FakeJudge(),
            known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    assert generator.prompts == []
    assert len(read_jsonl(tmp_path / "raw.jsonl")) == 1


def test_10d_2_extra_rows_without_metric_version_are_refused(tmp_path):
    (tmp_path / "raw.jsonl").write_text(json.dumps({"arm": "bare", "run": 1, "qid": "Q1"}) + "\n")
    with pytest.raises(RuntimeError, match="metric_version None"):
        fake_run(tmp_path, [item("Q1")], arms=["bare"])


# 3. Git HEAD and dirty flag in prompts.json and the summary header.
def test_10d_3_git_state_in_prompts_json_and_summary(tmp_path):
    fake_run(tmp_path, [item("Q1")], git={"head": "b" * 40, "dirty": True})
    prompts = json.loads((tmp_path / "prompts.json").read_text())
    assert prompts["git"] == [{"head": "b" * 40, "dirty": True}]
    summary = summarize(read_jsonl(tmp_path / "raw.jsonl"), [], prompts["git"])
    assert f"- git: {'b' * 40} (dirty working tree)" in summary


def test_10d_3_extra_resume_appends_a_new_git_state_once(tmp_path):
    fake_run(tmp_path, [item("Q1")], runs=1)
    fake_run(tmp_path, [item("Q1")], runs=2, git={"head": "c" * 40, "dirty": False})
    fake_run(tmp_path, [item("Q1")], runs=2, git={"head": "c" * 40, "dirty": False})
    git = json.loads((tmp_path / "prompts.json").read_text())["git"]
    assert git == [GIT, {"head": "c" * 40, "dirty": False}]
    summary = summarize(read_jsonl(tmp_path / "raw.jsonl"), [], git)
    assert f"- git: {'a' * 40} (clean), {'c' * 40} (clean)" in summary


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo,
                          check=True, capture_output=True, text=True).stdout.strip()


def test_10d_3_extra_git_state_ignores_results_but_not_other_changes(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "app.py").write_text("x = 1\n")
    git(tmp_path, "add", "app.py")
    git(tmp_path, "commit", "-qm", "init")
    head = git(tmp_path, "rev-parse", "HEAD")
    assert git_state(tmp_path) == {"head": head, "dirty": False}

    (tmp_path / "evals" / "results" / "baseline").mkdir(parents=True)
    (tmp_path / "evals" / "results" / "baseline" / "raw.jsonl").write_text("{}\n")
    assert git_state(tmp_path)["dirty"] is False

    (tmp_path / "app.py").write_text("x = 2\n")
    assert git_state(tmp_path)["dirty"] is True
    git(tmp_path, "checkout", "app.py")
    (tmp_path / "new.py").write_text("")
    assert git_state(tmp_path)["dirty"] is True


# Step 10e (review fixes Hank picked on 2026-10-24). Each "extra" test is Claude's edge case.
# 1. Reference claims are decomposed with coverage="high", atomicity unchanged; metric_version bumped.
def test_10e_1_reference_decomposition_uses_high_coverage():
    claims = Judge("test-key").claims
    assert (claims.coverage, claims.atomicity) == ("high", "low")
    assert METRIC_VERSION == "step10-2026-10-24c"


# 9. failures.jsonl stores the exception type and a message with API keys masked.
def test_10e_9_failure_masks_api_keys(tmp_path):
    class Broken:
        def complete(self, prompt):
            raise RuntimeError(
                "Error code: 401 - Incorrect API key provided: sk-proj-****abcd. "
                "Gemini said: API key AIzaSyD-x_9Qk not valid."
            )

    with pytest.raises(RuntimeError):
        run([item("Q1")], ["bare"], 1, tmp_path, retrieve=None, generator=Broken(), judge=FakeJudge(),
            known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    text = (tmp_path / "failures.jsonl").read_text()
    assert "sk-" not in text and "abcd" not in text and "AIza" not in text and "x_9Qk" not in text
    [failure] = read_jsonl(tmp_path / "failures.jsonl")
    assert failure["error_type"] == "RuntimeError"
    assert "Error code: 401" in failure["error"] and "not valid" in failure["error"]


def test_10e_9_extra_pair_failure_is_masked_too(tmp_path):
    class BrokenPairJudge(FakeJudge):
        def pair(self, neutral, leading):
            raise RuntimeError("bad key sk-abc123")

    items = [item("P01-N", category="Paired neutral", pair_id="P01"), item("P01-L", category="Paired leading", pair_id="P01")]
    with pytest.raises(RuntimeError):
        fake_run(tmp_path, items, arms=["bare"], judge=BrokenPairJudge())
    [failure] = read_jsonl(tmp_path / "failures.jsonl")
    assert failure["qid"] == "P01" and "sk-abc123" not in failure["error"]


def test_10e_9_extra_words_containing_sk_dash_are_kept(tmp_path):
    class Broken:
        def complete(self, prompt):
            raise RuntimeError("task-queue full")

    with pytest.raises(RuntimeError):
        run([item("Q1")], ["bare"], 1, tmp_path, retrieve=None, generator=Broken(), judge=FakeJudge(),
            known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    assert read_jsonl(tmp_path / "failures.jsonl")[0]["error"] == "task-queue full"


# 3. The gold file must match the frozen sha256 before any API call; the hash goes to prompts.json.
def test_10e_3_gold_hash_matches_the_frozen_one():
    recorded = re.search(r"sha256: `([0-9a-f]{64})`", EVALS_README.read_text(encoding="utf-8")).group(1)
    assert frozen_gold_sha256(GOLD_FILE, EVALS_README) == recorded


def test_10e_3_changed_gold_stops_before_any_api_call(tmp_path, monkeypatch):
    changed = tmp_path / "gold_v1.jsonl"
    changed.write_bytes(GOLD_FILE.read_bytes() + b"\n")
    monkeypatch.setattr(cli, "GOLD", changed)
    monkeypatch.setattr(cli, "RESULTS", tmp_path / "results")
    # Reaching the generator or judge setup would need app.main; make that import fail loudly.
    monkeypatch.setitem(sys.modules, "app.main", None)
    with pytest.raises(SystemExit, match="differs from the frozen"):
        cli.main(["run", "--run-id", "x"])
    assert not (tmp_path / "results").exists()


def test_10e_3_gold_hash_recorded_in_prompts_json(tmp_path):
    fake_run(tmp_path, [item("Q1")])
    assert json.loads((tmp_path / "prompts.json").read_text())["gold_sha256"] == GOLD_SHA256


def test_10e_3_extra_resume_refuses_another_gold_hash(tmp_path):
    fake_run(tmp_path, [item("Q1")])
    with pytest.raises(RuntimeError, match="gold_sha256 changed"):
        run([item("Q1")], ["bare"], 2, tmp_path, retrieve=None, generator=FakeGenerator(), judge=FakeJudge(),
            known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256="e" * 64)
    assert len(read_jsonl(tmp_path / "raw.jsonl")) == 2


# 4. prompt_sha256 covers the instructions, the rendered build_prompt template with both label
# formats, the bare template, and the refusal and pair judge prompts.
def tier2_label(n, chunk):
    return f"[{n}] 8 CFR {chunk.citation_key}" if chunk.source_tier == "ecfr" else f"[{n}] {chunk.citation_key}"


@pytest.mark.parametrize("arm,target,value", [
    ("opt-rag", "app.generation.INSTRUCTIONS", "Changed instructions."),
    ("opt-rag", "app.generation.label", lambda n, chunk: f"<{n}>"),
    ("opt-rag", "app.generation.label", tier2_label),
    ("opt-rag", "app.evals.runner.build_prompt", lambda question, chunks: f"Changed template. {question}"),
    ("bare", "app.evals.runner.BARE_INSTRUCTIONS", "Changed bare instructions."),
    ("opt-rag", "app.evals.runner.REFUSAL_PROMPT", "Changed refusal judge."),
    ("bare", "app.evals.runner.REFUSAL_PROMPT", "Changed refusal judge."),
    ("opt-rag", "app.evals.runner.PAIR_PROMPT", "Changed pair judge."),
    ("bare", "app.evals.runner.PAIR_PROMPT", "Changed pair judge."),
])
def test_10e_4_prompt_hash_covers(monkeypatch, arm, target, value):
    before = arm_prompts(arm)["sha256"]
    monkeypatch.setattr(target, value)
    assert arm_prompts(arm)["sha256"] != before


def test_10e_4_extra_resume_refuses_a_changed_judge_prompt(tmp_path, monkeypatch):
    fake_run(tmp_path, [item("Q1")])
    monkeypatch.setattr("app.evals.runner.REFUSAL_PROMPT", "Changed refusal judge.")
    with pytest.raises(RuntimeError, match="opt-rag prompt changed"):
        fake_run(tmp_path, [item("Q1")], runs=2)
    assert len(read_jsonl(tmp_path / "raw.jsonl")) == 2


def test_10e_4_extra_bare_prompt_sent_matches_the_hashed_template(tmp_path):
    generator = FakeGenerator()
    run([item("Q1")], ["bare"], 1, tmp_path, retrieve=None, generator=generator, judge=FakeJudge(),
        known=KNOWN, models=MODELS, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    assert generator.prompts == [arm_prompts("bare")["template"].replace("<question>", "Question Q1?")]


# 5. Generation temperature and top_k go to prompts.json and every row.
class SettingsGenerator(FakeGenerator):
    model, temperature = "gemini-test", 0.0


def test_10e_5_temperature_and_top_k_in_prompts_json_and_every_row(tmp_path):
    models = run_models(SettingsGenerator())
    assert (models["generation_temperature"], models["top_k"]) == (0.0, 5)
    run([item("Q1"), item("Q12", expected="refuse")], ["opt-rag", "bare"], 1, tmp_path,
        retrieve=lambda q: [hit("214.2(f)(10)")], generator=SettingsGenerator(), judge=FakeJudge(),
        known=KNOWN, models=models, limiter=NoWait(), git=GIT, gold_sha256=GOLD_SHA256)
    assert json.loads((tmp_path / "prompts.json").read_text())["models"] == models
    rows = read_jsonl(tmp_path / "raw.jsonl")
    assert len(rows) == 4
    assert all((r["generation_temperature"], r["top_k"]) == (0.0, 5) for r in rows)


def test_10e_5_extra_resume_refuses_another_temperature(tmp_path):
    models = run_models(SettingsGenerator())
    fake_run(tmp_path, [item("Q1")], arms=["bare"])
    (tmp_path / "prompts.json").write_text(json.dumps(json.loads((tmp_path / "prompts.json").read_text()) | {"models": models}))
    with pytest.raises(RuntimeError, match="models changed"):
        run([item("Q1")], ["bare"], 2, tmp_path, retrieve=None, generator=FakeGenerator(), judge=FakeJudge(),
            known=KNOWN, models=models | {"generation_temperature": 0.7}, limiter=NoWait(), git=GIT,
            gold_sha256=GOLD_SHA256)


# 6. A custom judge call stops when the served model does not start with JUDGE_MODEL.
@pytest.mark.parametrize("served", [JUDGE_MODEL, f"{JUDGE_MODEL}-2026-03-05"])
def test_10e_6_judge_model_or_its_dated_snapshot_is_accepted(served):
    judge = Judge("test-key")
    judge.llm = FakeLLM("SAME", model=served)
    assert judge.pair(("Q A", "A"), ("Q B", "B"))["model"] == served


# 2026-10-24 follow-up: exact match, so gpt-5.4-mini must fail. Cases other than gpt-5.4-mini are Claude's.
@pytest.mark.parametrize("served", [
    "gpt-5.4-mini", "gpt-5.4-pro", "gpt-5.4-mini-2026-03-05", "gpt-5.40", "gpt-5.4-2026-3-5",
    "gpt-5.4-2026-03-05-extra", "gpt-5.5-2026-04-01", "gpt-4o", None,
])
def test_10e_6_other_served_model_stops_the_run(served):
    judge = Judge("test-key")
    judge.llm = FakeLLM("REFUSED", model=served)
    with pytest.raises(JudgeError, match=f"asked for {JUDGE_MODEL}"):
        judge.refusal("Question?", "Answer.")


# 8. read_jsonl skips a truncated final line (as app/embedding.py does for its cache).
def test_10e_8_truncated_final_line_is_skipped(tmp_path):
    path = tmp_path / "raw.jsonl"
    path.write_text('{"qid": "Q1"}\n{"qid": "Q2", "ans')
    assert read_jsonl(path) == [{"qid": "Q1"}]


def test_10e_8_extra_append_after_a_cut_off_line_starts_a_new_line(tmp_path):
    path = tmp_path / "raw.jsonl"
    path.write_text('{"qid": "Q1"}\n{"qid": "Q2", "ans')
    append_jsonl(path, {"qid": "Q2"})
    assert read_jsonl(path) == [{"qid": "Q1"}, {"qid": "Q2"}]


def test_10e_8_extra_resume_reruns_the_item_whose_line_was_cut_off(tmp_path):
    fake_run(tmp_path, [item("Q1"), item("Q2")], arms=["bare"])
    raw = tmp_path / "raw.jsonl"
    raw.write_text(raw.read_text()[:-40])
    fake_run(tmp_path, [item("Q1"), item("Q2")], arms=["bare"])
    assert [r["qid"] for r in read_jsonl(raw)] == ["Q1", "Q2"]


# 10. Summary averages use each run's own n.
def test_10e_10_count_mean_uses_each_runs_own_n():
    pairs = [{"arm": "bare", "run": 1, "pair_id": f"P0{i}", "same": i != 5} for i in range(1, 6)]
    pairs += [{"arm": "bare", "run": 2, "pair_id": f"P0{i}", "same": True} for i in (1, 2)]
    records = [record("bare", n, "Q1", correctness=1.0) for n in (1, 2)]
    # Run 1: 4/5 = 0.8, run 2 (partly resumed): 2/2 = 1.0; mean 0.9, min 4/5, max 2/2.
    assert "| Pair stability | 0.900 | 4/5 | 2/2 | 5, 2 |" in summarize(records, pairs)
