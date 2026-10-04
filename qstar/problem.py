"""Problem container + construction from a road network and a traffic state."""
import numpy as np
from dataclasses import dataclass, field
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from .algos import KPEN


@dataclass
class Weights:
    time: float = 1.0        # alpha  (per minute)
    dist: float = 0.3        # beta   (per km)
    cong: float = 0.6        # gamma  (per congestion-km)


class Problem:
    """Capacitated / Time-Window VRP over a (possibly directed) cost matrix.  Index 0 is the depot."""

    def __init__(self, G, dem, Q, K=None, D=None, T=None, C=None, ctx=None, tw=None, service=None, tw_pen=5.0):
        G = np.asarray(G, float)
        self.Gn = G; self.G = G.tolist(); self.n = len(G) - 1
        assert len(dem) == len(G), 'demand list must include the depot at index 0'
        self.dem = [0] + [int(x) for x in dem[1:]]
        self.Q = Q
        self.K = K if K is not None else int(np.ceil(sum(self.dem) / Q)) + 1
        self.kpen = KPEN
        self.sym = bool(np.allclose(G, G.T, rtol=1e-6, atol=1e-9))
        self.D, self.T, self.C = D, T, C          # distance / time / congestion of the least-cost legs
        self.ctx = ctx                              # (net, stop_nodes, pred, weights) when built from a road net
        self.tw = tw                                # [(early_min, late_min), ...] for each stop
        self.service = service if service is not None else ([0.0] * (self.n + 1))
        self.tw_pen = tw_pen                        # cost penalty per minute of lateness

    def route_schedule(self, r):
        """Calculates stop schedule (arrival, service start, departure, wait, lateness)."""
        sched = []
        t = 0.0
        T = self.T if self.T is not None else self.Gn
        seq = [0] + r + [0]
        cur = 0
        for nxt in seq[1:]:
            travel = float(T[cur, nxt])
            arr = t + travel
            e, l = (self.tw[nxt] if self.tw else (0.0, 1e9))
            start = max(arr, e)
            serv = float(self.service[nxt]) if self.service else 0.0
            depart = start + serv
            wait = start - arr
            late = max(0.0, arr - l)
            sched.append(dict(stop=nxt, arr=round(arr, 1), start=round(start, 1),
                              depart=round(depart, 1), wait=round(wait, 1), late=round(late, 1)))
            t = depart
            cur = nxt
        return sched

    def route_cost(self, r):
        G = self.G; c = G[0][r[0]] + G[r[-1]][0]
        for a, b in zip(r[:-1], r[1:]): c += G[a][b]
        if self.tw:
            sched = self.route_schedule(r)
            c += sum(s["late"] for s in sched) * self.tw_pen
        return c

    def total(self, routes):
        return sum(self.route_cost(r) for r in routes) + self.kpen * max(0, len(routes) - self.K)

    def metrics(self, routes):
        """(km, minutes, congestion-km) of a plan following this problem's least-cost legs"""
        if self.D is None: return (0., 0., 0.)
        d = t = c = 0.
        for r in routes:
            seq = [0] + r + [0]
            for a, b in zip(seq[:-1], seq[1:]):
                d += self.D[a, b]; t += self.T[a, b]; c += self.C[a, b]
        return d, t, c

    def feasible(self, routes):
        seen = sorted(c for r in routes for c in r)
        return seen == list(range(1, self.n + 1)) and all(sum(self.dem[c] for c in r) <= self.Q for r in routes)


def _edge_costs(net, state, w: Weights):
    t = net.t0_min / np.clip(state.ratio, 0.03, 2.0)               # minutes under current speeds
    c = net.d_km * np.maximum(0.0, 1.0 / np.clip(state.ratio, 0.03, 2.0) - 1.0)   # delay-weighted km
    return t, c, w.time * t + w.dist * net.d_km + w.cong * c


def build_problem(net, state, stop_nodes, demands, Q, K=None, weights=Weights(), tw=None, service=None):
    """Dijkstra from every stop on the directed, traffic-weighted road graph."""
    t, c, wgt = _edge_costs(net, state, weights)
    N = net.N
    W = csr_matrix((wgt, (net.u, net.v)), shape=(N, N))
    dist, pred = dijkstra(W, directed=True, indices=stop_nodes, return_predecessors=True)
    m = len(stop_nodes)
    G = dist[:, stop_nodes]
    if not np.all(np.isfinite(G)):
        raise ValueError("some stops are unreachable from others (disconnected road network)")
    eid = net.edge_index
    D = np.zeros((m, m)); T = np.zeros((m, m)); C = np.zeros((m, m))
    for si, s in enumerate(stop_nodes):
        memo = {s: (0., 0., 0.)}
        for j, tgt in enumerate(stop_nodes):
            chain = []; v = tgt
            while v not in memo:
                chain.append(v); v = pred[si, v]
            d0, t0_, c0 = memo[v]
            for v in reversed(chain):
                e = eid[(pred[si, v], v)]
                d0 += net.d_km[e]; t0_ += t[e]; c0 += c[e]; memo[v] = (d0, t0_, c0)
            D[si, j], T[si, j], C[si, j] = memo[tgt]
    p = Problem(G, demands, Q, K, D, T, C, ctx=(net, list(stop_nodes), pred, weights), tw=tw, service=service)
    return p


def leg_edges(prob, a, b):
    """edge ids of the least-cost leg between stops a and b (for drawing and re-evaluation)"""
    net, stops, pred, _ = prob.ctx
    eid = net.edge_index; out = []; v = stops[b]
    while v != stops[a]:
        u = pred[a, v]; out.append(eid[(u, v)]); v = u
    return out[::-1]


def evaluate_plan_under(prob_plan, routes, net, state, weights=Weights()):
    """Drive the legs chosen by `prob_plan` (e.g. free-flow paths) through a different traffic `state`.
    Returns (cost, km, minutes, congestion-km).  Used to measure what ignoring live traffic costs."""
    t, c, wgt = _edge_costs(net, state, weights)
    cost = d = tt = cc = 0.
    for r in routes:
        seq = [0] + r + [0]
        for a, b in zip(seq[:-1], seq[1:]):
            es = leg_edges(prob_plan, a, b)
            cost += wgt[es].sum(); d += net.d_km[es].sum(); tt += t[es].sum(); cc += c[es].sum()
    return cost + prob_plan.kpen * max(0, len(routes) - prob_plan.K), d, tt, cc
