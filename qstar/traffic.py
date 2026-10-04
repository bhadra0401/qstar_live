"""Traffic providers.  Every provider returns a TrafficState with `ratio[e] = current speed / free-flow speed`
for every directed edge (1.0 = free flow, 0.3 = crawling, ~0.03 = closed).

  FreeFlowProvider   - no congestion (what a traffic-blind planner assumes)
  SimulatedProvider  - rush-hour model (BPR volume-delay law) with spatial hotspots; no internet needed
  TomTomProvider     - LIVE speeds from the TomTom Traffic Flow Segment Data API (API key required)
  ReplayProvider     - replays snapshots recorded earlier by scripts/collect_traffic.py (real data, offline)
"""
import json, os, time, math
from dataclasses import dataclass, field
import numpy as np
from scipy.spatial import cKDTree

TOMTOM_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/{zoom}/json"


@dataclass
class TrafficState:
    ratio: np.ndarray
    source: str
    timestamp: float = field(default_factory=time.time)
    n_observed: int = 0                  # edges that carry a direct measurement
    meta: dict = field(default_factory=dict)

    def summary(self):
        r = self.ratio
        return dict(source=self.source, mean_speed_ratio=float(r.mean()), pct_edges_slow=float((r < 0.6).mean() * 100),
                    observed_edges=self.n_observed, total_edges=len(r))


class FreeFlowProvider:
    def get_state(self, net):
        return TrafficState(np.ones(net.E), "free-flow (no traffic data)")


class SimulatedProvider:
    """volume/capacity = base(hour) * spatial(hotspots) ;  speed ratio = 1 / (1 + 0.15 (v/c)^4)   (BPR law)"""
    def __init__(self, hour=9.0, intensity=1.0, seed=0, n_hotspots=3):
        self.hour, self.intensity, self.seed, self.nh = hour, intensity, seed, n_hotspots

    @staticmethod
    def hour_profile(h):
        return 0.30 + 0.75 * math.exp(-((h - 9.0) ** 2) / 2.0) + 0.85 * math.exp(-((h - 18.0) ** 2) / 2.5)

    def get_state(self, net):
        rng = np.random.default_rng(self.seed)
        k = 111.32
        cx, cy = net.lat.mean(), net.lon.mean()
        span = max(np.ptp(net.lat) * k, np.ptp(net.lon) * k * math.cos(math.radians(cx)))
        hs = [(cx + rng.normal(0, 0.18) * span / k, cy + rng.normal(0, 0.18) * span / k) for _ in range(self.nh)]
        vc = np.zeros(net.E)
        for (hx, hy) in hs:
            d2 = ((net.mid_lat - hx) * k) ** 2 + ((net.mid_lon - hy) * k * math.cos(math.radians(cx))) ** 2
            vc += np.exp(-d2 / (2 * (0.18 * span) ** 2))
        arterial = np.where(net.rank <= 3, 1.25, 0.85)
        vc = self.hour_profile(self.hour) * self.intensity * (0.35 + 1.1 * vc) * arterial + rng.normal(0, 0.05, net.E)
        ratio = 1.0 / (1.0 + 0.15 * np.clip(vc, 0.05, 2.5) ** 4)
        return TrafficState(ratio, f"simulated rush-hour model, {self.hour:05.2f}h", n_observed=0,
                            meta=dict(hotspots=hs))


class TomTomProvider:
    """Live traffic.  Queries the Flow Segment Data endpoint at spatially spread sample points (one request each),
    then interpolates to every other edge (inverse-distance weighting that fades back to free flow with distance).
    The result is therefore *measured on the sampled roads and estimated elsewhere* - the dashboard reports the
    share of edges that are directly measured."""

    def __init__(self, api_key=None, max_samples=60, cache_dir="data/cache", http_get=None, zoom=10, ttl_s=120, fade_km=2.0):
        self.key = api_key or os.environ.get("TOMTOM_API_KEY")
        self.max_samples, self.zoom, self.ttl, self.fade_km = max_samples, zoom, ttl_s, fade_km
        self.cache_dir = cache_dir
        if http_get is None:
            import requests
            http_get = lambda url, params: requests.get(url, params=params, timeout=10)
        self.http_get = http_get
        self.requests_used = 0
        self._last = None

    def _pick_samples(self, net):
        """farthest-point sampling over major roads first, so a small request budget still covers the whole area"""
        cand = np.where(net.rank <= 4)[0]
        if len(cand) < self.max_samples: cand = np.arange(net.E)
        pts = np.c_[net.mid_lat[cand], net.mid_lon[cand] * math.cos(math.radians(net.lat.mean()))]
        chosen = [int(np.argmax(net.d_km[cand]))]
        dmin = np.linalg.norm(pts - pts[chosen[0]], axis=1)
        while len(chosen) < min(self.max_samples, len(cand)):
            j = int(np.argmax(dmin)); chosen.append(j)
            dmin = np.minimum(dmin, np.linalg.norm(pts - pts[j], axis=1))
        return cand[chosen]

    def _query(self, lat, lon):
        r = self.http_get(TOMTOM_URL.format(zoom=self.zoom), {"key": self.key, "point": f"{lat:.6f},{lon:.6f}", "unit": "KMPH"})
        self.requests_used += 1
        if r.status_code != 200: raise RuntimeError(f"TomTom HTTP {r.status_code}: {getattr(r, 'text', '')[:200]}")
        d = r.json()["flowSegmentData"]
        if d.get("roadClosure"): return 0.03, d
        cur, free = float(d["currentSpeed"]), float(d["freeFlowSpeed"])
        return float(np.clip(cur / max(free, 1.0), 0.03, 1.2)), d

    def get_state(self, net):
        if self._last is not None and time.time() - self._last.timestamp < self.ttl:
            return self._last                                   # protect the request quota
        if not self.key: raise RuntimeError("No TomTom API key: set TOMTOM_API_KEY or pass api_key")
        samp = self._pick_samples(net); vals = []; ok = []
        for e in samp:
            try:
                r, _ = self._query(net.mid_lat[e], net.mid_lon[e]); vals.append(r); ok.append(e)
            except Exception as ex:                             # skip a failed point, keep going
                last_err = ex
        if len(ok) < 3: raise RuntimeError(f"too few successful TomTom responses ({len(ok)}); last error: {last_err}")
        ok = np.array(ok); vals = np.array(vals)
        ratio = self._interpolate(net, ok, vals)
        st = TrafficState(ratio, "TomTom live traffic", n_observed=len(ok),
                          meta=dict(samples=len(ok), requested=len(samp), requests_total=self.requests_used))
        self._last = st
        return st

    def _interpolate(self, net, ok, vals):
        c = math.cos(math.radians(net.lat.mean())); k = 111.32
        P = np.c_[net.mid_lat[ok] * k, net.mid_lon[ok] * k * c]; Q = np.c_[net.mid_lat * k, net.mid_lon * k * c]
        kk = min(4, len(ok)); d, i = cKDTree(P).query(Q, k=kk)
        d = d.reshape(len(Q), kk); i = i.reshape(len(Q), kk)
        w = 1.0 / (d + 0.2) ** 2
        idw = (w * vals[i]).sum(1) / w.sum(1)
        fade = np.exp(-d[:, 0] / self.fade_km)
        ratio = 1.0 + (idw - 1.0) * fade
        ratio[ok] = vals                                        # measured edges keep their measurement
        return np.clip(ratio, 0.03, 1.2)


class ReplayProvider:
    """Replay snapshots saved by scripts/collect_traffic.py:  [{"t": epoch, "ratio": [...per edge...]}, ...]"""
    def __init__(self, path):
        self.snaps = json.load(open(path)); self.i = 0

    def set_index(self, i): self.i = int(np.clip(i, 0, len(self.snaps) - 1))

    def get_state(self, net):
        s = self.snaps[self.i]
        r = np.array(s["ratio"], float)
        if len(r) != net.E: raise ValueError("snapshot was recorded for a different network")
        return TrafficState(r, f"recorded real traffic, snapshot {self.i + 1}/{len(self.snaps)}", timestamp=s["t"], n_observed=s.get("n_observed", 0))
