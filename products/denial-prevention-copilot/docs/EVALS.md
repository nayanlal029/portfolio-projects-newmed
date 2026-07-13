# Evaluation methodology: Denial Prevention Co-Pilot

*How I know the model works, what the numbers mean, and what I would monitor in production. All numbers regenerate from `python3 run_pipeline.py`.*

## 1. Setup

| | |
|---|---|
| Model | Logistic regression, 15 binary features, pure Python (no dependencies) |
| Training window | 2026-01-01 → 2026-04-30 (3,992 claims) |
| Test window | 2026-05-01 → 2026-06-30 (2,008 claims, 325 denials, 16.2% base rate) |
| Split | **Temporal**, by service date |
| Label | claim denied vs paid, from adjudication outcome (835) |

**Why a temporal split and not a random split:** payer rules drift over time. A random split lets the model peek at future payer behaviour during training, which overstates real performance. Training on the past and testing on the future simulates exactly what deployment does. This is the same discipline as backtesting a churn model: evaluate in deployment order.

**Why logistic regression:** the biller must be able to audit every flag ("+2.42 logit: prior auth missing"). A model the user can't interrogate is a model the user overrides into irrelevance. Interpretability is a product requirement here, not a modeling preference. If real-world data shows meaningful interaction effects, the upgrade path is gradient-boosted trees + SHAP explanations, but you earn that complexity with evidence, not by default.

## 2. Results (offline backtest)

- **AUC = 0.853** on the unseen May-Jun window.
- Full threshold sweep exported to `model/evals.json` and explorable on the app's Evals tab.

Selected operating points (test window):

| Threshold | Precision | Recall | Claims flagged | Reading |
|---|---|---|---|---|
| 10% | 39% | 85% | 35% | catches nearly everything, drowns the biller |
| **30% (default)** | **54%** | **59%** | **18%** | ~1 in 2 flags is a real denial; workload ≈ 23 biller-hours/mo per 1,000 claims/mo |
| 50% | 73% | 32% | 7% | high-trust queue, misses two-thirds of denials |
| 70% | 92% | 11% | 2% | near-certain flags only |

**The threshold is a product decision, not a data-science decision.** It trades biller review capacity against denials caught, and the right point differs per practice (a 2-biller dermatology office ≠ a 40-biller RCM operation). That is why the prototype ships it as a slider with live workload and $-impact readouts, and why production ships it as a per-practice setting.

**Cost asymmetry:** a false positive costs ~4 minutes of biller review and a sliver of trust; a false negative costs $25-118 of rework and, ~46% of the time, the entire contracted revenue. This argues for leaning toward recall, but only up to the biller-capacity ceiling, because a flooded queue gets ignored, which is worse than a smaller queue that's trusted. (Identical structure to tuning a churn model where false churn-flags waste retention spend.)

## 3. The economics readout

At the default 30% threshold, scaled to this group's ~1,000 claims/month:

- ~352 claims flagged/month → ~23 biller-hours of review
- Est. **$46,078/month protected** = avoided rework labour + write-off revenue preserved
- Assumptions (all visible in `model/train_model.py`, deliberately conservative): 4 min review per flag; 85% of flagged preventable gaps actually fixable pre-submission; avg rework cost $79; 46% of denials written off at avg $449 lost contracted revenue.

## 4. Honest caveats

1. **Synthetic data flatters the model.** The generator and the model see overlapping feature families, so AUC 0.853 demonstrates the *method*, not real-world accuracy. Real adjudication has unobserved causes (clinical documentation, payer black-box edits); expect lower AUC and re-set expectations per payer.
2. **Noise floor is real, though:** the generator injects payer noise and non-preventable denial causes (medical necessity, duplicates, dx-mismatch) the features cannot see, which is why precision < 100% even here, and why the honest ceiling on "preventable" is ~80%, not 100%.
3. **Class base rate matters:** at 16% base rate, a naive "flag everything" gets 16% precision. The lift over that baseline (54% at the default point, 3.4×) is the meaningful number.

## 5. Production monitoring plan

| Signal | Cadence | Action trigger |
|---|---|---|
| Per-payer precision & recall vs actual 835s | weekly | > 10-pt calibration error for 2 consecutive weeks → retrain |
| Fix-suggestion acceptance rate | weekly | < 60% → review suggestion quality per denial category |
| Override rate | weekly | > 20% or rising → threshold/feature review with alpha practices |
| Payer rule-change feed (837 rejections, new CARC mixes) | continuous | new dominant CARC per payer → feature/rule gap analysis |
| Automation-bias audit (sampled re-review of accepted fixes) | monthly | error rate above baseline → mandatory-review share increases |
| Clean-claim rate vs matched control practices | monthly | the ultimate outcome metric; flat after 2 quarters → revisit product, not just model |

## 6. What the next model iteration would test (with real data)

- Per-payer models vs single pooled model with payer features (bet: pooled first, split when a payer's calibration diverges)
- Line-level features for multi-line claims (fan-out joins are the classic claims-data bug, pre-aggregate to claim grain first)
- Calibrated probabilities (Platt/isotonic) so "70% risk" means 70%, required before showing raw percentages to users at GA
