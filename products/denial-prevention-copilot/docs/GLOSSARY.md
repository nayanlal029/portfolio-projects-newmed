# Glossary: healthcare billing terms used in this project

*Plain-English definitions, each with why it matters to this product. (Also rendered on tab 5 of the app.)*

| Term | Plain English | Why it matters here |
|---|---|---|
| **Claim** | The itemized bill a practice sends an insurer after a visit: who was seen, what was done, why, and the charge. | The atomic unit this product scores. |
| **Payer** | Whoever pays: Medicare (federal, 65+), Medicaid (state, low-income), or commercial insurers. Each has its own rulebook. | Denial behaviour is payer-specific, the core modeling insight. |
| **CPT code** | 5-digit code for *what was done* (45380 = colonoscopy with biopsy). | Procedure determines charge, prior-auth need, modifier rules. |
| **ICD-10 code** | The diagnosis code, *why* it was done (K21.9 = acid reflux). | Diagnosis inconsistent with procedure → CO-11 denial. |
| **Modifier** | 2-character suffix adding context to a CPT: -LT/-RT (left/right), -25 (separate service same day). | Missing modifiers are a top preventable denial (CO-4) and a one-click fix. |
| **Denial / CARC code** | Payer refuses to pay; the coded reason (Claim Adjustment Reason Code), e.g. CO-197 = no prior authorization. | The labels the model learns from and the predictions it makes. |
| **EDI 837 / 835** | The electronic claim going out (837) / the remittance advice coming back (835) with pay-or-deny verdicts. | The 835 stream is a free, continuous source of training labels. |
| **Clearinghouse** | Routing middleman that validates and forwards claims between practices and thousands of payers. | Where rule-based "scrubbing" happens today, rules, not learning. |
| **Eligibility verification (270/271)** | Electronic check that coverage is active and what it covers. | Stale eligibility is the #1 denial cause in the dataset (CO-27), cheap to re-verify. |
| **Prior authorization (PA)** | Payer pre-approval required before certain procedures. Manual, slow, resented. | Highest-severity flag: 70% denial rate when missing. |
| **Timely filing limit** | Submission deadline after service date, 90 days (strict commercial) to 365 (Medicare). | Missed = nearly unrecoverable (92% denial): CO-29. |
| **Clean claim rate** | % of claims paid on first submission, no rework. Best practice 90-95%+. | The product's north-star metric. |
| **Denial rate** | % of claims denied. Industry ~10-15%. | The headline problem metric (15.4% in discovery). |
| **Days in A/R** | Average days from service to payment. Good < ~35-40. | Denied-then-recovered claims: ~95 days vs ~30 first-pass. |
| **Rework cost** | Staff labour to correct and resubmit a denied claim: ~$25-118. | One side of the ROI math. |
| **Write-off** | A denial the practice gives up on, revenue permanently lost. | ~46% of denials here. The biggest number this product protects. |
| **RCM** | Revenue Cycle Management, the whole booking-to-payment pipeline. | The product category this lives in. |
| **Payer mix** | A practice's split across Medicare / Medicaid / commercial / self-pay. | Sets each practice's risk profile and model calibration. |
| **HIPAA / PHI** | US patient-privacy law / Protected Health Information. | Real deployment needs BAA, minimum-necessary access, audit logs. |
| **Precision / recall** | Of what we flagged, how much was right / of what was truly there, how much we caught. | The workload-vs-coverage trade-off; the threshold is a product decision. |
