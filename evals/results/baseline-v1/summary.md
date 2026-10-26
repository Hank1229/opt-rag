# Eval summary: baseline-v1

- generation_model: gemini-3.6-flash
- embedding_model: gemini-embedding-001 (768 dims)
- judge_model: gpt-5.4
- metric_version: step10-2026-10-24c
- git: 57d2d33fe98d66c74bcff4f924b14c9c18a12ba4 (clean)

## opt-rag

Runs: 3. Items scored per run: 41, 41, 41.

n is per run: items scored out of answer items for rates, cited keys for the unknown citation rate, items or pairs judged for counts.

| Metric | Mean | Min | Max | n |
|---|---|---|---|---|
| Answer correctness (reference-claim recall) | 0.757 | 0.739 | 0.778 | 31/31, 31/31, 31/31 |
| Faithfulness | 0.903 | 0.894 | 0.920 | 31/31, 31/31, 31/31 |
| Context recall | 0.875 | 0.855 | 0.903 | 31/31, 31/31, 31/31 |
| hit@5 | 0.871 | 0.871 | 0.871 | 31/31, 31/31, 31/31 |
| MRR | 0.578 | 0.578 | 0.578 | 31/31, 31/31, 31/31 |
| Citation accuracy | 0.461 | 0.453 | 0.465 | 31/31, 31/31, 31/31 |
| Unknown citation rate | 0.000 | 0.000 | 0.000 | 87 keys, 78 keys, 77 keys |
| Refuse items judged REFUSED | 0.833 | 8/10 | 9/10 | 10, 10, 10 |
| Refuse items judged PARTIAL | 0.067 | 0/10 | 1/10 | 10, 10, 10 |
| Refuse items judged ANSWERED | 0.100 | 1/10 | 1/10 | 10, 10, 10 |
| False refusal rate, answer items | 0.075 | 1/31 | 3/31 | 31, 31, 31 |
| Pair stability | 0.933 | 4/5 | 5/5 | 5, 5, 5 |
| Answer items without the disclaimer | 0.000 | 0/31 | 0/31 | 31, 31, 31 |

5 worst answer items by answer correctness (reference-claim recall), mean over runs:

- Q8 0.00: How many total days can I be unemployed while on regular post-completion OPT? Answer: During post-completion OPT, you may not accrue an aggregate of more than 90 days of unemployment [1][2][3]. This is a...
- P05-N 0.00: Once I finish my post-completion OPT and enter the grace period, can I keep working? Answer: The provided sources do not contain the answer to this question. Please ask your Designated School Official (DSO). Th...
- P05-L 0.25: I still have a grace period after my post-completion OPT ends, so I can keep working for my employer during that time... Answer: The provided sources do not contain the answer to this question. Please ask your Designated School Official (DSO). Th...
- Q9 0.33: After I finish my post-completion OPT normally, how much time do I have to leave the U.S.? Answer: After completing an authorized period of post-completion OPT (practical training), you have 60 days after your OPT em...
- Q23 0.33: My employer filed an H-1B petition requesting a change of status during the grace period after my OPT ended. If the p... Answer: The provided sources do not contain the answer to this question. Please ask your Designated School Official (DSO). Th...

## bare

Runs: 3. Items scored per run: 41, 41, 41.

n is per run: items scored out of answer items for rates, cited keys for the unknown citation rate, items or pairs judged for counts.

| Metric | Mean | Min | Max | n |
|---|---|---|---|---|
| Answer correctness (reference-claim recall) | 0.840 | 0.808 | 0.856 | 31/31, 31/31, 31/31 |
| Citation accuracy | 0.548 | 0.501 | 0.575 | 31/31, 31/31, 31/31 |
| Unknown citation rate | 0.060 | 0.048 | 0.070 | 49 keys, 43 keys, 42 keys |
| Refuse items judged REFUSED | 0.300 | 3/10 | 3/10 | 10, 10, 10 |
| Refuse items judged PARTIAL | 0.400 | 4/10 | 4/10 | 10, 10, 10 |
| Refuse items judged ANSWERED | 0.300 | 3/10 | 3/10 | 10, 10, 10 |
| False refusal rate, answer items | 0.000 | 0/31 | 0/31 | 31, 31, 31 |
| Pair stability | 1.000 | 5/5 | 5/5 | 5, 5, 5 |
| Answer items without the disclaimer | 0.000 | 0/31 | 0/31 | 31, 31, 31 |

5 worst answer items by answer correctness (reference-claim recall), mean over runs:

- Q15 0.33: My STEM OPT extension application is still pending, but my current EAD has expired. Under what conditions can I keep ... Answer: Under **8 CFR 214.2(f)(11)(i)(C)**, you may continue working while your STEM OPT extension application is pending aft...
- Q11 0.42: Can I travel to another country while my OPT application is still pending? Answer: Under 8 CFR 214.2(f)(13)(ii), an F-1 student who has an **approved** period of optional practical training (OPT) may ...
- Q22 0.50: I'm switching employers during my STEM OPT extension. What do I need to submit for my old and new training plans, inc... Answer: When switching employers during your STEM OPT extension, you must submit documents for both your former employer and ...
- Q13 0.57: Is having an eligible STEM degree enough to apply for a STEM OPT extension, or are there requirements for my employer... Answer: No, having an eligible STEM degree alone is not enough to apply for a STEM OPT extension. Under 8 CFR 214.2(f)(10)(ii...
- Q6 0.67: If I'm on pre-completion OPT, how many hours a week can I work while school is in session? Answer: While school is in session, an F-1 student authorized for pre-completion Optional Practical Training (OPT) can work a...
