"""Parser for CVRPLIB / TSPLIB-style .vrp files (Augerat A/B/P, Uchoa X, ...), EUC_2D only.
Download instances from http://vrp.galgos.inf.puc-rio.br/ and pass the best-known cost for the gap."""
import re, numpy as np
from .problem import Problem


def load_vrp(path, rounding=True):
    txt = open(path).read(); lines = [l.strip() for l in txt.splitlines()]
    hdr = {}; coords = {}; dem = {}; sec = None
    for l in lines:
        if not l or l == "EOF": continue
        if ":" in l and sec is None or (":" in l and l.split(":")[0].strip().isupper() and not l[0].isdigit()):
            k, v = [x.strip() for x in l.split(":", 1)]; hdr[k] = v; sec = None; continue
        if l.startswith("NODE_COORD_SECTION"): sec = "c"; continue
        if l.startswith("DEMAND_SECTION"): sec = "d"; continue
        if l.startswith("DEPOT_SECTION"): sec = "dep"; continue
        if sec == "c":
            i, x, y = l.split()[:3]; coords[int(i)] = (float(x), float(y))
        elif sec == "d":
            i, q = l.split()[:2]; dem[int(i)] = int(q)
    if hdr.get("EDGE_WEIGHT_TYPE", "EUC_2D") != "EUC_2D": raise ValueError("only EUC_2D supported")
    ids = sorted(coords); depot = ids[0]
    P = np.array([coords[i] for i in ids]); G = np.linalg.norm(P[:, None] - P[None], axis=2)
    if rounding: G = np.rint(G)
    m = re.search(r"-k(\d+)", hdr.get("NAME", "")); K = int(m.group(1)) if m else None
    p = Problem(G, [dem[i] for i in ids], int(hdr["CAPACITY"]), K)
    p.kpen = float(G.max()) * 10
    p.name = hdr.get("NAME", path)
    return p
