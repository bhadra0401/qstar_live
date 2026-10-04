"""Tests for VRPTW (Time-Window Vehicle Routing Problem)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qstar import synthetic_city, build_problem, algos
from qstar.traffic import FreeFlowProvider
from qstar.ortools_baseline import ortools_solve

def test_vrptw_qstar_and_ortools():
    net = synthetic_city(seed=42)
    stops, dem, tw, serv = net.sample_customers(12, seed=42, with_tw=True)
    assert len(tw) == len(stops) and len(serv) == len(stops)
    
    st = FreeFlowProvider().get_state(net)
    prob = build_problem(net, st, stops, dem, Q=40, tw=tw, service=serv)
    assert prob.tw is not None
    
    cost, hist, routes, secs, _ = algos.qstar(prob, pop=12, iters=20, seed=42)
    assert prob.feasible(routes)
    
    sched = prob.route_schedule(routes[0])
    assert len(sched) > 0
    for s in sched:
        assert s["depart"] >= s["start"] >= s["arr"]
    
    ot_res = ortools_solve(prob, time_limit_s=5)
    assert ot_res is not None
    assert prob.feasible(ot_res[1])
    print(f"PASS VRPTW Q-STAR (cost={cost:.1f}) & OR-Tools (cost={ot_res[0]:.1f})")

if __name__ == "__main__":
    test_vrptw_qstar_and_ortools()
