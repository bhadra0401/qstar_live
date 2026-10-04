"""Run all optimisers on one Problem under the SAME wall-clock budget (fair comparison)."""
import time, numpy as np
from . import algos

METHODS = ["Clarke-Wright", "GA+LS", "PSO+LS", "QPSO+LS", "Q-STAR", "OR-Tools"]


def run_method(prob, name, time_limit=10.0, seed=0, init=None, callback=None):
    """returns dict(cost, routes, secs, hist)"""
    t0 = time.perf_counter(); hist = []
    if name == "Clarke-Wright":
        c, r = algos.clarke_wright(prob); r = algos.local_search(prob, r); c = prob.total(r)
    elif name == "GA+LS":
        c, hist, r, _ = algos.ga(prob, pop=20, iters=10 ** 7, seed=seed, ls=True, max_time=time_limit)
    elif name == "PSO+LS":
        c, hist, r, _, _ = algos.swarm(prob, "pso", pop=20, iters=10 ** 7, seed=seed, ls_all=True, max_time=time_limit)
    elif name == "QPSO+LS":
        c, hist, r, _, _ = algos.swarm(prob, "qpso", pop=20, iters=10 ** 7, seed=seed, ls_all=True, max_time=time_limit)
    elif name == "Q-STAR":
        c, hist, r, _, keys = algos.qstar(prob, pop=20, iters=10 ** 7, seed=seed, max_time=time_limit, init=init, callback=callback)
    elif name == "OR-Tools":
        out = None
        try:
            from .ortools_baseline import ortools_solve
            out = ortools_solve(prob, time_limit_s=time_limit)
        except ImportError:
            return None
        if out is None: return None
        c, r, _ = out
    else:
        raise ValueError(name)
    assert prob.feasible(r), f"{name} produced an infeasible plan"
    return dict(cost=float(prob.total(r)), routes=r, secs=time.perf_counter() - t0, hist=list(map(float, hist)),
                keys=(algos.encode(r, prob.n)))


def compare(prob, methods=METHODS, time_limit=10.0, runs=1, seed=0):
    res = {}
    for m in methods:
        outs = [run_method(prob, m, time_limit, seed + k) for k in range(runs if m not in ("Clarke-Wright", "OR-Tools") else 1)]
        if outs[0] is None: continue
        best = min(outs, key=lambda o: o["cost"])
        res[m] = dict(best, mean_cost=float(np.mean([o["cost"] for o in outs])), std_cost=float(np.std([o["cost"] for o in outs])))
    return res
