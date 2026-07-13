# NewMed Practice Ops Bottleneck Analyzer

**A working prototype: mine a medical group's operational task events, rank each practice's manual-effort sinks, and quantify, in hours, dollars, and FTEs, what automation would return.**

> Built by [Nayan Lal](https://www.linkedin.com/in/nayanlal) as an AI product management case study. Companion project to the [Denial Prevention Co-Pilot](../denial-prevention-copilot), same fictional platform ("NewMed") and practice group ("Lakeview Specialty Partners"). All data is synthetic.

## The idea

Practices know they are busy; they do not know **where the hours go**. Staff time bleeds away in scheduling calls, manual eligibility checks, paper-intake transcription, prior-auth chasing, and denial rework, but the effort is invisible because it is spread across roles, days, and locations. This tool makes it visible, then does the part most dashboards skip: **it pairs every bottleneck with a specific automation recommendation and a quantified saving.** A bottleneck without a recommendation is just a complaint.

This is the "identify operational bottlenecks using data-driven metrics and propose automation solutions" job, productized, the same instrument-then-aggregate method I used to find and eliminate 100+ hours/month of manual reporting effort in a previous role.

## What it does

- **13-week task-event log** (6,000+ daily aggregates: 8 practices × 12 task types × 4 staff roles) generated with per-practice bottleneck profiles, a GI center drowns in prior-auth; a dermatology front desk in scheduling calls, then analyzed **in SQL** (SQLite).
- **Interactive dashboard**: pick a practice → KPI tiles (manual hours/month, labour cost, FTE-equivalent, automatable share), top-3 bottleneck cards with recommendations mapped to NewMed platform capabilities, hours-by-task chart split into automatable vs residual work, weekly trend, and role cost mix.
- **What-if slider**: model automation adoption (0-100%) → hours returned, labour value, annualized savings, FTE capacity freed, live.
- Note the deliberate framing in the footer of the what-if panel: freed hours are **capacity for patient-facing work**, not automatically headcount reduction. That framing decides whether practice staff adopt or resist the rollout.

## Quickstart

```bash
python3 pipeline.py                          # generate events → SQLite → SQL analysis → app/data.json
python3 -m http.server 8802 --directory app  # open http://localhost:8802
```

Python 3 stdlib only. No dependencies, no API keys.

## Findings in the current dataset

- **3,324 manual hours/month** across the group ≈ **20.8 FTEs** absorbed by manual ops (~$84k/month of labour).
- **69% technically automatable**, but never 100% per task, each task carries a realistic automatable share (85-90% for eligibility/intake; 50-60% where human judgement stays, like denial rework and billing questions).
- Bottleneck profiles are **practice-specific**, which is the product argument for a per-practice recommendation engine rather than a one-size-fits-all playbook.

## Design decisions

- **SQL-first analysis** (`pipeline.py` bottom): the aggregates the app shows are the output of three queries over the event table, the method is the point.
- **Honest automation math**: savings = hours × automatable-share × adoption, at per-role hourly rates. Every assumption is visible in the UI.
- **Recommendations map to platform capabilities** (front-office assistant, digital intake, eligibility automation, PA packet assembly, the Denial Prevention Co-Pilot) so each finding lands as a next step, not an observation.

## Limitations

- Synthetic event log with designed-in bottlenecks; a real deployment would instrument actual PM-system events (call logs, task queues, claim status transitions) and would need to handle measurement gaps.
- Labour rates and task durations are estimates; a real rollout would calibrate them per practice.
