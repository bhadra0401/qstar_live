"""Benchmark Q-STAR against Clarke-Wright / GA / PSO / QPSO / OR-Tools on a road network + traffic source,
and measure what ignoring live traffic costs.

  python scripts/run_benchmark.py --offline --traffic sim --n 60 --runs 5 --time 10
  python scripts/run_benchmark.py --place "Bengaluru, India" --traffic tomtom --n 60 --runs 5 --time 20
"""
import argparse, os, sys, csv, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qstar import RoadNet, synthetic_city, build_problem, Weights, evaluate_plan_under
from qstar.traffic import SimulatedProvider, FreeFlowProvider, TomTomProvider, ReplayProvider
from qstar.runner import compare, METHODS, run_method

ap = argparse.ArgumentParser()
ap.add_argument("--offline", action="store_true", help="use the synthetic demo city (no internet)")
ap.add_argument("--place"); ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float); ap.add_argument("--radius", type=float, default=2500)
ap.add_argument("--traffic", choices=["sim", "tomtom", "replay"], default="sim"); ap.add_argument("--replay-file")
ap.add_argument("--hour", type=float, default=18.0); ap.add_argument("--n", type=int, default=60); ap.add_argument("--Q", type=int, default=60)
ap.add_argument("--runs", type=int, default=5); ap.add_argument("--time", type=float, default=10.0); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--instances", type=int, default=3, help="different random customer sets")
ap.add_argument("--out", default="results")
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)

net = synthetic_city() if a.offline else RoadNet.from_osm(a.place, (a.lat, a.lon) if a.lat else None, a.radius)
prov = {"sim": lambda: SimulatedProvider(hour=a.hour, seed=a.seed), "tomtom": lambda: TomTomProvider(max_samples=60),
        "replay": lambda: ReplayProvider(a.replay_file)}[a.traffic]()
live = prov.get_state(net)
print(f"network: {net.label}  nodes={net.N} edges={net.E}   traffic: {live.source}  {live.summary()}")
if net.synthetic or a.traffic == "sim":
    print("NOTE: synthetic network and/or simulated traffic -> these numbers are NOT real-world evidence.")

rows = []; impact = []
for inst in range(a.instances):
    nodes, dem = net.sample_customers(a.n, seed=a.seed + inst)
    p = build_problem(net, live, nodes, dem, a.Q)
    res = compare(p, METHODS, time_limit=a.time, runs=a.runs, seed=a.seed)
    cw = res["Clarke-Wright"]["cost"]
    for m, r in res.items():
        d, t, c = p.metrics(r["routes"])
        rows.append(dict(instance=inst, method=m, cost=r["cost"], mean_cost=r["mean_cost"], std=r["std_cost"], vs_CW_pct=(r["cost"] / cw - 1) * 100,
                         km=d, minutes=t, congestion_km=c, secs=r["secs"]))
    # impact of live data: same optimiser, but planned on free-flow speeds, then driven through live traffic
    p_blind = build_problem(net, FreeFlowProvider().get_state(net), nodes, dem, a.Q)
    rb = run_method(p_blind, "Q-STAR", a.time, a.seed)["routes"]
    cb, db, tb, kb = evaluate_plan_under(p_blind, rb, net, live)
    ra = res["Q-STAR"]["routes"]; da, ta, ka = p.metrics(ra)
    impact.append((tb, ta, db, da, kb, ka, cb, p.total(ra)))
    print(f"instance {inst}: " + "  ".join(f"{m}={r['cost']:.0f}" for m, r in res.items()))

with open(os.path.join(a.out, "benchmark.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("\nmethod          mean cost vs Clarke-Wright (%)   mean time(s)")
for m in METHODS:
    rr = [r for r in rows if r["method"] == m]
    if rr: print(f"{m:14s}  {np.mean([r['vs_CW_pct'] for r in rr]):+8.2f}                      {np.mean([r['secs'] for r in rr]):6.1f}")
I = np.array(impact)
print("\nIMPACT OF LIVE TRAFFIC DATA (same optimiser, with vs without live speeds; evaluated under the live state)")
print(f"  travel time  : {I[:,0].mean():.1f} -> {I[:,1].mean():.1f} min   ({(I[:,1].mean()/I[:,0].mean()-1)*100:+.1f}%)")
print(f"  distance     : {I[:,2].mean():.1f} -> {I[:,3].mean():.1f} km    ({(I[:,3].mean()/I[:,2].mean()-1)*100:+.1f}%)")
print(f"  congestion-km: {I[:,4].mean():.1f} -> {I[:,5].mean():.1f}      ({(I[:,5].mean()/I[:,4].mean()-1)*100:+.1f}%)")
print(f"  total cost   : {I[:,6].mean():.1f} -> {I[:,7].mean():.1f}      ({(I[:,7].mean()/I[:,6].mean()-1)*100:+.1f}%)")
print("\nsaved:", os.path.join(a.out, "benchmark.csv"))
