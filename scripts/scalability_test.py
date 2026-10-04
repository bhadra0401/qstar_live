"""Scalability stress testing script for large-scale VRP / VRPTW demonstration (SIH26137).
Tests scaling from 20 up to 120 customers under equal budgets and records execution metrics.
"""
import os, sys, time, csv, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qstar import RoadNet, build_problem, synthetic_city
from qstar.traffic import FreeFlowProvider, TomTomProvider
from qstar.runner import compare, run_method

def run_scalability_test(n_values=[20, 40, 60, 80, 100], time_budget=5.0, place=None, out="results"):
    os.makedirs(out, exist_ok=True)
    if place:
        print(f"Loading real road network for {place}...")
        net = RoadNet.from_osm(place=place)
    else:
        print("Using synthetic large urban network...")
        net = synthetic_city(rows=24, cols=24, spacing_m=200)
    
    st = FreeFlowProvider().get_state(net)
    print(f"Network: {net.label} | Nodes: {net.N}, Edges: {net.E}")
    
    rows = []
    for n in n_values:
        print(f"\n--- Testing N={n} Customers ---")
        stops, dem, tw, serv = net.sample_customers(n, seed=42, with_tw=True)
        prob = build_problem(net, st, stops, dem, Q=60, tw=tw, service=serv)
        
        t0 = time.perf_counter()
        q_res = run_method(prob, "Q-STAR", time_limit=time_budget, seed=42)
        q_dur = time.perf_counter() - t0
        
        t0 = time.perf_counter()
        cw_res = run_method(prob, "Clarke-Wright", time_limit=time_budget, seed=42)
        cw_dur = time.perf_counter() - t0
        
        ot_res = run_method(prob, "OR-Tools", time_limit=time_budget, seed=42)
        
        row = dict(
            customers=n,
            vehicles_qstar=len(q_res["routes"]),
            cost_qstar=round(q_res["cost"], 2),
            time_qstar_s=round(q_res["secs"], 2),
            cost_cw=round(cw_res["cost"], 2),
            cost_ortools=round(ot_res["cost"], 2) if ot_res else None,
            vs_cw_pct=round((q_res["cost"] / cw_res["cost"] - 1) * 100, 2)
        )
        rows.append(row)
        print(f"Result N={n}: Q-STAR={row['cost_qstar']} | Clarke-Wright={row['cost_cw']} ({row['vs_cw_pct']:+.1f}%) | Vehicles={row['vehicles_qstar']}")
    
    out_file = os.path.join(out, "scalability.csv")
    with open(out_file, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved scalability demonstration metrics to {out_file}")

if __name__ == "__main__":
    run_scalability_test(n_values=[20, 40, 60, 80], time_budget=3.0)
