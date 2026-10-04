"""Standalone Leaflet map (OpenStreetMap tiles) - no extra Python deps; works inside Streamlit or as a saved .html file."""
import json
import numpy as np
from .problem import leg_edges

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324", "#800000", "#808000", "#000075", "#f032e6", "#469990"]


def _edge_line(net, e):
    if net.geom[e]: return [[float(a), float(b)] for a, b in net.geom[e]]
    return [[float(net.lat[net.u[e]]), float(net.lon[net.u[e]])], [float(net.lat[net.v[e]]), float(net.lon[net.v[e]])]]


def _color(r):
    return "#1a9850" if r >= 0.85 else "#a6d96a" if r >= 0.7 else "#fee08b" if r >= 0.55 else "#f46d43" if r >= 0.4 else "#a50026"


def leaflet_html(net, state, prob=None, routes=None, height=620, max_edges=6000):
    E = np.arange(net.E)
    if net.E > max_edges:                                    # keep the page light: slowest roads + every major road
        keep = np.argsort(state.ratio)[: max_edges // 2].tolist() + np.where(net.rank <= 2)[0].tolist()
        E = np.unique(keep)[:max_edges]
    traffic = [dict(l=_edge_line(net, int(e)), c=_color(float(state.ratio[e])), w=int(2 + 3 * (net.rank[e] <= 3))) for e in E]
    plan = []; stops = []
    if prob is not None and routes:
        for k, r in enumerate(routes):
            seq = [0] + r + [0]; pts = []
            for a, b in zip(seq[:-1], seq[1:]):
                for e in leg_edges(prob, a, b): pts += _edge_line(net, e)
            plan.append(dict(l=pts, c=PALETTE[k % len(PALETTE)], n=f"Vehicle {k+1}: {len(r)} stops"))
        nodes = prob.ctx[1]
        stops = [dict(p=[float(net.lat[n]), float(net.lon[n])], d=int(prob.dem[i]), depot=(i == 0)) for i, n in enumerate(nodes)]
    c = [float(net.lat.mean()), float(net.lon.mean())]
    return f"""<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<div id="map" style="height:{height}px;width:100%;border-radius:8px"></div>
<script>
const T={json.dumps(traffic)}, P={json.dumps(plan)}, S={json.dumps(stops)};
const map=L.map('map',{{preferCanvas:true}}).setView({json.dumps(c)},14);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);
const tl=L.layerGroup().addTo(map), pl=L.layerGroup().addTo(map);
T.forEach(e=>L.polyline(e.l,{{color:e.c,weight:e.w,opacity:0.75}}).addTo(tl));
P.forEach(r=>L.polyline(r.l,{{color:r.c,weight:5,opacity:0.95}}).bindTooltip(r.n).addTo(pl));
S.forEach(s=>L.circleMarker(s.p,{{radius:s.depot?10:5,color:'#000',fillColor:s.depot?'#1B2A49':'#fff',fillOpacity:1,weight:2}}).bindTooltip(s.depot?'Depot':'Demand '+s.d).addTo(pl));
L.control.layers(null,{{'Live traffic (green=free, red=jammed)':tl,'Optimised routes':pl}}).addTo(map);
const b=[].concat(...T.slice(0,2000).map(e=>e.l)); if(b.length) map.fitBounds(L.latLngBounds(b));
</script>"""
