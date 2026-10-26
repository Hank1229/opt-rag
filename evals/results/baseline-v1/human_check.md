# Human check: baseline-v1 answer correctness

Hand-scoring pass to check the judge's answer correctness (reference-claim recall) against a human reader.

For each item, read the reference answer and the full answer, then write 1 on the Human score line if the answer gives the facts in the reference answer correctly, 0 if it misses or contradicts any of them. Judge the answer against the reference directly; extra correct detail in the answer does not lower the score. The judge score is shown for later comparison only.

Sample: run 1 answer items, Python random.Random(42), opt-rag first then bare. Within each arm, by judge score: 2 below 0.5, 1 from 0.5 up to but not including 1.0, 2 at 1.0; each stratum drawn with rng.sample from its items in gold order.

## 1. Q8 (opt-rag)

**Question**: How many total days can I be unemployed while on regular post-completion OPT?

**Reference answer**: 90 days in aggregate during the post-completion OPT period.

**Answer**:

> During post-completion OPT, you may not accrue an aggregate of more than 90 days of unemployment [1][2][3].
>
> This is an informational summary, not legal advice.

**Judge score**: 0.00

**Human score (0 or 1)**: 1 

## 2. P05-N (opt-rag)

**Question**: Once I finish my post-completion OPT and enter the grace period, can I keep working?

**Reference answer**: No. Post-completion OPT employment authorization ends when the OPT period ends; the 60-day period that follows is for preparing to depart the United States or transferring to another school, not for continued employment.

**Answer**:

> The provided sources do not contain the answer to this question. Please ask your Designated School Official (DSO).
>
> This is an informational summary, not legal advice.

**Judge score**: 0.00

**Human score (0 or 1)**: 0

## 3. Q14 (opt-rag)

**Question**: I'm on OPT based on a non-STEM degree, but I earned a STEM degree before that. Can I use my earlier degree to apply for a STEM OPT extension, and what requirements would my earlier degree and current job need to meet?

**Reference answer**: Yes. The earlier degree must have been conferred by a U.S. institution that is accredited and SEVP-certified when your DSO recommends the extension, be in a category on the current STEM Designated Degree Program List at that time, and have been conferred within the 10 years before the DSO recommendation. Your current job must be directly related to that earlier STEM degree.

**Answer**:

> Yes, you can use a previously obtained STEM degree to apply for a 24-month STEM OPT extension while on post-completion OPT based on a non-STEM degree, provided specific conditions are met [1][2][3].
>
> **Requirements for your earlier degree (and most recent degree):**
> * **Degree level:** The prior qualifying STEM degree must be at the bachelor's level or higher [3].
> * **Timeframe:** The prior degree must have been conferred within the 10 years preceding the date the DSO recommends you for the extension [1] / applying with USCIS [3].
> * **School Accreditation and SEVP Certification:** 
>   * Your prior degree must have been conferred by a U.S. educational institution that is accredited and SEVP-certified at the time the DSO recommends the extension [1].
>   * Your most recent degree (which does not need to be STEM-related) must also be from a currently accredited, SEVP-certified school [3].
> * **STEM List:** The prior degree program category must be included on the DHS STEM Designated Degree Program List at the time of the DSO recommendation / when submitting the application to USCIS [1][3].
>
> **Requirements for your job/training:**
> * The temporary training must directly relate to your program of study in an approved STEM field [5].
>
> **Application Timing:**
> * You must apply while in a valid period of post-completion OPT [1][2][4][5]. You cannot apply for a STEM OPT extension during the 60-day grace period [2][5].
>
> This is an informational summary, not legal advice.

**Judge score**: 0.83

**Human score (0 or 1)**: 1

## 4. Q20 (opt-rag)

**Question**: My OPT is approved and I've received my EAD, but the start date on the card is still two weeks away. My employer wants me to start next week. Can I start working then?

**Reference answer**: No. You may not begin OPT employment before the approved start date on your EAD.

**Answer**:

> No, you cannot start working next week before the start date on your Employment Authorization Document (EAD) [1][2][3]. 
>
> You may only begin OPT employment after USCIS approves your Form I-765, you receive your EAD, and the start date listed on the EAD actually arrives [2][3]. A student is not permitted to begin OPT employment prior to the approved start date on their EAD [1].
>
> This is an informational summary, not legal advice.

**Judge score**: 1.00

**Human score (0 or 1)**: 1

## 5. Q6 (opt-rag)

**Question**: If I'm on pre-completion OPT, how many hours a week can I work while school is in session?

**Reference answer**: No more than 20 hours a week while school is in session.

**Answer**:

> While school is in session, pre-completion OPT is limited to no more than 20 hours per week [1][2][5].
>
> This is an informational summary, not legal advice.

**Judge score**: 1.00

**Human score (0 or 1)**: 1

## 6. Q6 (bare)

**Question**: If I'm on pre-completion OPT, how many hours a week can I work while school is in session?

**Reference answer**: No more than 20 hours a week while school is in session.

**Answer**:

> While school is in session, an F-1 student authorized for pre-completion Optional Practical Training (OPT) can work a maximum of 20 hours per week. 
>
> This requirement is specified in 8 CFR 214.2(f)(10)(ii)(A)(1)(ii).
>
> This is an informational summary, not legal advice.

**Judge score**: 0.00

**Human score (0 or 1)**: 1

## 7. Q15 (bare)

**Question**: My STEM OPT extension application is still pending, but my current EAD has expired. Under what conditions can I keep working, and for how long?

**Reference answer**: If you filed the STEM OPT extension timely and properly (before your post-completion OPT expired) and timely requested the DSO recommendation, including submitting your executed Form I-983, your work authorization is automatically extended for 180 days; the extension ends once USCIS decides your application.

**Answer**:

> Under **8 CFR 214.2(f)(11)(i)(C)**, you may continue working while your STEM OPT extension application is pending after your current EAD expires under the following conditions:
>
> 1. **Timely Filing:** You must have properly and timely filed your Form I-765 application for the 24-month STEM OPT extension with USCIS *before* your initial post-completion OPT EAD expired.
> 2. **Qualifying Application:** The application must be for a STEM OPT extension based on a qualifying STEM degree and meet all applicable criteria.
>
> **Duration:**
> Your employment authorization is automatically extended for **up to 180 days** starting from the day after your initial post-completion OPT EAD expires, or until USCIS makes a decision on your application, whichever is earlier.
>
> If you are unsure whether your application was timely filed or have questions about your application status, please consult your Designated School Official (DSO).
>
> This is an informational summary, not legal advice.

**Judge score**: 0.33

**Human score (0 or 1)**: 0

## 8. Q13 (bare)

**Question**: Is having an eligible STEM degree enough to apply for a STEM OPT extension, or are there requirements for my employer and training plan too?

**Reference answer**: No. Beyond a qualifying STEM degree, your employer must be enrolled in E-Verify and remain in good standing, you and your employer must complete and sign a Form I-983 training plan before the DSO can recommend the extension, the training must be directly related to the qualifying degree, and you must work at least 20 hours per week, not counting time off taken under the employer's leave policies for similarly situated U.S. workers.

**Answer**:

> No, having an eligible STEM degree is not enough on its own to qualify for a STEM OPT extension. Under the regulations, there are strict requirements for both your employer and your training plan.
>
> Here are the key requirements under 8 CFR 214.2(f)(10)(ii)(C):
>
> 1. **Employer Requirements:** 
>    Your employer must be enrolled in and in good standing with the federal E-Verify program, as specified in 8 CFR 214.2(f)(10)(ii)(C)(5). Additionally, the employer must have a valid Employer Identification Number (EIN) and agree to fulfill duties such as reporting your termination or departure to your Designated School Official (DSO).
>
> 2. **Training Plan Requirements:** 
>    You and your employer must complete and sign a formal Training Plan (Form I-983) before your DSO can recommend the STEM extension, as required by 8 CFR 214.2(f)(10)(ii)(C)(7). Pursuant to 8 CFR 214.2(f)(10)(ii)(C)(7)(i) and 8 CFR 214.2(f)(10)(ii)(C)(10), this training plan must detail specific learning objectives, describe the supervision and assessment you will receive, and include employer certifications ensuring that the employment terms (such as duties, hours, and compensation) are commensurate with those of similarly situated U.S. workers.
>
> If you have questions about whether a specific employer or training plan meets these criteria, please consult with your Designated School Official (DSO).
>
> This is an informational summary, not legal advice.

**Judge score**: 0.57

**Human score (0 or 1)**: 0

## 9. P04-N (bare)

**Question**: Does my employer need to be enrolled in E-Verify for me to get a STEM OPT extension?

**Reference answer**: Your employer must be enrolled in E-Verify and remain a participant in good standing with E-Verify for you to get a STEM OPT extension; a qualifying degree alone is not enough.

**Answer**:

> Yes, your employer must be enrolled in E-Verify for you to be eligible for a STEM OPT extension. 
>
> According to 8 CFR 214.2(f)(10)(ii)(C)(1)(ii), a student seeking a STEM OPT extension must be employed by an employer that is currently enrolled in and in good standing with the E-Verify program.
>
> This is an informational summary, not legal advice.

**Judge score**: 1.00

**Human score (0 or 1)**: 1

## 10. P01-L (bare)

**Question**: I've submitted my initial post-completion OPT application and received the receipt notice, so I can start working while it's pending, right?

**Reference answer**: No. You may not begin post-completion OPT until USCIS approves your Form I-765, you receive your EAD, and the start date on the EAD arrives; a pending application or receipt notice does not authorize work.

**Answer**:

> No, you cannot start working while your initial post-completion OPT application is pending or based solely on receiving a receipt notice. 
>
> Under 8 CFR 214.2(f)(10)(ii)(E), an F-1 student may not begin optional practical training until the date indicated on his or her Employment Authorization Document (EAD). Therefore, you must wait until you receive the physical EAD card and the approved start date on the card has arrived before you can begin working.
>
> If you have questions about your application status or start date, you should consult your Designated School Official (DSO).
>
> This is an informational summary, not legal advice.

**Judge score**: 1.00

**Human score (0 or 1)**: 1

## Result

Agreement (judge score >= 0.5 vs human 1): 7/10.
Disagreements: Q8 opt-rag (judge 0.00, human 1: subject-less reference, dataset issue), Q6 bare (judge 0.00, human 1: NLI verdict flipped in run 1; runs 2 and 3 scored 1.0), Q13 bare (judge 0.57, human 0: answer covers 3 of 6 reference conditions; the judge's claim split let it pass the 0.5 threshold).
Human scoring rule applied: strict, as stated above.
