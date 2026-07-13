# PRD: NewMed Denial Prevention Co-Pilot

| | |
|---|---|
| **Author** | Nayan Lal |
| **Status** | Prototype shipped (v0.1, July 2026) |
| **Product line** | NewMed Practice Management (claims & billing) |
| **Related** | NewMed Billing Assistant (denial *resolution*, 2026 roadmap), this product is its pre-submission complement |

## 1. Problem statement

Specialty practices lose material revenue to claim denials. In the six-month discovery dataset (Lakeview Specialty Partners, 8 practices, 6,000 claims):

- **15.4%** of claims denied (industry norm 10-15%; best practice <5-8%)
- **$829,757** in charges tied up in denials; **$72,869** spent on rework labour
- **45.5%** of denials never recovered, written off entirely
- Denied-then-recovered claims paid in **~95 days** vs **~30 days** first-pass, a 3× cash-flow drag

**80.1% of these denials trace to causes knowable before submission** (eligibility, prior auth, modifiers, missing information, timely filing). Today those gaps are discovered at stage 6 of the revenue cycle (payer adjudication), weeks after the practice lost the ability to fix them cheaply. See [DISCOVERY.md](DISCOVERY.md) for the full SQL trail.

## 2. Users

| User | Job to be done | Today's reality |
|---|---|---|
| **Biller / billing manager** (primary) | Get every claim paid on first pass; keep days-in-A/R low | Works a denial queue reactively; triages by intuition; decodes CARC codes claim-by-claim |
| **Front-desk staff** (secondary) | Verify coverage before the visit | Eligibility checks skipped or stale under time pressure, esp. high-churn Medicaid |
| **Practice owner / administrator** (secondary) | Predictable cash flow; lean billing headcount | Sees denial % on a monthly report, too late to act |
| **NewMed RCM services team** (internal) | Work denials for managed-billing clients efficiently | Highest-volume denial workers; best source of alpha feedback |

## 3. Core workflow (MVP)

1. Claim reaches the pre-submission queue (claim-scrubbing stage).
2. Model scores denial risk from the claim record + payer-specific historical adjudication patterns.
3. High-risk claims are flagged with (a) the top contributing factors in biller language, (b) the predicted CARC denial code, (c) a suggested fix, e.g. *"Eligibility last verified 77 days ago for a high-churn payer; run a real-time 270/271 check before submitting."*
4. Biller applies the fix (one click where the platform can automate it) or overrides and submits as-is.
5. Every fix, override, and eventual 835 outcome is logged as labeled training data.

**Principle: the AI recommends, the biller decides.** No claim is ever auto-blocked or auto-edited.

## 4. Why NewMed wins here (moat)

A single practice sees too few denials per payer to learn payer behaviour. A platform processing claims across thousands of practices sees every payer's adjudication patterns at scale, payer-specific denial models no individual practice could train. The discovery data shows why this matters: each payer's *dominant* denial reason differs (UnityHealth → prior auth; Medicaid → eligibility churn). The same cross-practice data asset that powers post-denial resolution (Billing Assistant) powers pre-submission prevention, one flywheel, two products.

## 5. Success metrics

| Tier | Metric | Definition | Target (12 mo post-GA) |
|---|---|---|---|
| **North star** | First-pass clean claim rate | % of claims paid on first submission, no edits/rework | +5 pts vs matched control practices |
| Supporting | Denial rate | % claims denied | −20% relative |
| Supporting | Days in A/R | avg service→payment days | −4 days |
| Supporting | Rework hours per 1,000 claims | biller labour on denials | −30% |
| **Model health** | Precision / recall at operating threshold | per payer, weekly | precision ≥ 55% at recall ≥ 55% (tunable per practice) |
| **Trust** | Fix-suggestion acceptance rate | % of flags where biller applies suggested fix | > 60% |
| **Trust** | Override rate | % of flags overridden | < 20% and falling |
| Guardrail | Added review time | minutes of biller review per flagged claim | ≤ 4 min median |

## 6. MVP scope

**In:**
- Risk scoring for professional claims (837P), single service line
- Five preventable-gap detectors: eligibility, prior auth, modifier, missing fields, timely filing
- Explainable factor list + predicted CARC + suggested fix
- Operating-threshold configuration per practice (workload vs recall)
- Feedback capture: fix applied / overridden / eventual 835 outcome
- Offline eval harness with temporal backtesting (ships before the model does)

**Out (non-goals for MVP):**
- Auto-editing or auto-holding claims without biller action
- Medical-necessity / clinical-documentation denial prediction (needs chart data; separate effort)
- Institutional claims (837I), multi-line adjudication
- Appeals drafting (that's the Billing Assistant's stage-7 territory)
- Real-time payer integrations beyond what the platform already has

## 7. Rollout plan (gated)

| Phase | Gate to advance |
|---|---|
| **Phase 0: Offline backtest** on historical claims per payer | AUC > 0.80; per-payer recall floor; calibration reviewed |
| **Phase 1: Gated alpha**: 3-5 practices, one specialty, payer-heavy region; 100% human review; weekly calibration vs actual 835s | acceptance > 60%, override < 20%, no workflow regression |
| **Phase 2: Expand payers before specialties** (payer behaviour transfers across specialties better than the reverse) | clean-claim lift visible vs control |
| **Phase 3: GA** with per-practice ROI reporting and continuous retraining | pre-agreed clean-claim-rate lift sustained 2 quarters |

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Payer rule drift** (rules change quarterly) | weekly per-payer precision monitoring; retraining trigger on calibration error; 835 stream as continuous label source |
| **Automation bias** (billers rubber-stamp) | sampled mandatory manual review of accepted fixes; override always one click |
| **False-positive fatigue** (trust erosion) | threshold is per-practice, tied to biller capacity; precision floor per payer |
| **PHI / HIPAA** | claim-metadata features only; BAA, minimum-necessary access, audit logging in architecture from day one |
| **Cold start** (small specialties/payers) | fall back to cross-specialty payer patterns until volume accrues |
| **Cannibalization worry vs Billing Assistant** | none, shared moat, complementary stages; prevented denials free RCM capacity for the hard (non-preventable) denials |

## 9. Open questions

1. Should the co-pilot also run at stage 2 (front desk, pre-visit) for eligibility-only flags? Earlier is cheaper but a different user and surface.
2. Per-practice vs per-payer-per-practice thresholds, how much configurability before it becomes a support burden?
3. What is the right latency budget at scrubbing time (batch overnight vs real-time on claim save)?
