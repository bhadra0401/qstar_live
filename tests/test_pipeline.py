"""Offline end-to-end tests (no internet, no API key).  Run:  python tests/test_pipeline.py   (or pytest -q)"""
import os, sys, json, tempfile, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qstar import synthetic_city, build_problem, Weights, evaluate_plan_under, algos
from qstar.traffic import SimulatedProvider, FreeFlowProvider, TomTomProvider, ReplayProvider
from qstar.cvrplib import load_vrp


def _setup(n=20, seed=3):
    net = synthetic_city(); nodes, dem = net.sample_customers(n, seed=seed)
    return net, nodes, dem


def test_network_is_directed_and_connected():
    net = synthetic_city()
    assert net.N > 200 and net.E > 600
    one_way = sum((int(v), int(u)) not in net.edge_index for u, v in zip(net.u, net.v))
    assert one_way > 0                      # real cities have one-way streets


def test_problem_matrix_and_plan_feasible():
    net, nodes, dem = _setup()
    st = SimulatedProvider(hour=9).get_state(net)
    p = build_problem(net, st, nodes, dem, Q=60)
    assert p.G[0][0] == 0 and not p.sym
    cost, hist, routes, t, keys = algos.qstar(p, pop=12, iters=15, seed=1)
    assert p.feasible(routes) and abs(p.total(routes) - cost) < 1e-6
    d, tt, c = p.metrics(routes); assert d > 0 and tt > 0


def test_exact_gap_directed():
    net, nodes, dem = _setup(n=9, seed=5)
    p = build_problem(net, SimulatedProvider(hour=18).get_state(net), nodes, dem, Q=45)
    opt = algos.exact(p)
    best = min(algos.qstar(p, pop=12, iters=30, seed=s)[0] for s in range(3))
    assert best >= opt - 1e-6 and best <= opt * 1.03, (best, opt)


def test_traffic_awareness_helps():
    """a plan made on free-flow data, driven through rush-hour traffic, must not beat the traffic-aware plan"""
    net, nodes, dem = _setup(n=30)
    live = SimulatedProvider(hour=18, intensity=1.2).get_state(net)
    p_live = build_problem(net, live, nodes, dem, Q=60)
    p_blind = build_problem(net, FreeFlowProvider().get_state(net), nodes, dem, Q=60)
    r_aware = algos.qstar(p_live, pop=12, iters=25, seed=0)[2]
    r_blind = algos.qstar(p_blind, pop=12, iters=25, seed=0)[2]
    c_blind = evaluate_plan_under(p_blind, r_blind, net, live)[0]
    assert p_live.total(r_aware) <= c_blind + 1e-6


def test_tomtom_provider_with_mock_api():
    net = synthetic_city(); calls = []

    class R:
        status_code = 200
        def __init__(s, d): s.d = d
        def json(s): return {"flowSegmentData": s.d}

    def fake_get(url, params):
        calls.append((url, params)); lat = float(params["point"].split(",")[0])
        return R({"currentSpeed": 20 if lat > net.lat.mean() else 38, "freeFlowSpeed": 40, "roadClosure": False})

    prov = TomTomProvider(api_key="TEST", max_samples=25, http_get=fake_get)
    st = prov.get_state(net)
    assert "flowSegmentData/absolute" in calls[0][0] and calls[0][1]["key"] == "TEST"
    assert len(calls) == 25 and st.n_observed == 25 and st.ratio.min() >= 0.03 and st.ratio.max() <= 1.2
    assert st.ratio[net.mid_lat > net.lat.mean() + 0.01].mean() < st.ratio[net.mid_lat < net.lat.mean() - 0.01].mean()
    prov.get_state(net); assert len(calls) == 25            # second call served from the TTL cache


def test_replay_provider():
    net = synthetic_city(); st = SimulatedProvider(hour=8).get_state(net)
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump([{"t": 1.0, "ratio": st.ratio.tolist()}], f); f.close()
    assert np.allclose(ReplayProvider(f.name).get_state(net).ratio, st.ratio)


VRP_TOY = "\n".join(["NAME : X-n5-k2", "COMMENT : toy", "TYPE : CVRP", "DIMENSION : 5", "EDGE_WEIGHT_TYPE : EUC_2D",
                     "CAPACITY : 10", "NODE_COORD_SECTION", "1 0 0", "2 0 10", "3 10 0", "4 0 -10", "5 -10 0",
                     "DEMAND_SECTION", "1 0", "2 5", "3 5", "4 5", "5 5", "DEPOT_SECTION", "1", "-1", "EOF"])


def test_cvrplib_parser():
    f = tempfile.NamedTemporaryFile("w", suffix=".vrp", delete=False); f.write(VRP_TOY); f.close()
    p = load_vrp(f.name); assert p.n == 4 and p.Q == 10 and p.K == 2
    assert algos.exact(p) == 68.0 and algos.qstar(p, pop=10, iters=10)[0] == 68.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("PASS", name)
