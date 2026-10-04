"""Google OR-Tools routing solver as an external, state-of-the-practice baseline (pip install ortools)."""
import time


def ortools_solve(prob, time_limit_s=10, scale=100, extra_vehicles=0):
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    n = prob.n
    Gi = [[int(round(x * scale)) for x in row] for row in prob.G]
    K = prob.K + extra_vehicles
    t0 = time.perf_counter()
    manager = pywrapcp.RoutingIndexManager(n + 1, K, 0)
    routing = pywrapcp.RoutingModel(manager)
    cb = routing.RegisterTransitCallback(lambda i, j: Gi[manager.IndexToNode(i)][manager.IndexToNode(j)])
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    dem = routing.RegisterUnaryTransitCallback(lambda i: prob.dem[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(dem, 0, [prob.Q] * K, True, "Capacity")

    if getattr(prob, "tw", None) is not None:
        T = prob.T if getattr(prob, "T", None) is not None else prob.Gn
        serv = getattr(prob, "service", None) or [0.0] * (n + 1)
        time_cb = routing.RegisterTransitCallback(
            lambda i, j: int(round((float(T[manager.IndexToNode(i)][manager.IndexToNode(j)]) + float(serv[manager.IndexToNode(i)])) * scale))
        )
        horizon = int(max(tw[1] for tw in prob.tw) * scale * 2)
        routing.AddDimension(time_cb, int(300 * scale), horizon, False, "Time")
        time_dim = routing.GetDimensionOrDie("Time")
        for i, (e, l) in enumerate(prob.tw):
            idx = manager.NodeToIndex(i)
            time_dim.CumulVar(idx).SetRange(int(round(e * scale)), int(round(l * scale)))

    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.seconds = int(max(1, time_limit_s))
    sol = routing.SolveWithParameters(p)
    if sol is None:
        if extra_vehicles < 5: return ortools_solve(prob, time_limit_s, scale, extra_vehicles + 1)
        return None
    routes = []
    for v in range(K):
        idx = routing.Start(v); r = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node != 0: r.append(node)
            idx = sol.Value(routing.NextVar(idx))
        if r: routes.append(r)
    return prob.total(routes), routes, time.perf_counter() - t0
