#!/usr/bin/env python3
"""
Runs analysis/discovery_queries.sql against data/newmed.db, prints results,
writes docs/DISCOVERY.md (the full reasoning trail with query text + results)
and app/data/discovery.json (aggregates consumed by the prototype UI).

Also emits a small aggregation cube keyed by (payer, specialty, month) so the
UI can recompute every KPI and chart client-side when the user filters by
payer or specialty. The cube stays tiny (120 cells) because it aggregates;
no claim-level data ships to the browser.

Run: python3 analysis/run_discovery.py
"""
import json
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "newmed.db")
SQL_FILE = os.path.join(HERE, "discovery_queries.sql")

# Narrative wrapper for each query in DISCOVERY.md: (title, question, takeaway template)
NARRATIVE = {
    "Q1": ("How big is the problem?",
           "Is denial volume material enough to justify a product?"),
    "Q2": ("Where do denials concentrate?",
           "Is this a uniform problem or a payer-specific one?"),
    "Q3": ("Why are claims denied?",
           "What share of denial reasons are knowable BEFORE submission?"),
    "Q4": ("The headline aggregate: the preventable share",
           "The single number that justifies the build."),
    "Q5": ("Monthly trend",
           "Is this getting better on its own? (If yes, no product needed.)"),
    "Q6": ("Cash-flow impact",
           "Denials do not just cost rework labour; they stall cash."),
    "Q7": ("Top denial reason per payer (window function)",
           "Payer-specific patterns are the moat argument."),
    "Q8": ("Fact-pattern audit",
           "Is the risk signal visible at submission time? (Feasibility check.)"),
}


def split_queries(sql_text):
    """Split the .sql file into (qid, comment_block, query) tuples."""
    blocks = re.split(r"\n(?=-- Q\d+ ::)", sql_text)
    out = []
    for b in blocks:
        m = re.match(r"-- (Q\d+) ::", b)
        if not m:
            continue
        qid = m.group(1)
        comment_lines, sql_lines = [], []
        for line in b.splitlines():
            (comment_lines if line.startswith("--") else sql_lines).append(line)
        out.append((qid, "\n".join(comment_lines), "\n".join(sql_lines).strip()))
    return out


def run():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    queries = split_queries(open(SQL_FILE).read())

    md = ["# Discovery: the SQL trail that led to the Denial Prevention Co-Pilot",
          "",
          "*This document is the reasoning, not just the result.* Before proposing",
          "any product, I profiled six months of claims for Lakeview Specialty",
          "Partners (synthetic 8-practice group, 6,000 claims, Jan-Jun 2026) in the",
          "NewMed claims warehouse. Each section below is one product question, the",
          "SQL that answers it, the actual result, and what it implied for the",
          "build/no-build decision.",
          "",
          "> Data is synthetic (see `data/generate_claims.py`). Codes (CPT, ICD-10,",
          "> CARC) are real industry vocabulary; payer names other than",
          "> Medicare/Medicaid are fictional.",
          ""]
    app_data = {}

    for qid, _comment, sql in queries:
        cur = con.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        cols = list(rows[0].keys()) if rows else []
        title, question = NARRATIVE[qid]

        md.append(f"## {qid}. {title}")
        md.append(f"\n**Product question:** {question}\n")
        md.append("```sql\n" + sql + "\n```\n")
        if rows:
            md.append("| " + " | ".join(cols) + " |")
            md.append("|" + "---|" * len(cols))
            for r in rows:
                md.append("| " + " | ".join(
                    "" if r[c] is None else str(r[c]) for c in cols) + " |")
        md.append("")
        app_data[qid] = dict(title=title, question=question, sql=sql, rows=rows)
        print(f"{qid}: {len(rows)} rows")

    # ---------------- filter cube for the interactive UI --------------------
    con.row_factory = sqlite3.Row
    carc_meta = {r["carc"]: (r["category"], r["preventable_presubmission"])
                 for r in con.execute("SELECT * FROM denial_codes")}
    cube = {}
    claims = con.execute("""
        SELECT c.*, p.timely_filing_days FROM claims c
        JOIN payers p ON p.payer = c.payer""").fetchall()
    for r in claims:
        key = (r["payer"], r["specialty"], r["service_date"][:7])
        cell = cube.setdefault(key, dict(
            n=0, d=0, dc=0.0, rw=0.0, wo=0,
            cat={}, gaps=dict(pa=[0, 0], el=[0, 0], mod=[0, 0], tf=[0, 0], clean=[0, 0]),
            pay=[0, 0.0], rec=[0, 0.0]))
        denied = r["status"] == "denied"
        cell["n"] += 1
        if denied:
            cell["d"] += 1
            cell["dc"] += r["charge_amount"]
            cell["rw"] += r["rework_cost"]
            if r["final_outcome"] == "written_off":
                cell["wo"] += 1
            cat = carc_meta[r["denial_code"]][0]
            cell["cat"][cat] = cell["cat"].get(cat, 0) + 1
        if r["final_outcome"] == "paid_first_pass":
            cell["pay"][0] += 1; cell["pay"][1] += r["days_to_payment"]
        elif r["final_outcome"] == "recovered_after_rework":
            cell["rec"][0] += 1; cell["rec"][1] += r["days_to_payment"]
        # gap patterns mirror Q8 exactly (patterns can overlap by design)
        pa = r["prior_auth_required"] == 1 and r["prior_auth_obtained"] == 0
        el = r["eligibility_verified"] == 0 or r["elig_stale_days"] > 60
        mod = r["modifier_required"] == 1 and r["modifier_present"] == 0
        tf = r["days_to_submit"] > r["timely_filing_days"]
        clean = not pa and not el and not mod and r["has_missing_fields"] == 0
        for flag, k in ((pa, "pa"), (el, "el"), (mod, "mod"), (tf, "tf"), (clean, "clean")):
            if flag:
                cell["gaps"][k][0] += 1
                if denied:
                    cell["gaps"][k][1] += 1
    app_data["cube"] = [dict(p=k[0], s=k[1], m=k[2], **v) for k, v in sorted(cube.items())]
    app_data["cat_preventable"] = {cat: prev for cat, prev in carc_meta.values()}
    print(f"cube: {len(app_data['cube'])} cells")

    # Takeaways written after seeing the numbers (kept in one place so they
    # stay in sync with regenerated data).
    q1 = app_data["Q1"]["rows"][0]
    q4 = app_data["Q4"]["rows"][0]
    md.append("## The decision\n")
    md.append(f"- **{q1['denial_rate_pct']}% denial rate** against an industry norm of 10-15%: "
              f"~${q1['denied_charges_usd']:,.0f} of charges denied in six months, "
              f"~${q1['rework_cost_usd']:,.0f} spent on rework, and "
              f"{q1['pct_denials_written_off']}% of denials never recovered at all.")
    md.append(f"- **{q4['preventable_pct_of_denials']}% of denials are preventable at "
              f"submission time** (eligibility, prior auth, modifiers, missing info, "
              f"timely filing), worth ~${q4['preventable_charges_usd']:,.0f} in charges.")
    md.append("- Denials concentrate by payer AND the dominant reason differs per payer "
              "(Q2, Q7). Generic claim-scrubber rules underfit; a model that learns "
              "payer-specific patterns has a structural edge.")
    md.append("- The signal is visible **before** submission (Q8): claims with a "
              "known gap deny at 5-10x the clean-claim rate. A pre-submission risk "
              "score is feasible with data the platform already holds.")
    md.append("\n**Decision: build a pre-submission Denial Prevention Co-Pilot.** "
              "Score every claim at claim-scrubbing time, flag high-risk claims with "
              "the predicted denial reason and a one-click fix, keep the biller in "
              "the loop, and feed every override back into the model.")

    docs = os.path.join(ROOT, "docs", "DISCOVERY.md")
    with open(docs, "w") as f:
        f.write("\n".join(md) + "\n")
    app_dir = os.path.join(ROOT, "app", "data")
    os.makedirs(app_dir, exist_ok=True)
    with open(os.path.join(app_dir, "discovery.json"), "w") as f:
        json.dump(app_data, f, indent=1)
    print(f"Wrote {docs} and app/data/discovery.json")


if __name__ == "__main__":
    run()
