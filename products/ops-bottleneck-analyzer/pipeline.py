#!/usr/bin/env python3
"""
NewMed Practice Ops Bottleneck Analyzer, data pipeline.

Generates a synthetic 13-week operational task-event log for Lakeview
Specialty Partners (the same fictional 8-practice group used in the
denial-prevention-copilot repo), loads it into SQLite, runs the bottleneck
analysis in SQL, and emits app/data.json for the dashboard.

The core product idea: practices know they are busy; they do not know WHERE
the hours go. Mine the event log, rank each practice's manual-effort sinks,
attach an automation recommendation and a quantified saving to each, and let
the administrator play the "what if we automated X%" question live.

All data is synthetic. Run: python3 pipeline.py
"""
import json
import math
import os
import random
import sqlite3
from datetime import date, timedelta

random.seed(11)
HERE = os.path.dirname(os.path.abspath(__file__))
START = date(2026, 3, 30)   # 13 ISO weeks -> Jun 28, 2026
WEEKS = 13

ROLES = {"Front desk": 22, "Billing": 28, "Clinical staff": 35, "Admin": 30}

# task: (role, avg_minutes, base_events_per_practice_per_day, automatable_share,
#        automation recommendation, which NewMed capability)
TASKS = {
    "Appointment scheduling calls":      ("Front desk", 6, 34, 0.70, "Patient self-scheduling + AI front-office assistant for phone deflection", "NewMed Front Office Assistant"),
    "Reschedule / cancellation handling":("Front desk", 5, 11, 0.65, "Automated waitlist backfill and self-service rescheduling", "NewMed Front Office Assistant"),
    "Manual eligibility verification":   ("Front desk", 7, 18, 0.85, "Batch real-time 270/271 checks 48h pre-visit; exceptions-only review", "NewMed Practice Management (eligibility automation)"),
    "Paper intake form transcription":   ("Front desk", 9, 13, 0.90, "Digital intake sent at booking; data flows straight to the chart", "NewMed Patient Engagement (digital intake)"),
    "Fax & document indexing":           ("Front desk", 4, 15, 0.75, "AI document classification and auto-filing to patient record", "NewMed platform (document AI)"),
    "No-show follow-up outreach":        ("Front desk", 5, 7,  0.80, "Automated reminder cadence + reactivation outreach", "NewMed Patient Engagement"),
    "Prior-auth requests & follow-up":   ("Billing", 22, 6,  0.60, "Auto-assembled PA packets from chart data + payer status tracking", "NewMed Billing tools (PA automation)"),
    "Denial rework & resubmission":      ("Billing", 25, 5,  0.55, "Pre-submission denial risk scoring (see Denial Prevention Co-Pilot)", "Denial Prevention Co-Pilot"),
    "Patient billing questions":         ("Billing", 8, 9,  0.50, "Self-service statements + AI billing chat with human handoff", "NewMed Patient Engagement + Pay"),
    "Referral coordination":             ("Clinical staff", 10, 5, 0.45, "Structured e-referral workflow with status visibility", "NewMed interoperability (API platform)"),
    "Prescription refill requests":      ("Clinical staff", 6, 8, 0.65, "Protocol-based refill triage; clinician reviews exceptions", "NewMed Clinical Assistant"),
    "Manual report assembly":            ("Admin", 15, 2, 0.85, "Scheduled analytics dashboards replace hand-built spreadsheets", "NewMed Analytics"),
}

PRACTICES = [
    ("P01", "Lakeview Dermatology - Downtown",  {"Appointment scheduling calls": 1.6, "Paper intake form transcription": 1.5}),
    ("P02", "Lakeview Dermatology - Northside", {"No-show follow-up outreach": 1.9, "Appointment scheduling calls": 1.3}),
    ("P03", "Lakeview GI Associates",           {"Prior-auth requests & follow-up": 2.1, "Referral coordination": 1.5}),
    ("P04", "Lakeview Endoscopy Center",        {"Prior-auth requests & follow-up": 1.8, "Manual eligibility verification": 1.6}),
    ("P05", "Lakeview Orthopedics - Main",      {"Denial rework & resubmission": 1.8, "Fax & document indexing": 1.7}),
    ("P06", "Lakeview Sports Medicine",         {"Reschedule / cancellation handling": 1.8, "Prescription refill requests": 1.4}),
    ("P07", "Lakeview Eye Institute",           {"Manual eligibility verification": 1.9, "Patient billing questions": 1.5}),
    ("P08", "Lakeview Retina Specialists",      {"Prior-auth requests & follow-up": 1.6, "Denial rework & resubmission": 1.5}),
]


def generate():
    rows = []
    for w in range(WEEKS):
        for d in range(5):  # weekdays
            day = START + timedelta(weeks=w, days=d)
            for pid, pname, skew in PRACTICES:
                for task, (role, avg_min, base, auto, rec, cap) in TASKS.items():
                    lam = base * skew.get(task, 1.0) * random.uniform(0.75, 1.25)
                    # mild growth in scheduling volume over the quarter
                    if task == "Appointment scheduling calls":
                        lam *= 1 + 0.10 * (w / WEEKS)
                    count = max(0, int(random.gauss(lam, math.sqrt(lam))))
                    minutes = sum(max(1, random.gauss(avg_min, avg_min * 0.35)) for _ in range(count))
                    if count:
                        rows.append((day.isoformat(), w + 1, pid, pname, task, role,
                                     count, round(minutes, 1)))
    return rows


def main():
    rows = generate()
    db = os.path.join(HERE, "data", "ops.db")
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE task_events (
        day TEXT, week INTEGER, practice_id TEXT, practice TEXT,
        task TEXT, role TEXT, events INTEGER, minutes REAL)""")
    con.executemany("INSERT INTO task_events VALUES (?,?,?,?,?,?,?,?)", rows)
    con.execute("CREATE TABLE roles (role TEXT PRIMARY KEY, hourly_usd REAL)")
    con.executemany("INSERT INTO roles VALUES (?,?)", ROLES.items())
    con.commit()
    print(f"{len(rows)} daily task aggregates -> {db}")

    # ---------------- bottleneck analysis, in SQL ----------------
    QUERIES = {
        "by_task": """
            -- Where do the hours go? One row per (practice, task).
            SELECT t.practice_id, t.practice, t.task, t.role,
                   -- minutes -> hours (/60), then 13 weeks -> per month (/3)
                   ROUND(SUM(t.minutes)/60.0 / 3.0, 1)          AS hours_per_month,
                   -- hours priced at the role's hourly rate from the roles table
                   ROUND(SUM(t.minutes)/60.0 / 3.0 * r.hourly_usd) AS cost_per_month,
                   SUM(t.events)                                 AS events_13w
            FROM task_events t
            JOIN roles r ON r.role = t.role   -- brings in hourly_usd per role
            GROUP BY t.practice_id, t.task    -- practice+task grain: the app
                                              -- re-aggregates client-side""",
        "weekly_trend": """
            -- Is manual load stable, growing, or seasonal?
            SELECT week, ROUND(SUM(minutes)/60.0, 1) AS hours
            FROM task_events
            GROUP BY week                     -- ISO week number, 1 to 13
            ORDER BY week""",
        "role_mix": """
            -- Which staff role absorbs the cost? Targets the automation pitch.
            SELECT t.role, ROUND(SUM(t.minutes)/60.0 / 3.0, 1) AS hours_per_month,
                   ROUND(SUM(t.minutes)/60.0 / 3.0 * r.hourly_usd) AS cost_per_month
            FROM task_events t JOIN roles r ON r.role = t.role
            GROUP BY t.role
            ORDER BY hours_per_month DESC     -- biggest sink first""",
    }
    con.row_factory = sqlite3.Row
    out = {k: [dict(r) for r in con.execute(q)] for k, q in QUERIES.items()}
    out["sql"] = QUERIES

    meta = {t: dict(role=v[0], avg_minutes=v[1], automatable=v[3],
                    recommendation=v[4], capability=v[5]) for t, v in TASKS.items()}
    out["task_meta"] = meta
    out["roles"] = ROLES
    out["practices"] = [dict(id=p, name=n) for p, n, _ in PRACTICES]

    with open(os.path.join(HERE, "app", "data.json"), "w") as f:
        json.dump(out, f, indent=1)
    total = sum(r["hours_per_month"] for r in out["by_task"])
    print(f"Total manual hours/month across group: {total:,.0f}")
    print("Wrote app/data.json")


if __name__ == "__main__":
    main()
