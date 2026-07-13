# NewMed Denial Prevention Co-Pilot

**A working product prototype: pre-submission denial risk scoring for medical claims, predicted denial reason, one-click fix, biller in the loop.**

> Built by [Nayan Lal](https://www.linkedin.com/in/nayanlal) as an AI product management case study.
> All data is synthetic. "NewMed" is a fictional healthcare SaaS platform; "Lakeview Specialty Partners" is a fictional 8-practice medical group. No real patient, provider, or payer data is used anywhere.

---

## The problem, in one paragraph

US medical practices submit claims to insurers (payers) and get **10-15% of them denied**. Each denied claim costs **$25-$118 of staff labour** to decode, correct, and resubmit, and roughly **half are never recovered at all**: the revenue is simply written off. The industry's standard answer is *denial management*, working denials after the payer says no. But most denial reasons (stale eligibility, missing prior authorization, missing modifiers, incomplete fields, timely-filing breaches) are **knowable from the claim record before it is ever submitted**. The cheapest denial is the one that never goes out wrong.

**The Co-Pilot shifts denial intelligence left**: it scores every claim for denial risk at claim-scrubbing time (the last moment the practice still controls the claim), explains *why* in biller language, predicts the CARC denial code the payer would return, and offers a one-click fix. The biller decides; every override and every eventual payer verdict feeds back into the model.

## Why I believed this was worth building (the discovery trail)

I did not start with the product. I started with SQL against a six-month claims warehouse, 6,000 claims across 4 specialties and 5 payers. The full reasoning trail, with every query and result, is in **[docs/DISCOVERY.md](docs/DISCOVERY.md)** and rendered interactively on tab 1 of the app. The short version:

| Question | Query | Finding |
|---|---|---|
| How big is the problem? | Q1 | **15.4% denial rate** (industry norm 10-15%), **$829,757** in denied charges, **$72,869** rework spend, **45.5%** of denials written off, in six months |
| Is it uniform? | Q2, Q7 | No, Medicaid denies at 32%, Medicare at 10%, and each payer's *dominant* denial reason differs (UnityHealth → prior auth; Medicaid → eligibility churn) |
| Is it preventable? | Q3, Q4 | **80.1% of denials** trace to reasons knowable pre-submission |
| Is the signal visible in time? | Q8 | Claims with a clean fact pattern deny at **5%**; with a known gap, **43-92%**. The signal exists at submission time |
| Will it fix itself? | Q5 | No trend improvement over six months, the leak is structural |

That last table is the whole build case: **material, concentrated, preventable, detectable, and not self-healing.**

## What the prototype does

A five-tab single-page app, served locally, no external dependencies:

1. **Why build this**, the SQL discovery trail, with every query expandable next to its live chart.
2. **Claim lifecycle**, the 8-stage revenue cycle in plain English, showing where the Co-Pilot sits (stage 5) versus where classic denial management sits (stage 7), and why shifting left wins.
3. **Co-Pilot queue**, *the working product.* A biller's pre-submission queue, scored **live in the browser** by the trained model. Click a claim → risk score, contributing factors with model weights, predicted CARC code, suggested fixes. Apply a fix → the score re-computes in real time. Override → logged as a training label.
4. **Evals & rollout**, temporal backtest (AUC 0.853), an **operating-threshold slider** that trades biller workload against denials caught (precision/recall/confusion matrix/$ protected update live), the gated rollout plan, and the risk register.
5. **Glossary**, every healthcare term used, in plain English, with why it matters to this product.

## Quickstart

Requires only Python 3 (stdlib, no pip installs).

```bash
python3 run_pipeline.py                      # regenerate data → run SQL discovery → train model
python3 -m http.server 8801 --directory app  # serve the prototype
# open http://localhost:8801
```

## Repo map

```
data/generate_claims.py      synthetic claims warehouse (SQLite + CSV) with a causal
                             denial process, payer-specific rules + irreducible noise
analysis/discovery_queries.sql  the 8 discovery queries, each tied to a product question
analysis/run_discovery.py    runs the SQL, emits docs/DISCOVERY.md + app aggregates
model/train_model.py         pure-Python logistic regression, temporal split, threshold sweep
app/index.html               the five-tab prototype (vanilla JS, hand-rolled SVG charts)
docs/PRD.md                  the product requirements document
docs/DISCOVERY.md            generated: full SQL reasoning trail with results
docs/EVALS.md                evaluation methodology, results, monitoring plan
docs/GLOSSARY.md             healthcare vocabulary in plain English
docs/DEMO_SCRIPT.md          3-minute walkthrough script
```

## Deliberate design decisions

- **Logistic regression, not a deep model.** A biller must be able to audit *why* a claim was flagged, or they stop trusting the queue. Interpretability is the product requirement; the 15 weights are printed to the browser console on load.
- **Temporal backtest, not a random split.** Payer rules drift. Training on Jan-Apr and testing on May-Jun simulates deployment order; a random split would leak the future and flatter the metrics.
- **The threshold is a slider, not a constant.** Flagging more claims catches more denials but burns biller review time and trust. That trade-off belongs to the practice (a product decision), not to the data scientist.
- **Human in the loop, permanently.** The AI recommends; the biller decides. Overrides are one click and are treated as labeled training data, not as failures.
- **The 835 remittance stream is the flywheel.** Every payer verdict is a free training label; the model improves as a by-product of normal operations.

## Honest limitations

- Synthetic data is generated from a causal process I designed, so model performance (AUC 0.853) is **illustrative of the method, not a claim about real-world accuracy**, real adjudication is messier and performance would be lower and payer-dependent.
- Single-line claims only; real 837s carry multiple service lines and line-level adjudication.
- No real eligibility (270/271) or prior-auth integrations, the "Apply fix" button simulates the outcome of those workflows.
- A production system needs HIPAA controls (BAA, minimum-necessary access, audit logging) that a local prototype does not implement.

---

*Prototype built July 2026. Stack: Python 3 stdlib, SQLite, vanilla HTML/JS/SVG. No frameworks, no external services, no API keys, clone and run.*
