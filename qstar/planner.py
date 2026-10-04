"""Stateful planner = the dynamic loop of the book: traffic update -> new cost matrix -> drift test -> warm-start re-optimisation."""
import time, numpy as np
from .problem import build_problem, evaluate_plan_under, Weights
from .runner import run_method
from .traffic import FreeFlowProvider


class Planner:
    def __init__(self, net, provider, stop_nodes, demands, Q, K=None, weights=Weights(), time_limit=10.0, method="Q-STAR", tw=None, service=None):
        self.net, self.provider = net, provider
        self.stops, self.dem, self.Q, self.K, self.w = stop_nodes, demands, Q, K, weights
        self.time_limit, self.method = time_limit, method
        self.tw, self.service = tw, service
        self.state = self.prob = self.plan = None
        self.log = []

    def _build(self, state):
        return build_problem(self.net, state, self.stops, self.dem, self.Q, self.K, self.w, tw=self.tw, service=self.service)

    def optimise(self):
        t0 = time.perf_counter()
        self.state = self.provider.get_state(self.net); self.prob = self._build(self.state)
        build_s = time.perf_counter() - t0
        self.plan = run_method(self.prob, self.method, self.time_limit)
        self.log.append(dict(event="initial plan", t=time.time(), cost=self.plan["cost"], drift_pct=0.0, reoptimised=True,
                             build_s=build_s, solve_s=self.plan["secs"], source=self.state.source))
        return self.plan

    def refresh(self, drift_threshold=0.03, force=False):
        """pull fresh traffic; keep the current plan if it is still good, otherwise warm-start a short re-optimisation"""
        t0 = time.perf_counter()
        self.provider_state = self.provider.get_state(self.net)
        new_prob = self._build(self.provider_state); build_s = time.perf_counter() - t0
        stale = new_prob.total(self.plan["routes"])                     # old plan under the new traffic
        # cost the old plan had when it was made, measured on the *old* matrix
        drift = (stale - self.plan["cost"]) / self.plan["cost"]
        re = force or abs(drift) > drift_threshold
        ev = dict(event="traffic update", t=time.time(), stale_cost=stale, drift_pct=drift * 100, reoptimised=re,
                  build_s=build_s, source=self.provider_state.source)
        if re:
            keys = self.plan.get("keys")
            new = run_method(new_prob, self.method, max(2.0, self.time_limit * 0.3), init=keys if self.method == "Q-STAR" else None)
            ev.update(cost=new["cost"], solve_s=new["secs"], saving_vs_stale_pct=(1 - new["cost"] / stale) * 100)
            self.plan = new
        else:
            self.plan = dict(self.plan, cost=stale)
            ev.update(cost=stale, solve_s=0.0, saving_vs_stale_pct=0.0)
        self.state, self.prob = self.provider_state, new_prob
        self.log.append(ev); return ev

    def blind_comparison(self):
        """cost of the same optimiser *without* live traffic data, driven through the current traffic"""
        p_blind = self._build(FreeFlowProvider().get_state(self.net))
        rb = run_method(p_blind, self.method, self.time_limit)["routes"]
        c, d, t, k = evaluate_plan_under(p_blind, rb, self.net, self.state, self.w)
        da, ta, ka = self.prob.metrics(self.plan["routes"])
        return dict(blind=dict(cost=c, km=d, minutes=t, cong=k), aware=dict(cost=self.plan["cost"], km=da, minutes=ta, cong=ka))
