"""Gap to best-known solution on a public CVRPLIB instance (EUC_2D .vrp), equal wall-clock budget.
  python scripts/cvrplib_benchmark.py A-n32-k5.vrp --best-known 784 --time 30 --runs 5
Take the best-known value from the CVRPLIB website (do not trust numbers typed from memory)."""
import argparse, os, sys, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qstar.cvrplib import load_vrp
from qstar.runner import compare, METHODS

ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--best-known", type=float, required=True)
ap.add_argument("--time", type=float, default=30); ap.add_argument("--runs", type=int, default=5); a = ap.parse_args()
p = load_vrp(a.file); print(f"{p.name}: n={p.n} Q={p.Q} K={p.K}  best known={a.best_known}")
res = compare(p, METHODS, time_limit=a.time, runs=a.runs)
print(f"{'method':14s} {'best':>9s} {'mean':>9s} {'gap best %':>11s} {'gap mean %':>11s}")
for m, r in res.items():
    print(f"{m:14s} {r['cost']:9.0f} {r['mean_cost']:9.1f} {(r['cost']/a.best_known-1)*100:11.2f} {(r['mean_cost']/a.best_known-1)*100:11.2f}")
