#!/usr/bin/env python3
"""
Denial-risk model: pure-Python logistic regression (no dependencies).

Deliberate choices, in product terms:
- LOGISTIC REGRESSION, not a deep model: every risk score must be explainable
  to a biller ("flagged because prior auth is missing for a payer that denies
  70% of such claims"). Interpretability IS the product requirement; the biller
  must be able to audit why a claim was flagged, or they stop trusting the queue.
- TEMPORAL SPLIT, not random: train on Jan-Apr 2026, evaluate on May-Jun 2026.
  A random split would leak future payer behaviour into training and overstate
  performance. Payer rules drift; the eval must simulate deployment order.
- THRESHOLD SWEEP exported, not a single number: the operating threshold is a
  product decision (biller review capacity vs denials caught), not a data
  science decision. The prototype exposes it as a slider.

Outputs: model/model.json, model/evals.json, app/data/queue.json
Run:     python3 model/train_model.py
"""
import json
import math
import os
import random
import sqlite3

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "newmed.db")

FEATURES = [
    # (name, human label shown in the UI when the factor contributes)
    ("pa_gap",          "Prior authorization required but not on file"),
    ("elig_gap",        "Eligibility unverified or verification stale (>60 days)"),
    ("mod_gap",         "Required modifier missing from claim line"),
    ("missing_fields",  "Claim record has missing/incomplete fields"),
    ("timely_exceeded", "Already past this payer's timely-filing limit"),
    ("timely_near",     "Within 20% of this payer's timely-filing limit"),
    ("resubmission",    "This is a resubmission of a prior claim"),
    ("high_charge",     "High-dollar claim (charge > $1,000)"),
    ("payer_medicaid",  "Payer: Medicaid (highest eligibility churn)"),
    ("payer_unityhealth", "Payer: UnityHealth (strictest prior-auth policy)"),
    ("payer_medicare",  "Payer: Medicare"),
    ("payer_blueshield", "Payer: BlueShield Plus"),
    ("spec_gi",         "Specialty: Gastroenterology"),
    ("spec_ortho",      "Specialty: Orthopedics"),
    ("spec_ophth",      "Specialty: Ophthalmology"),
]
FEATURE_NAMES = [f for f, _ in FEATURES]


def featurize(row, timely_limit):
    ratio = row["days_to_submit"] / timely_limit
    return {
        "pa_gap": int(row["prior_auth_required"] == 1 and row["prior_auth_obtained"] == 0),
        "elig_gap": int(row["eligibility_verified"] == 0 or row["elig_stale_days"] > 60),
        "mod_gap": int(row["modifier_required"] == 1 and row["modifier_present"] == 0),
        "missing_fields": int(row["has_missing_fields"] == 1),
        "timely_exceeded": int(ratio > 1.0),
        "timely_near": int(0.8 < ratio <= 1.0),
        "resubmission": int(row["is_resubmission"] == 1),
        "high_charge": int(row["charge_amount"] > 1000),
        "payer_medicaid": int(row["payer"] == "Medicaid"),
        "payer_unityhealth": int(row["payer"] == "UnityHealth"),
        "payer_medicare": int(row["payer"] == "Medicare"),
        "payer_blueshield": int(row["payer"] == "BlueShield Plus"),
        "spec_gi": int(row["specialty"] == "Gastroenterology"),
        "spec_ortho": int(row["specialty"] == "Orthopedics"),
        "spec_ophth": int(row["specialty"] == "Ophthalmology"),
    }


def sigmoid(z):
    if z < -30: return 1e-13
    if z > 30: return 1.0 - 1e-13
    return 1.0 / (1.0 + math.exp(-z))


def train(X, y, epochs=400, lr=0.5, l2=1e-4):
    n, d = len(X), len(X[0])
    w, b = [0.0] * d, 0.0
    for _ in range(epochs):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(X, y):
            err = sigmoid(b + sum(w[j] * xi[j] for j in range(d))) - yi
            for j in range(d):
                if xi[j]:
                    gw[j] += err * xi[j]
            gb += err
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * gb / n
    return w, b


def auc_score(scores, labels):
    pairs = sorted(zip(scores, labels))
    pos = sum(labels); neg = len(labels) - pos
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0
        rank_sum += avg_rank * sum(1 for k in range(i, j) if pairs[k][1] == 1)
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT c.*, p.timely_filing_days FROM claims c JOIN payers p ON p.payer=c.payer")]

    train_rows = [r for r in rows if r["service_date"] < "2026-05-01"]
    test_rows = [r for r in rows if r["service_date"] >= "2026-05-01"]
    print(f"Temporal split: {len(train_rows)} train (Jan-Apr) / {len(test_rows)} test (May-Jun)")

    def to_xy(rs):
        X = [[featurize(r, r["timely_filing_days"])[f] for f in FEATURE_NAMES] for r in rs]
        y = [1 if r["status"] == "denied" else 0 for r in rs]
        return X, y

    Xtr, ytr = to_xy(train_rows)
    Xte, yte = to_xy(test_rows)
    w, b = train(Xtr, ytr)
    scores = [sigmoid(b + sum(w[j] * x[j] for j in range(len(w)))) for x in Xte]
    auc = auc_score(scores, yte)
    print(f"Test AUC: {auc:.3f} | test base denial rate: {sum(yte)/len(yte):.1%}")

    # ------------------------- economics inputs (from the data itself) ------
    denied = [r for r in rows if r["status"] == "denied"]
    avg_rework = sum(r["rework_cost"] for r in denied) / len(denied)
    writeoff_rate = sum(1 for r in denied if r["final_outcome"] == "written_off") / len(denied)
    # Revenue actually lost on a written-off claim ~= expected contracted payment
    avg_lost_revenue = (sum(r["charge_amount"] for r in denied) / len(denied)) * 0.50
    econ = dict(
        avg_rework_cost=round(avg_rework, 2),
        writeoff_rate=round(writeoff_rate, 3),
        avg_lost_revenue_per_writeoff=round(avg_lost_revenue, 2),
        review_minutes_per_flag=4,
        fix_success_rate=0.85,  # share of flagged preventable gaps a biller can actually fix
        monthly_claims=round(len(rows) / 6),
    )

    # ------------------------- threshold sweep ------------------------------
    sweep = []
    for t_pct in range(2, 96, 2):
        t = t_pct / 100.0
        tp = sum(1 for s, yv in zip(scores, yte) if s >= t and yv == 1)
        fp = sum(1 for s, yv in zip(scores, yte) if s >= t and yv == 0)
        fn = sum(1 for s, yv in zip(scores, yte) if s < t and yv == 1)
        tn = len(yte) - tp - fp - fn
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        sweep.append(dict(threshold=t, tp=tp, fp=fp, fn=fn, tn=tn,
                          precision=round(prec, 3) if prec is not None else None,
                          recall=round(rec, 3) if rec is not None else None,
                          flagged=tp + fp,
                          flagged_pct=round(100.0 * (tp + fp) / len(yte), 1)))

    with open(os.path.join(HERE, "model.json"), "w") as f:
        json.dump(dict(
            model="logistic_regression_pure_python",
            trained="2026-07-13", train_window="2026-01-01..2026-04-30",
            test_window="2026-05-01..2026-06-30",
            features=[dict(name=n, label=l, weight=round(w[i], 4))
                      for i, (n, l) in enumerate(FEATURES)],
            bias=round(b, 4)), f, indent=1)
    with open(os.path.join(HERE, "evals.json"), "w") as f:
        json.dump(dict(
            auc=round(auc, 3),
            test_n=len(yte), test_denials=sum(yte),
            test_base_rate=round(sum(yte) / len(yte), 3),
            economics=econ, sweep=sweep), f, indent=1)

    # ------------------------- co-pilot queue -------------------------------
    # Simulated pre-submission queue: late-June claims, enriched with facts the
    # UI needs. Mix guaranteed: take the 14 highest-risk + 10 random others.
    pool = [r for r in test_rows if r["service_date"] >= "2026-06-15"]
    scored_pool = []
    for r in pool:
        feats = featurize(r, r["timely_filing_days"])
        s = sigmoid(b + sum(w[j] * feats[FEATURE_NAMES[j]] for j in range(len(w))))
        scored_pool.append((s, r, feats))
    scored_pool.sort(key=lambda x: -x[0])
    chosen = scored_pool[:14] + random.sample(scored_pool[14:], 10)
    random.shuffle(chosen)
    queue = []
    for s, r, feats in chosen:
        queue.append(dict(
            claim_id=r["claim_id"], practice=r["practice"], specialty=r["specialty"],
            payer=r["payer"], patient_id=r["patient_id"], service_date=r["service_date"],
            cpt_code=r["cpt_code"], cpt_desc=r["cpt_desc"], icd10_code=r["icd10_code"],
            charge_amount=r["charge_amount"], days_to_submit=r["days_to_submit"],
            timely_limit=r["timely_filing_days"], elig_stale_days=r["elig_stale_days"],
            features=feats,
            actual_status=r["status"], actual_denial_code=r["denial_code"]))
    app_dir = os.path.join(ROOT, "app", "data")
    os.makedirs(app_dir, exist_ok=True)
    with open(os.path.join(app_dir, "queue.json"), "w") as f:
        json.dump(queue, f, indent=1)
    print(f"Wrote model/model.json, model/evals.json, app/data/queue.json ({len(queue)} queue claims)")


if __name__ == "__main__":
    main()
