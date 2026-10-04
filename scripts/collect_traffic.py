"""Record REAL traffic snapshots from TomTom so the whole demo can be replayed offline (and over a full day).

  export TOMTOM_API_KEY=...
  python scripts/collect_traffic.py --place "Bengaluru, India" --every-min 15 --count 48 --out data/traffic_blr.json
Keep --samples small enough for your daily request quota (requests used = samples x count)."""
import argparse, os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qstar import RoadNet
from qstar.traffic import TomTomProvider

ap = argparse.ArgumentParser()
ap.add_argument("--place"); ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float); ap.add_argument("--radius", type=float, default=2500)
ap.add_argument("--samples", type=int, default=40); ap.add_argument("--every-min", type=float, default=15); ap.add_argument("--count", type=int, default=8)
ap.add_argument("--out", default="data/traffic_snapshots.json")
a = ap.parse_args()
net = RoadNet.from_osm(a.place, (a.lat, a.lon) if a.lat else None, a.radius)
prov = TomTomProvider(max_samples=a.samples, ttl_s=0)
snaps = []
for k in range(a.count):
    st = prov.get_state(net)
    snaps.append(dict(t=st.timestamp, ratio=[round(float(x), 4) for x in st.ratio], n_observed=st.n_observed))
    json.dump(snaps, open(a.out, "w")); print(f"snapshot {k+1}/{a.count}: {st.summary()}  (requests so far: {prov.requests_used})")
    if k + 1 < a.count: time.sleep(a.every_min * 60)
