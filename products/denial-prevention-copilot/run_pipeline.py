#!/usr/bin/env python3
"""
One-command build: regenerates the synthetic warehouse, re-runs the SQL
discovery pack, retrains the risk model, and stages all artifacts the app
reads. Idempotent; pure stdlib.

Run:   python3 run_pipeline.py
Then:  python3 -m http.server 8801 --directory app
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
STEPS = [
    ("Generating synthetic claims warehouse", ["data/generate_claims.py"]),
    ("Running SQL discovery pack",            ["analysis/run_discovery.py"]),
    ("Training denial-risk model + evals",    ["model/train_model.py"]),
]

for label, args in STEPS:
    print(f"\n=== {label} ===")
    subprocess.run([sys.executable] + [os.path.join(ROOT, a) for a in args], check=True)

# Stage model artifacts where the static app can fetch them.
os.makedirs(os.path.join(ROOT, "app", "data"), exist_ok=True)
for src in ("model/model.json", "model/evals.json"):
    shutil.copy(os.path.join(ROOT, src), os.path.join(ROOT, "app", "data"))
print("\nPipeline complete. Serve the app with:")
print("  python3 -m http.server 8801 --directory app")
