#!/usr/bin/env python3
"""
Synthetic claims-warehouse generator for the NewMed Denial Prevention Co-Pilot.

Generates ~6,000 professional claims (Jan-Jun 2026) for "Lakeview Specialty
Partners", a fictional 8-practice multi-specialty group on the NewMed platform.

Design notes
------------
- All data is SYNTHETIC. Payer names other than Medicare/Medicaid are fictional.
- CPT / ICD-10 / CARC codes are real industry vocabulary, used so the prototype
  speaks the language billers actually use.
- Denials are generated from a causal process (eligibility gaps, missing prior
  auth, missing modifiers, timely-filing breaches, payer strictness) plus noise,
  so that a risk model has real signal to learn AND a residual it cannot see --
  mirroring how real adjudication behaves.

Outputs: data/newmed.db (SQLite) and data/claims.csv
Run:     python3 data/generate_claims.py
"""
import csv
import math
import os
import random
import sqlite3
from datetime import date, timedelta

random.seed(42)
HERE = os.path.dirname(os.path.abspath(__file__))

N_CLAIMS = 6000
START = date(2026, 1, 1)
END = date(2026, 6, 30)
DAYS = (END - START).days

# ---------------------------------------------------------------- payers ----
# timely_filing: days allowed from service date to submission.
# pa_denial_strictness / elig_volatility: knobs that shape denial behaviour.
PAYERS = {
    "Medicare":        dict(type="government", mix=0.30, timely=365, contract=0.42, pa_strict=0.40, elig_vol=0.03, mod_strict=0.85, base_adj=0.00),
    "Medicaid":        dict(type="government", mix=0.15, timely=95,  contract=0.35, pa_strict=0.75, elig_vol=0.40, mod_strict=0.30, base_adj=0.90),
    "BlueShield Plus": dict(type="commercial", mix=0.25, timely=180, contract=0.58, pa_strict=0.55, elig_vol=0.12, mod_strict=0.40, base_adj=0.15),
    "UnityHealth":     dict(type="commercial", mix=0.18, timely=90,  contract=0.55, pa_strict=0.95, elig_vol=0.04, mod_strict=0.35, base_adj=0.50),
    "SunCoast Health": dict(type="commercial", mix=0.12, timely=120, contract=0.60, pa_strict=0.50, elig_vol=0.06, mod_strict=0.40, base_adj=0.00),
}

# ------------------------------------------------------------ procedures ----
# (cpt, description, avg_charge, pa_required, modifier_required, weight)
CPTS = {
    "Dermatology": [
        ("11102", "Skin biopsy, tangential, first lesion",        160,  False, True,  0.30),
        ("17000", "Destruction of premalignant lesion (AK)",      130,  False, False, 0.25),
        ("11402", "Excision benign lesion, 1.1-2.0 cm",           360,  False, True,  0.15),
        ("96910", "Photochemotherapy (UVB)",                      95,   True,  False, 0.10),
        ("88305", "Surgical pathology, level IV",                 90,   False, False, 0.20),
    ],
    "Gastroenterology": [
        ("45380", "Colonoscopy with biopsy",                      1250, True,  False, 0.35),
        ("43239", "Upper GI endoscopy (EGD) with biopsy",         920,  True,  False, 0.30),
        ("45378", "Colonoscopy, diagnostic",                      980,  True,  False, 0.25),
        ("91110", "Capsule endoscopy, small intestine",           1850, True,  False, 0.10),
    ],
    "Orthopedics": [
        ("20610", "Arthrocentesis, major joint (injection)",      260,  False, True,  0.35),
        ("29881", "Knee arthroscopy with meniscectomy",           2600, True,  True,  0.15),
        ("73721", "MRI, lower extremity joint",                   1450, True,  False, 0.20),
        ("97110", "Therapeutic exercise, 15 min (PT)",            80,   False, False, 0.30),
    ],
    "Ophthalmology": [
        ("66984", "Cataract surgery with IOL insertion",          1900, True,  True,  0.20),
        ("67028", "Intravitreal injection of pharmacologic agent",1150, True,  True,  0.20),
        ("92083", "Visual field examination, extended",           155,  False, False, 0.25),
        ("92014", "Comprehensive eye exam, established patient",  185,  False, False, 0.35),
    ],
}

ICD10 = {
    "Dermatology":      ["D48.5", "L57.0", "D22.9", "L40.0", "C44.319"],
    "Gastroenterology": ["K21.9", "K50.90", "Z12.11", "K92.1", "K58.0"],
    "Orthopedics":      ["M17.11", "M25.561", "M54.16", "S83.242A", "M75.101"],
    "Ophthalmology":    ["H25.11", "H35.32", "E11.311", "H40.11X1", "H52.4"],
}

PRACTICES = [
    ("P01", "Lakeview Dermatology - Downtown",   "Dermatology"),
    ("P02", "Lakeview Dermatology - Northside",  "Dermatology"),
    ("P03", "Lakeview GI Associates",            "Gastroenterology"),
    ("P04", "Lakeview Endoscopy Center",         "Gastroenterology"),
    ("P05", "Lakeview Orthopedics - Main",       "Orthopedics"),
    ("P06", "Lakeview Sports Medicine",          "Orthopedics"),
    ("P07", "Lakeview Eye Institute",            "Ophthalmology"),
    ("P08", "Lakeview Retina Specialists",       "Ophthalmology"),
]

# CARC = Claim Adjustment Reason Code (the payer's coded denial reason on the 835)
DENIAL_CODES = {
    "CO-27":  ("Expenses incurred after coverage terminated", "Eligibility", True),
    "CO-197": ("Precertification/authorization absent",       "Prior authorization", True),
    "CO-4":   ("Procedure code inconsistent with modifier",   "Coding / modifier", True),
    "CO-16":  ("Claim lacks information needed for adjudication", "Missing information", True),
    "CO-29":  ("Time limit for filing has expired",           "Timely filing", True),
    "CO-11":  ("Diagnosis inconsistent with procedure",       "Coding / diagnosis", False),
    "CO-50":  ("Non-covered: not deemed medically necessary", "Medical necessity", False),
    "CO-18":  ("Exact duplicate claim/service",               "Duplicate", False),
}


def sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z))


def pick_weighted(pairs):
    r, acc = random.random(), 0.0
    for item, w in pairs:
        acc += w
        if r <= acc:
            return item
    return pairs[-1][0]


def make_claim(i):
    payer = pick_weighted([(p, cfg["mix"]) for p, cfg in PAYERS.items()])
    pcfg = PAYERS[payer]
    practice_id, practice, specialty = random.choice(PRACTICES)
    cpt, desc, avg_charge, pa_req, mod_req, _ = pick_weighted(
        [(row, row[5]) for row in CPTS[specialty]])
    icd = random.choice(ICD10[specialty])
    provider_id = f"{practice_id}-DR{random.randint(1, 4)}"
    coder_id = f"CD{random.randint(1, 6):02d}"

    service_date = START + timedelta(days=random.randint(0, DAYS))
    # Submission lag: mostly prompt, with a long backlog tail.
    if random.random() < 0.955:
        lag = max(1, int(random.lognormvariate(1.9, 0.7)))          # ~4-15 days
    else:
        lag = random.randint(60, 160)                                # backlog tail
    submission_date = service_date + timedelta(days=lag)

    charge = round(avg_charge * random.uniform(0.85, 1.20), 2)

    # -------- pre-submission fact pattern (what the co-pilot can see) --------
    elig_verified = random.random() < (0.95 - 0.35 * pcfg["elig_vol"])
    elig_stale_days = 0
    if elig_verified:
        # Medicaid coverage churns fastest -> verifications go stale.
        elig_stale_days = int(random.expovariate(1 / 15.0) * (1 + 5 * pcfg["elig_vol"]))
    pa_obtained = (random.random() < (0.99 - 0.17 * pcfg["pa_strict"])) if pa_req else True
    mod_present = (random.random() < 0.92) if mod_req else True
    missing_fields = random.random() < 0.05
    resubmission = random.random() < 0.06

    pa_gap = pa_req and not pa_obtained
    elig_gap = (not elig_verified) or elig_stale_days > 60
    mod_gap = mod_req and not mod_present
    timely_exceeded = lag > pcfg["timely"]

    # ----------------- adjudication: causal logit + noise --------------------
    z = -3.55 + pcfg["base_adj"]
    z += 3.5 * pa_gap + 2.6 * elig_gap + (1.6 + 2.2 * pcfg["mod_strict"]) * mod_gap
    z += 1.9 * missing_fields + 6.0 * timely_exceeded
    z += 0.35 * (charge > 1000) + 0.45 * resubmission
    z += random.gauss(0, 0.4)
    denied = random.random() < sigmoid(z)

    if denied:
        # Attribute the denial to the strongest triggered cause (with slippage).
        causes = []
        if timely_exceeded: causes.append(("CO-29", 6.0))
        if pa_gap:          causes.append(("CO-197", 3.5))
        if elig_gap:        causes.append(("CO-27", 2.6))
        if mod_gap:         causes.append(("CO-4", 2.4))
        if missing_fields:  causes.append(("CO-16", 1.9))
        if causes:
            total = sum(w for _, w in causes)
            code = pick_weighted([(c, w / total) for c, w in causes])
        else:
            code = pick_weighted([("CO-11", 0.50), ("CO-50", 0.30), ("CO-18", 0.20)])
        status = "denied"
        paid = 0.0
        # Rework economics: industry range ~$25-$118 per reworked claim.
        rework_cost = round(random.uniform(25, 118) * (1.15 if charge > 1000 else 1.0), 2)
        recovered = random.random() < 0.55
        days_to_payment = random.randint(60, 130) if recovered else None
        outcome = "recovered_after_rework" if recovered else "written_off"
    else:
        status = "paid"
        code = None
        paid = round(charge * pcfg["contract"] * random.uniform(0.92, 1.05), 2)
        rework_cost = 0.0
        days_to_payment = random.randint(14, 45)
        outcome = "paid_first_pass"

    return dict(
        claim_id=f"CLM-2026-{i:05d}", practice_id=practice_id, practice=practice,
        specialty=specialty, provider_id=provider_id, coder_id=coder_id,
        payer=payer, payer_type=pcfg["type"], patient_id=f"PT{random.randint(10000, 99999)}",
        service_date=service_date.isoformat(), submission_date=submission_date.isoformat(),
        days_to_submit=lag, cpt_code=cpt, cpt_desc=desc, icd10_code=icd,
        charge_amount=charge, eligibility_verified=int(elig_verified),
        elig_stale_days=elig_stale_days, prior_auth_required=int(pa_req),
        prior_auth_obtained=int(pa_obtained), modifier_required=int(mod_req),
        modifier_present=int(mod_present), has_missing_fields=int(missing_fields),
        is_resubmission=int(resubmission), status=status, denial_code=code,
        paid_amount=paid, rework_cost=rework_cost,
        days_to_payment=days_to_payment, final_outcome=outcome,
    )


def main():
    claims = [make_claim(i + 1) for i in range(N_CLAIMS)]
    denial_rate = sum(c["status"] == "denied" for c in claims) / len(claims)
    print(f"Generated {len(claims)} claims | denial rate {denial_rate:.1%}")

    csv_path = os.path.join(HERE, "claims.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(claims[0].keys()))
        w.writeheader()
        w.writerows(claims)

    db_path = os.path.join(HERE, "newmed.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""CREATE TABLE payers (
        payer TEXT PRIMARY KEY, payer_type TEXT, timely_filing_days INTEGER,
        avg_contract_rate REAL)""")
    cur.executemany("INSERT INTO payers VALUES (?,?,?,?)",
                    [(p, c["type"], c["timely"], c["contract"]) for p, c in PAYERS.items()])
    cur.execute("""CREATE TABLE denial_codes (
        carc TEXT PRIMARY KEY, description TEXT, category TEXT,
        preventable_presubmission INTEGER)""")
    cur.executemany("INSERT INTO denial_codes VALUES (?,?,?,?)",
                    [(k, v[0], v[1], int(v[2])) for k, v in DENIAL_CODES.items()])
    cols = list(claims[0].keys())
    col_defs = ", ".join(f"{c} TEXT" if c in
                         ("claim_id", "practice_id", "practice", "specialty", "provider_id",
                          "coder_id", "payer", "payer_type", "patient_id", "service_date",
                          "submission_date", "cpt_code", "cpt_desc", "icd10_code", "status",
                          "denial_code", "final_outcome")
                         else f"{c} REAL" for c in cols)
    cur.execute(f"CREATE TABLE claims ({col_defs})")
    cur.executemany(f"INSERT INTO claims VALUES ({','.join('?' * len(cols))})",
                    [[c[k] for k in cols] for c in claims])
    con.commit()
    con.close()
    print(f"Wrote {csv_path} and {db_path}")


if __name__ == "__main__":
    main()
