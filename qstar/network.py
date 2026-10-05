"""Road network as a directed weighted graph, loaded from OpenStreetMap (via OSMnx) or any
networkx MultiDiGraph that follows the OSMnx conventions (nodes: x=lon, y=lat; edges: length in metres)."""
import os, re, numpy as np
import networkx as nx
from scipy.spatial import cKDTree

HIGHWAY_SPEED = {"motorway": 80, "motorway_link": 50, "trunk": 60, "trunk_link": 40, "primary": 50, "primary_link": 35,
                 "secondary": 40, "secondary_link": 30, "tertiary": 35, "tertiary_link": 30, "unclassified": 30,
                 "residential": 25, "living_street": 15, "service": 20}
HIGHWAY_RANK = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4}   # others -> 5


def _first(x):
    return x[0] if isinstance(x, (list, tuple)) and x else x


def _speed_kmh(data):
    """free-flow speed from maxspeed tag, else a default per road class"""
    ms = _first(data.get("maxspeed"))
    if ms is not None:
        m = re.search(r"(\d+(\.\d+)?)", str(ms))
        if m:
            v = float(m.group(1))
            return v * 1.609 if "mph" in str(ms) else v
    if data.get("speed_kph"): return float(_first(data["speed_kph"]))
    return HIGHWAY_SPEED.get(str(_first(data.get("highway", "residential"))), 25)


class RoadNet:
    def __init__(self, G, label="", synthetic=False):
        # keep the largest strongly connected component so every stop can reach every other stop
        comp = max(nx.strongly_connected_components(G), key=len)
        G = G.subgraph(comp).copy()
        self.label, self.synthetic = label, synthetic
        self.node_ids = list(G.nodes)
        idx = {n: i for i, n in enumerate(self.node_ids)}
        self.N = len(self.node_ids)
        self.lat = np.array([G.nodes[n]["y"] for n in self.node_ids])
        self.lon = np.array([G.nodes[n]["x"] for n in self.node_ids])
        best = {}                                    # one edge per (u,v): the quickest parallel edge
        for u, v, data in G.edges(data=True):
            L = float(_first(data.get("length", 0.0))) or 1.0
            sp = _speed_kmh(data); t = L / 1000.0 / sp * 60.0
            key = (idx[u], idx[v])
            if key not in best or t < best[key][2]:
                geom = data.get("geometry")
                pts = [(y, x) for x, y in geom.coords] if geom is not None else None
                best[key] = (L / 1000.0, sp, t, str(_first(data.get("highway", "residential"))), pts)
        keys = list(best)
        self.u = np.array([k[0] for k in keys]); self.v = np.array([k[1] for k in keys]); self.E = len(keys)
        self.d_km = np.array([best[k][0] for k in keys]); self.free_kmh = np.array([best[k][1] for k in keys])
        self.t0_min = np.array([best[k][2] for k in keys]); self.hw = [best[k][3] for k in keys]
        self.geom = [best[k][4] for k in keys]
        self.rank = np.array([HIGHWAY_RANK.get(h.replace("_link", ""), 5) for h in self.hw])
        self.edge_index = {k: i for i, k in enumerate(keys)}
        self.mid_lat = (self.lat[self.u] + self.lat[self.v]) / 2
        self.mid_lon = (self.lon[self.u] + self.lon[self.v]) / 2
        self._tree = cKDTree(np.c_[self.lat, self.lon * np.cos(np.radians(self.lat.mean()))])

    # ------------------------------------------------------------------ loaders
    @classmethod
    def from_osm(cls, place=None, center=None, radius_m=2500, cache_dir="data/cache", label=None, **kwargs):
        """Download the drivable network from OpenStreetMap with OSMnx (internet required)."""
        import osmnx as ox
        os.makedirs(cache_dir, exist_ok=True)
        tag = re.sub(r"\W+", "_", place if place else f"{center[0]:.4f}_{center[1]:.4f}_{int(radius_m)}")
        path = os.path.join(cache_dir, f"{tag}.graphml")
        save = getattr(ox, "save_graphml", None) or ox.io.save_graphml
        load = getattr(ox, "load_graphml", None) or ox.io.load_graphml
        
        if os.path.exists(path):
            G = load(path)
        else:
            # Fix for Streamlit Cloud "Connection refused" / Overpass API blocks
            endpoints = [
                "https://lz4.overpass-api.de/api",
                "https://overpass.kumi.systems/api",
                "https://overpass-api.de/api"
            ]
            G = None
            last_err = None
            for ep in endpoints:
                if hasattr(ox, "settings"):
                    ox.settings.overpass_endpoint = ep
                    ox.settings.timeout = 180
                try:
                    if place: G = ox.graph_from_place(place, network_type="drive")
                    else: G = ox.graph_from_point(center, dist=radius_m, network_type="drive")
                    break  # Success
                except Exception as e:
                    last_err = e
                    continue
            
            if G is None:
                raise last_err
                
            save(G, path)
        return cls(G, label=label or place or f"{center[0]:.4f},{center[1]:.4f} r={radius_m}m")

    def nearest_node(self, lat, lon):
        _, i = self._tree.query([lat, lon * np.cos(np.radians(self.lat.mean()))]); return int(i)

    def sample_customers(self, n, seed=0, depot=None, with_tw=False):
        """depot = (lat, lon) or None (network centre); customers = random distinct nodes"""
        rng = np.random.default_rng(seed)
        d = self.nearest_node(*depot) if depot else self.nearest_node(self.lat.mean(), self.lon.mean())
        pool = [i for i in range(self.N) if i != d]
        cust = rng.choice(pool, size=min(n, len(pool)), replace=False).tolist()
        stops = [d] + cust
        demands = [0] + rng.integers(1, 16, len(cust)).tolist()
        if not with_tw:
            return stops, demands
        tw = [(0.0, 480.0)]
        service = [0.0]
        for _ in cust:
            start_window = float(rng.choice([15.0, 45.0, 90.0, 150.0, 210.0, 270.0, 330.0]))
            dur = float(rng.choice([60.0, 90.0, 120.0]))
            tw.append((start_window, min(480.0, start_window + dur)))
            service.append(float(rng.choice([3.0, 5.0, 8.0])))
        return stops, demands, tw, service

    def snap_stops(self, depot, customers):
        """depot=(lat,lon); customers=[(lat,lon,demand)] -> (node list, demand list)"""
        nodes = [self.nearest_node(*depot)]; dem = [0]
        for lat, lon, q in customers:
            nodes.append(self.nearest_node(lat, lon)); dem.append(int(q))
        return nodes, dem

    def km_between(self, i, j):
        k = 111.32
        return float(np.hypot((self.lat[i] - self.lat[j]) * k, (self.lon[i] - self.lon[j]) * k * np.cos(np.radians(self.lat[i]))))


def synthetic_city(seed=1, rows=18, cols=18, center=(12.9716, 77.5946), spacing_m=260):
    """OFFLINE DEMO ONLY: an OSM-shaped synthetic city (one-way streets, arterials, closed roads).
    Used for tests and for running the dashboard without internet. Never present it as real data."""
    rng = np.random.default_rng(seed)
    G = nx.MultiDiGraph()
    dlat = spacing_m / 111320.0; dlon = spacing_m / (111320.0 * np.cos(np.radians(center[0])))
    for i in range(rows):
        for j in range(cols):
            G.add_node(i * cols + j, y=center[0] + (i - rows / 2) * dlat + rng.normal(0, dlat * .12),
                       x=center[1] + (j - cols / 2) * dlon + rng.normal(0, dlon * .12))
    def add(a, b, hw):
        if rng.random() < 0.03: return                           # closed road
        L = float(np.hypot((G.nodes[a]["y"] - G.nodes[b]["y"]) * 111320, (G.nodes[a]["x"] - G.nodes[b]["x"]) * 111320 * np.cos(np.radians(center[0]))))
        G.add_edge(a, b, length=L * (1 + .08 * rng.random()), highway=hw)
        if hw in ("primary", "secondary") or rng.random() < 0.7: G.add_edge(b, a, length=L, highway=hw)   # ~30% of small streets are one-way
    for i in range(rows):
        for j in range(cols):
            a = i * cols + j
            hw_h = "primary" if i % 6 == 3 else "secondary" if i % 3 == 0 else "residential"
            hw_v = "primary" if j % 6 == 3 else "secondary" if j % 3 == 0 else "residential"
            if j + 1 < cols: add(a, a + 1, hw_h)
            if i + 1 < rows: add(a, a + cols, hw_v)
    return RoadNet(G, label="SYNTHETIC demo city (offline)", synthetic=True)
