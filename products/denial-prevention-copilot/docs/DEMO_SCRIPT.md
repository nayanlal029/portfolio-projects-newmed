# Demo script: 3 minutes, conversational

*How to walk someone through the prototype. Deploy conversationally, not as a pitch: two or three sentences, then stop and invite reaction.*

## The one-breath setup

> "I wanted to test how fast I could ramp into the billing domain, so I built something. I took a synthetic claims warehouse, six thousand claims, five payers, four specialties, and did what I'd do on the job: SQL first. The numbers said 15% of claims deny, and 80% of those denials are knowable *before* submission. So I built a pre-submission co-pilot: it scores every claim for denial risk, predicts the denial code, and suggests the fix, biller stays in the loop. Want to see it?"

## The 3-minute walkthrough (tab order = argument order)

**Tab 1, Why build this (45s).** "I didn't start with the product, I started with queries." Point at the KPI tiles, then Q8: *clean claims deny at 5%; claims with a known gap deny at 43-92%. The signal exists before submission, that's the feasibility proof.* Expand one SQL block to show the queries are real.

**Tab 2, Lifecycle (20s).** "Denials are born at stages 1-5 but discovered at stage 6, weeks later. Classic denial management works at stage 7. This sits at stage 5, the last moment the practice controls the claim. Cheapest denial is the one that never goes out wrong."

**Tab 3, Co-Pilot queue (75s, the money moment).** Click the top claim: "93% risk, and it tells the biller *why*, prior auth missing, eligibility 77 days stale, in their language, with the predicted denial code CO-197." Click **Apply fix**: "watch the score recompute, 93 to 55, and now the predicted denial re-ranks to the next cause. Apply the second fix, 14%, claim's clean." Point at the override button: "and if the biller disagrees, one click, and that override becomes a training label. The AI recommends, the biller decides."

**Tab 4, Evals (40s).** "Temporal backtest, trained Jan-Apr, tested May-Jun, never random, because payer rules drift. AUC 0.85. But the real product decision is this slider: the operating threshold trades biller workload against denials caught. At 30%, half the flags are real denials, we catch 59% of them, and it costs 23 biller-hours a month against about $46k protected. False positives here cost trust exactly like false churn flags cost retention spend, same tuning problem I did at Deloitte."

**Stop there.** Offer tab 5 (glossary) only if domain vocabulary comes up.

## Anticipated questions → where the answer lives

| Question | Answer anchor |
|---|---|
| "How would you validate this before release?" | Evals tab + EVALS.md: offline backtest → gated alpha, 100% human review → payer-first expansion → GA gates |
| "What if the model is wrong?" | Cost asymmetry: FP = 4 min review; FN = $79 rework + 46% chance of $449 write-off. Threshold is per-practice. Override is one click and feeds back. |
| "Why logistic regression, not an LLM/deep model?" | Auditability is the product requirement; earn complexity with evidence. (An LLM belongs in a different slot: drafting appeal letters at stage 7, or explaining flags conversationally.) |
| "Isn't this just a claim scrubber?" | Scrubbers are static generic rules. This learns payer-specific patterns from cross-practice adjudication history, Q7 shows each payer's dominant failure mode differs. The platform's data is the moat. |
| "How does it relate to the Billing Assistant?" | Same data flywheel, one stage earlier. Prevention (stage 5) + resolution (stage 7), complementary, and every stage-7 resolution teaches the stage-5 model. |
| "What would you do differently with real data?" | EVALS.md §6: calibration, line-level features, pooled-vs-per-payer models, and much humbler accuracy expectations. |
| "Where's the SQL?" | analysis/discovery_queries.sql, 8 queries incl. window functions (RANK over payer partitions), NULL-safe rates, CTEs. |

## Disclosure line (use verbatim)

> "To be clear, this is synthetic data and a fictional platform I named NewMed; I built it to force myself through the domain: the claim lifecycle, CARC codes, payer behaviour, the economics. The product thinking and the eval method are the transferable part."
