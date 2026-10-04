"""Q-STAR core algorithms (decoder, local search, GA / PSO / QPSO / Q-STAR, Clarke-Wright, exact DP).
Works on any `Problem` (see problem.py) with a (possibly asymmetric) cost matrix prob.G."""
import numpy as np, time, math

KPEN = 300.0   # penalty per vehicle above the fleet limit (in cost units)

# ------------------------------------------------------------------ decoder (Prins split)
def split(prob, perm):
    G, dem, Q, n = prob.G, prob.dem, prob.Q, prob.n
    tw = getattr(prob, 'tw', None)
    service = getattr(prob, 'service', None) or [0.0] * (n + 1)
    tw_pen = getattr(prob, 'tw_pen', 5.0)
    T = prob.T if getattr(prob, 'T', None) is not None else prob.Gn
    V = [1e18] * (n + 1); V[0] = 0.0; P = [0] * (n + 1)
    G0 = G[0]
    for i in range(n):
        load = 0; cost = 0.0; prev = 0
        Vi = V[i]
        curr_t = 0.0
        for j in range(i, n):
            c = perm[j]; load += dem[c]
            if load > Q: break
            cost += G0[c] if j == i else G[prev][c]
            if tw is not None:
                trav = float(T[0, c] if j == i else T[prev, c])
                arr = curr_t + trav
                e, l = tw[c]
                start = max(arr, e)
                curr_t = start + float(service[c])
                late = max(0.0, arr - l)
                cost += late * tw_pen
            prev = c
            ret_cost = G0[c]
            if tw is not None:
                ret_arr = curr_t + float(T[c, 0])
                if ret_arr > tw[0][1]:
                    ret_cost += (ret_arr - tw[0][1]) * tw_pen
            tot = Vi + cost + ret_cost
            if tot < V[j + 1]: V[j + 1] = tot; P[j + 1] = i
    routes = []; j = n
    while j > 0:
        i = P[j]; routes.append(perm[i:j]); j = i
    routes.reverse()
    return routes


def decode(prob, keys):
    perm = (np.argsort(keys) + 1).tolist()
    routes = split(prob, perm)
    return routes, prob.total(routes)


def canon(X):
    """rank-canonical random keys: identical tours <-> identical vectors"""
    return (np.argsort(np.argsort(X, axis=1), axis=1) + 0.5) / X.shape[1]


def encode(routes, n):
    keys = np.zeros(n)
    pos = 0
    for r in routes:
        for c in r:
            keys[c - 1] = (pos + 0.5) / n; pos += 1
    return keys


# ------------------------------------------------------------------ local search
def _seqcost(G, seq):
    return sum(G[a][b] for a, b in zip(seq[:-1], seq[1:]))


def local_search(prob, routes, passes=4):
    G, dem, Q = prob.G, prob.dem, prob.Q
    routes = [list(r) for r in routes]
    loads = [sum(dem[c] for c in r) for r in routes]
    for _ in range(passes):
        improved = False
        # intra-route 2-opt (exact delta for symmetric costs, exact recompute for directed roads)
        for r in routes:
            seq = [0] + r + [0]; m = len(seq)
            for i in range(m - 3):
                for j in range(i + 2, m - 1):
                    if prob.sym:
                        a, b, c, d = seq[i], seq[i + 1], seq[j], seq[j + 1]
                        better = G[a][c] + G[b][d] - G[a][b] - G[c][d] < -1e-9
                    else:
                        cand = seq[:i + 1] + seq[i + 1:j + 1][::-1] + seq[j + 1:]
                        better = _seqcost(G, cand) < _seqcost(G, seq) - 1e-9
                    if better:
                        seq[i + 1:j + 1] = seq[i + 1:j + 1][::-1]; improved = True
            r[:] = seq[1:-1]
        # inter-route relocate
        for a in range(len(routes)):
            ra = routes[a]; x = 0
            while x < len(ra):
                c = ra[x]
                prev = ra[x - 1] if x > 0 else 0; nxt = ra[x + 1] if x + 1 < len(ra) else 0
                rem = G[prev][c] + G[c][nxt] - G[prev][nxt]
                best = (0, None, None)
                for b in range(len(routes)):
                    if b == a or loads[b] + dem[c] > Q: continue
                    rb = routes[b]; sb = [0] + rb + [0]
                    for p in range(len(sb) - 1):
                        add = G[sb[p]][c] + G[c][sb[p + 1]] - G[sb[p]][sb[p + 1]]
                        gain = rem - add
                        if gain > best[0] + 1e-9: best = (gain, b, p)
                if best[1] is not None:
                    _, b, p = best
                    routes[b].insert(p, c); loads[b] += dem[c]; loads[a] -= dem[c]
                    ra.pop(x); improved = True
                else:
                    x += 1
        # inter-route swap
        for a in range(len(routes)):
            for b in range(a + 1, len(routes)):
                ra, rb = routes[a], routes[b]
                for x in range(len(ra)):
                    for y in range(len(rb)):
                        ca, cb = ra[x], rb[y]
                        if loads[a] - dem[ca] + dem[cb] > Q or loads[b] - dem[cb] + dem[ca] > Q: continue
                        pa = ra[x - 1] if x > 0 else 0; na = ra[x + 1] if x + 1 < len(ra) else 0
                        pb = rb[y - 1] if y > 0 else 0; nb = rb[y + 1] if y + 1 < len(rb) else 0
                        old = G[pa][ca] + G[ca][na] + G[pb][cb] + G[cb][nb]
                        new = G[pa][cb] + G[cb][na] + G[pb][ca] + G[ca][nb]
                        if new < old - 1e-9:
                            ra[x], rb[y] = cb, ca
                            loads[a] += dem[cb] - dem[ca]; loads[b] += dem[ca] - dem[cb]; improved = True
        keep = [i for i, r in enumerate(routes) if r]
        routes = [routes[i] for i in keep]; loads = [loads[i] for i in keep]
        if not improved: break
    return routes


# ------------------------------------------------------------------ algorithms
def _ls_hook(prob, keys, cost, routes):
    r2 = local_search(prob, routes)
    c2 = prob.total(r2)
    if c2 < cost - 1e-9:
        return encode(r2, prob.n), c2, r2
    return keys, cost, routes


def ga(prob, pop=30, iters=100, seed=0, ls=False, ls_every=5, max_time=None):
    rng = np.random.default_rng(seed); n = prob.n; t0 = time.perf_counter()
    P = [rng.permutation(n) + 1 for _ in range(pop)]
    fit = []
    for p in P:
        rt = split(prob, p.tolist()); fit.append(prob.total(rt))
    best_i = int(np.argmin(fit)); best = (fit[best_i], P[best_i].copy(), None); hist = [best[0]]
    for it in range(iters):
        if max_time is not None and time.perf_counter() - t0 > max_time: break
        newP, newF = [], []
        order = np.argsort(fit); newP.append(P[order[0]].copy()); newF.append(fit[order[0]])
        while len(newP) < pop:
            def tour():
                i = rng.integers(pop, size=3); return P[i[np.argmin([fit[k] for k in i])]]
            p1, p2 = tour(), tour()
            if rng.random() < 0.9:                       # order crossover
                a, b = sorted(rng.integers(n, size=2)); ch = [0] * n; seg = p1[a:b + 1]
                ch[a:b + 1] = seg; s = set(seg.tolist()); rest = [x for x in p2 if x not in s]
                k = 0
                for i in range(n):
                    if not (a <= i <= b): ch[i] = rest[k]; k += 1
                ch = np.array(ch)
            else: ch = p1.copy()
            if rng.random() < 0.3:                       # inversion
                a, b = sorted(rng.integers(n, size=2)); ch[a:b + 1] = ch[a:b + 1][::-1]
            if rng.random() < 0.3:                       # swap
                a, b = rng.integers(n, size=2); ch[a], ch[b] = ch[b], ch[a]
            rt = split(prob, ch.tolist()); newP.append(ch); newF.append(prob.total(rt))
        P, fit = newP, newF
        bi = int(np.argmin(fit))
        if fit[bi] < best[0]: best = (fit[bi], P[bi].copy(), None)
        if ls and (it + 1) % ls_every == 0:
            rt = split(prob, best[1].tolist()); k, c, rt2 = _ls_hook(prob, None, best[0], rt)
            if c < best[0] - 1e-9:
                perm = np.array([x for r in rt2 for x in r]); best = (c, perm, None)
                P[0] = perm.copy(); fit[0] = c
        hist.append(best[0])
    rt = split(prob, best[1].tolist())
    if ls: rt = local_search(prob, rt)
    return prob.total(rt), hist, rt, time.perf_counter() - t0


def swarm(prob, kind="qpso", pop=30, iters=100, seed=0, ls=False, ls_every=5, init=None,
          chaotic=False, wmbest=False, adaptive=False, tunnel=False, topk=1, seed_cw=False, efrac=1.0, amax=1.0, amin=0.5, cscale=0.12, ls_all=False, max_time=None, callback=None):
    """kind: 'pso' or 'qpso'.  flags select the Q-STAR components."""
    rng = np.random.default_rng(seed); n = prob.n; t0 = time.perf_counter()
    if chaotic:
        z = rng.uniform(0.05, 0.95, (pop, n))
        for _ in range(20): z = 4 * z * (1 - z)
        X = np.clip(z, 0, 1)
    else:
        X = rng.random((pop, n))
    if seed_cw:                                           # heuristic-guided quantum initialisation
        cwr = clarke_wright(prob)[1]
        X[0] = encode(cwr, n)
        for q in range(1, max(2, pop // 8)):
            X[q] = np.clip(X[0] + rng.normal(0, 0.03 * q, n), 0, 1)
    if init is not None:
        X[0] = init
        if pop > 2: X[1] = np.clip(init + rng.normal(0, 0.02, n), 0, 1)
    X = canon(X); V = np.zeros((pop, n))
    fit = np.empty(pop); rts = [None] * pop
    for i in range(pop): rts[i], fit[i] = decode(prob, X[i])
    PB, PF = X.copy(), fit.copy(); stag = np.zeros(pop)
    gi = int(np.argmin(PF)); GB, GF, GR = PB[gi].copy(), PF[gi], rts[gi]
    hist = [GF]; D0 = None
    for it in range(iters):
        if max_time is not None and time.perf_counter() - t0 > max_time: break
        frac = it / max(1, iters - 1)
        if max_time is not None: frac = min(1.0, max(frac, (time.perf_counter() - t0) / max_time))
        if kind == "pso":
            w = 0.9 - 0.5 * frac
            r1, r2 = rng.random((pop, n)), rng.random((pop, n))
            V = w * V + 2.0 * r1 * (PB - X) + 2.0 * r2 * (GB - X)
            V = np.clip(V, -0.25, 0.25); X = canon(np.clip(X + V, 0, 1))
        else:
            if wmbest:                                       # rank-weighted mean best
                m = max(3, int(pop * efrac)); idx = np.argsort(PF)[:m]
                wt = np.log(m + 1) - np.log(np.arange(1, m + 1)); wt /= wt.sum()
                mbest = (wt[:, None] * PB[idx]).sum(0)
            else:
                mbest = PB.mean(0)
            alpha = amax - (amax - amin) * frac                  # linear schedule
            if adaptive:                                      # diversity feedback law
                div = np.mean(np.linalg.norm(X - X.mean(0), axis=1))
                if D0 is None: D0 = div + 1e-12
                alpha = (amax - (amax - amin) * frac ** 0.7) * (1 + 0.8 * max(0.0, 1 - div / D0))
                alpha = min(alpha, 1.7)                       # keep below e^gamma = 1.781
            phi = rng.random((pop, n)); u = rng.random((pop, n)) + 1e-12
            p = phi * PB + (1 - phi) * GB
            sgn = np.where(rng.random((pop, n)) < 0.5, -1.0, 1.0)
            X = canon(np.clip(p + sgn * alpha * np.abs(mbest - X) * np.log(1.0 / u), 0, 1))
            if tunnel:                                        # quantum tunnelling via Cauchy kicks
                ptun = 0.5 * (1 - frac) + 0.1
                for i in np.where(stag >= 6)[0]:
                    if rng.random() < ptun:
                        mask = rng.random(n) < 0.15
                        X[i] = canon(np.clip(np.where(mask, PB[i] + cscale * rng.standard_cauchy(n), PB[i]), 0, 1)[None])[0]
                        stag[i] = 0
        for i in range(pop):
            rts[i], fit[i] = decode(prob, X[i])
            if ls_all:
                r2 = local_search(prob, rts[i], passes=3); c2 = prob.total(r2)
                if c2 < fit[i] - 1e-9: rts[i], fit[i], X[i] = r2, c2, encode(r2, n)
            if fit[i] < PF[i] - 1e-12: PB[i], PF[i], stag[i] = X[i].copy(), fit[i], 0
            else: stag[i] += 1
        gi = int(np.argmin(PF))
        if PF[gi] < GF - 1e-12: GB, GF, GR = PB[gi].copy(), PF[gi], decode(prob, PB[gi])[0]
        if ls and (it + 1) % ls_every == 0:                   # memetic Lamarckian refinement
            for q in np.argsort(PF)[:topk]:
                rq = decode(prob, PB[q])[0]
                k2, c2, r2 = _ls_hook(prob, PB[q], PF[q], rq)
                if c2 < PF[q] - 1e-9:
                    PB[q] = k2.copy(); PF[q] = c2
                    if c2 < GF - 1e-9: GB, GF, GR = k2.copy(), c2, r2
        hist.append(GF)
        if callback: callback(it, GF)
    if ls:
        r2 = local_search(prob, GR); c2 = prob.total(r2)
        if c2 < GF: GF, GR = c2, r2
        hist[-1] = GF
    return GF, hist, GR, time.perf_counter() - t0, GB


def qstar(prob, pop=20, iters=60, seed=0, max_time=None, init=None, callback=None):
    """Full Q-STAR: quantum-behaved swarm + weighted centre + diversity-feedback alpha + tunnelling
    + local refinement of every particle (memetic). `init` = keys of a previous plan (warm start)."""
    return swarm(prob, "qpso", pop=pop, iters=iters, seed=seed, ls_all=True, chaotic=True, wmbest=True,
                 adaptive=True, tunnel=True, init=init, max_time=max_time, callback=callback)


# ------------------------------------------------------------------ classical baselines
def clarke_wright(prob):
    n, G, dem, Q = prob.n, prob.G, prob.dem, prob.Q
    routes = {i: [i] for i in range(1, n + 1)}; load = {i: dem[i] for i in routes}; where = {i: i for i in routes}
    sav = sorted(((G[0][i] + G[0][j] - G[i][j], i, j) for i in range(1, n + 1) for j in range(i + 1, n + 1)), reverse=True)
    for s, i, j in sav:
        if s <= 0: break
        ri, rj = where[i], where[j]
        if ri == rj or load[ri] + load[rj] > Q: continue
        A, B = routes[ri], routes[rj]
        if A[-1] == i and B[0] == j: new = A + B
        elif A[0] == i and B[-1] == j: new = B + A
        elif A[0] == i and B[0] == j: new = A[::-1] + B
        elif A[-1] == i and B[-1] == j: new = A + B[::-1]
        else: continue
        routes[ri] = new; load[ri] += load[rj]; del routes[rj], load[rj]
        for c in new: where[c] = ri
    rt = list(routes.values())
    return prob.total(rt), rt


def nearest_neighbour(prob):
    n, G, dem, Q = prob.n, prob.G, prob.dem, prob.Q
    un = set(range(1, n + 1)); rt = []
    while un:
        cur, load, r = 0, 0, []
        while True:
            c = [j for j in un if load + dem[j] <= Q]
            if not c: break
            j = min(c, key=lambda x: G[cur][x]); r.append(j); un.remove(j); load += dem[j]; cur = j
        rt.append(r)
    return prob.total(rt), rt


# ------------------------------------------------------------------ exact (bitmask DP, n <= ~12)
def exact(prob):
    n, G, dem, Q = prob.n, prob.G, prob.dem, prob.Q
    full = 1 << n; INF = 1e18
    tsp = [INF] * full; tsp[0] = 0
    dp = [[INF] * n for _ in range(full)]
    for i in range(n): dp[1 << i][i] = G[0][i + 1]
    for m in range(1, full):
        for last in range(n):
            v = dp[m][last]
            if v >= INF: continue
            for nx in range(n):
                if m >> nx & 1: continue
                m2 = m | 1 << nx; nv = v + G[last + 1][nx + 1]
                if nv < dp[m2][nx]: dp[m2][nx] = nv
        tsp[m] = min(dp[m][l] + G[l + 1][0] for l in range(n) if m >> l & 1)
    load = [0] * full
    for m in range(1, full):
        low = (m & -m).bit_length() - 1; load[m] = load[m & (m - 1)] + dem[low + 1]
    best = [INF] * full; best[0] = 0
    for m in range(1, full):
        low = m & -m; sub = m
        while sub:
            if sub & low and load[sub] <= Q:
                v = best[m ^ sub] + tsp[sub]
                if v < best[m]: best[m] = v
            sub = (sub - 1) & m
    return best[full - 1]
