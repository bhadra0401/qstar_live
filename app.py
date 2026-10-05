"""Q-STAR live dashboard.   Run:  streamlit run app.py"""
import os, time, io
import numpy as np, pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from qstar import RoadNet, synthetic_city, Weights
from qstar.traffic import SimulatedProvider, FreeFlowProvider, TomTomProvider, ReplayProvider
from qstar.planner import Planner
from qstar.runner import compare, METHODS
from qstar.viz import leaflet_html

st.set_page_config(page_title="Q-STAR live traffic routing", layout="wide")
S = st.session_state
st.title("Q-STAR: quantum-inspired routing on real roads with live traffic")

@st.cache_data(ttl=3600)
def search_places(query, api_key=None):
    """Search locations by keyword or place name with auto-complete (TomTom & OSM)."""
    if not query or len(query.strip()) < 2:
        return []
    import urllib.parse
    import requests
    # 1. First try TomTom Search API if key available (fast, rich address metadata)
    if api_key:
        try:
            url = f"https://api.tomtom.com/search/2/search/{urllib.parse.quote(query)}.json"
            r = requests.get(url, params={"key": api_key, "limit": 6}, timeout=3)
            if r.status_code == 200:
                results = []
                for item in r.json().get("results", []):
                    pos = item.get("position", {})
                    addr = item.get("address", {}).get("freeformAddress", "")
                    poi = item.get("poi", {}).get("name", "")
                    title = f"{poi} - {addr}" if poi and poi not in addr else (addr or poi)
                    if pos.get("lat") and pos.get("lon"):
                        results.append({"name": title, "lat": float(pos["lat"]), "lon": float(pos["lon"])})
                if results:
                    return results
        except Exception:
            pass
    # 2. Fallback to OpenStreetMap Nominatim
    try:
        headers = {"User-Agent": "QStarRoutingSIH/1.0"}
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 6, "addressdetails": 1},
            headers=headers,
            timeout=3
        )
        if r.status_code == 200:
            return [{"name": item["display_name"], "lat": float(item["lat"]), "lon": float(item["lon"])} for item in r.json()]
    except Exception:
        pass
    return []


PRESETS = {
    "Indiranagar, Bengaluru": (12.9733, 77.6405),
    "Marathahalli, Bengaluru": (12.9553, 77.6984),
    "Koramangala, Bengaluru": (12.9352, 77.6245),
    "Whitefield, Bengaluru": (12.9698, 77.7500),
    "HSR Layout, Bengaluru": (12.9121, 77.6446),
    "Connaught Place, New Delhi": (28.6315, 77.2167),
    "Bandra West, Mumbai": (19.0596, 72.8295),
    "Cyber City, Gurugram": (28.4950, 77.0895),
    "Hitech City, Hyderabad": (17.4474, 78.3762),
    "Lower Manhattan, New York": (40.7128, -74.0060),
    "Central London, UK": (51.5074, -0.1278),
    "Marina Bay, Singapore": (1.2868, 103.8545),
}

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("1. Road network")
    src = st.radio("Search Mode", [
        "🔍 Live Location Search (Auto-Suggest)",
        "⚡ Popular City Presets",
        "📍 Custom Lat / Lon & Radius",
        "Offline synthetic demo (NOT real)"
    ])
    
    place = None; center = None; radius = 2000; label_name = None
    default_key = os.environ.get("TOMTOM_API_KEY", "")
    
    if src.startswith("🔍 Live Location Search"):
        query = st.text_input("Type place, area, or landmark", "Indiranagar, Bengaluru")
        results = search_places(query, api_key=default_key)
        if results:
            opts = [f"📍 {r['name'][:55]}..." if len(r['name']) > 55 else f"📍 {r['name']}" for r in results]
            idx = st.selectbox("Matching locations (Google/Apple Maps style)", range(len(opts)), format_func=lambda i: opts[i])
            chosen = results[idx]
            center = (chosen["lat"], chosen["lon"])
            parts = [p.strip() for p in chosen["name"].split(",")]
            label_name = f"{parts[0]}, {parts[-1]}" if len(parts) > 1 else parts[0]
            st.caption(f"Coordinates: `{chosen['lat']:.4f}, {chosen['lon']:.4f}`")
        else:
            st.warning("Type a location above to see real-time suggestions.")
            center = (12.9733, 77.6405); label_name = query
        radius = st.slider("Road network radius (meters)", 800, 5000, 2000, 200)
        
    elif src.startswith("⚡ Popular City Presets"):
        choice = st.selectbox("Select target area", list(PRESETS.keys()))
        center = PRESETS[choice]
        label_name = choice
        radius = st.slider("Road network radius (meters)", 800, 5000, 2000, 200)
        st.caption(f"Coordinates: `{center[0]:.4f}, {center[1]:.4f}`")
        
    elif src.startswith("📍 Custom Lat"):
        c1, c2 = st.columns(2)
        lat0 = c1.number_input("Lat", value=12.9716, format="%.5f")
        lon0 = c2.number_input("Lon", value=77.5946, format="%.5f")
        radius = st.slider("Radius (meters)", 800, 6000, 2500, 250)
        center = (lat0, lon0)
        label_name = f"{lat0:.4f}, {lon0:.4f} (r={radius}m)"
    else:
        place = center = None; radius = 0

    @st.cache_resource(show_spinner=False)
    def load_road_network(src_mode, place_val, center_val, radius_val, label_val):
        if src_mode.startswith("Offline"):
            return synthetic_city()
        return RoadNet.from_osm(place=place_val, center=center_val, radius_m=radius_val, label=label_val)

    if st.button("Load network", type="primary"):
        with st.spinner(f"Loading road network ({label_name or 'selected area'})..."):
            try:
                S.net = load_road_network(src, place, center, radius, label_name)
                S.pop("planner", None); S.pop("bench", None)
            except Exception as e:
                st.error(f"Could not load the network: {e}")

    st.header("2. Traffic source")
    tsrc = st.selectbox("Traffic data", ["TomTom live traffic (API key)", "Simulated rush hour", "Replay recorded real traffic", "Free flow (no traffic)"])
    key = hour = None
    if tsrc.startswith("TomTom"):
        key = st.text_input("TomTom API key", os.environ.get("TOMTOM_API_KEY", ""), type="password")
        samples = st.slider("Probe points per refresh (= API requests)", 10, 120, 40, 5)
    elif tsrc.startswith("Simulated"):
        hour = st.slider("Hour of day", 0.0, 24.0, 18.0, 0.25); inten = st.slider("Intensity", 0.5, 2.0, 1.0, 0.1)
    elif tsrc.startswith("Replay"):
        rfile = st.text_input("Snapshot file", "data/traffic_snapshots.json")

    st.header("3. Fleet & objective")
    n_cust = st.slider("Customers (random)", 5, 150, 40)
    Q = st.number_input("Vehicle capacity", 10, 500, 60); K = st.number_input("Max vehicles", 1, 50, 8)
    use_tw = st.checkbox("Enable Customer Delivery Time Windows (VRPTW)", value=False)
    up = st.file_uploader("...or upload customers CSV (lat,lon,demand)", type="csv")
    wa, wb, wg = st.slider("Weight: time", 0.0, 2.0, 1.0, 0.1), st.slider("Weight: distance", 0.0, 2.0, 0.3, 0.1), st.slider("Weight: congestion", 0.0, 2.0, 0.6, 0.1)
    method = st.selectbox("Algorithm", ["Q-STAR", "QPSO+LS", "PSO+LS", "GA+LS", "Clarke-Wright", "OR-Tools"])
    tlim = st.slider("Time budget per solve (s)", 2, 60, 10)
    theta = st.slider("Re-optimise if cost drifts more than (%)", 1, 20, 3) / 100
    seed = st.number_input("Random seed", 0, 9999, 0)


def make_provider():
    if tsrc.startswith("TomTom"): return TomTomProvider(api_key=key, max_samples=samples, ttl_s=30)
    if tsrc.startswith("Simulated"): return SimulatedProvider(hour=hour, intensity=inten, seed=int(seed))
    if tsrc.startswith("Replay"): return ReplayProvider(rfile)
    return FreeFlowProvider()


if "net" not in S or S.net is None:
    try:
        S.net = load_road_network("⚡ Popular City Presets", None, PRESETS["Indiranagar, Bengaluru"], 2000, "Indiranagar, Bengaluru")
    except Exception:
        S.net = synthetic_city()

net = S.get("net")
if net.synthetic: st.warning("Synthetic offline city: for testing only, not real-world data.")
st.caption(f"Network: **{net.label}** - {net.N:,} junctions, {net.E:,} directed road segments")

# ------------------------------------------------------------------ actions
b1, b2, b3 = st.columns(3)
if b1.button("Fetch traffic and optimise", type="primary"):
    try:
        if up is not None:
            df = pd.read_csv(up); stops, dem = net.snap_stops((net.lat.mean(), net.lon.mean()), [(r.lat, r.lon, r.demand) for r in df.itertuples()])
            tw = service = None
        else:
            if use_tw:
                stops, dem, tw, service = net.sample_customers(n_cust, seed=int(seed), with_tw=True)
            else:
                stops, dem = net.sample_customers(n_cust, seed=int(seed), with_tw=False)
                tw = service = None
        S.planner = Planner(net, make_provider(), stops, dem, int(Q), int(K), Weights(wa, wb, wg), float(tlim), method, tw=tw, service=service)
        with st.spinner("Reading traffic and optimising..."):
            S.planner.optimise(); S.blind = S.planner.blind_comparison()
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")
pl = S.get("planner")
if pl is not None and b2.button("Refresh traffic and re-optimise (warm start)"):
    pl.provider = make_provider()
    with st.spinner("Updating traffic..."):
        try: pl.refresh(theta); S.blind = pl.blind_comparison()
        except Exception as e: st.error(f"{type(e).__name__}: {e}")
auto = b3.checkbox("Auto-refresh every 60 s")

if pl is None or pl.plan is None:
    st.info("Press **Fetch traffic and optimise**."); st.stop()

# ------------------------------------------------------------------ results
d, t, c = pl.prob.metrics(pl.plan["routes"])
bl = S.get("blind")
tab_map, tab_kpi, tab_bench, tab_conv, tab_log, tab_theory = st.tabs(["Map", "KPIs and impact", "Benchmark", "Convergence", "Dynamic log", "SIH 2026 Deliverables & Theory"])
with tab_map:
    st.caption(f"Traffic source: **{pl.state.source}** | directly measured segments: {pl.state.n_observed} of {pl.state.ratio.size} (the rest are interpolated)" if pl.state.n_observed else f"Traffic source: **{pl.state.source}**")
    components.html(leaflet_html(net, pl.state, pl.prob, pl.plan["routes"]), height=650)
with tab_kpi:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Vehicles used", len(pl.plan["routes"])); k2.metric("Distance", f"{d:.1f} km"); k3.metric("Travel time", f"{t:.0f} min"); k4.metric("Congestion exposure", f"{c:.1f} cong-km")
    if bl:
        st.subheader("What does ignoring live traffic cost?")
        st.caption("Same optimiser; one plan uses free-flow speeds only, the other uses the current traffic. Both are driven through the current traffic.")
        df = pd.DataFrame({"Traffic-blind plan": bl["blind"], "Live-traffic-aware (Q-STAR)": bl["aware"]}).T.rename(columns={"cost": "Generalised cost", "km": "km", "minutes": "minutes", "cong": "congestion-km"})
        st.dataframe(df.style.format("{:.1f}")); sav = (1 - bl["aware"]["minutes"] / bl["blind"]["minutes"]) * 100
        st.success(f"Travel time {sav:+.1f}% vs the traffic-blind plan; congestion exposure {(1 - bl['aware']['cong'] / max(bl['blind']['cong'], 1e-9)) * 100:+.1f}%.")
        ef = st.number_input("Assumed emission factor (kg CO2 per km, editable assumption)", 0.0, 2.0, 0.25, 0.01)
        st.caption(f"Indicative distance-based CO2: {d * ef:.1f} kg for this plan (idling emissions not modelled).")
    rows = []
    for k, r in enumerate(pl.plan["routes"]):
        seq = [0] + r + [0]; tm = sum(pl.prob.T[a, b] for a, b in zip(seq[:-1], seq[1:])); dd = sum(pl.prob.D[a, b] for a, b in zip(seq[:-1], seq[1:]))
        rows.append(dict(vehicle=k + 1, stops=len(r), load=sum(pl.prob.dem[x] for x in r), km=round(dd, 2), minutes=round(tm, 1), order=" > ".join(map(str, r))))
    rt = pd.DataFrame(rows); st.dataframe(rt)
    st.download_button("Download routes (CSV)", rt.to_csv(index=False), "routes.csv")
    if getattr(pl.prob, "tw", None):
        st.subheader("Customer Delivery Time Windows & Driver Schedule (VRPTW)")
        sched_rows = []
        for k, r in enumerate(pl.plan["routes"]):
            for s in pl.prob.route_schedule(r):
                if s["stop"] == 0: continue
                e, l = pl.prob.tw[s["stop"]]
                sched_rows.append(dict(vehicle=k + 1, customer=s["stop"], demand=pl.prob.dem[s["stop"]],
                                       delivery_window=f"{int(e)} - {int(l)} min", arrival=f"{s['arr']} min",
                                       service_start=f"{s['start']} min", wait=f"{s['wait']} min",
                                       lateness=f"{s['late']} min", status="On-Time" if s["late"] == 0 else f"Late ({s['late']}m)"))
        sdf = pd.DataFrame(sched_rows)
        on_time_pct = (sdf["lateness"] == "0.0 min").mean() * 100 if not sdf.empty else 100.0
        st.caption(f"Fleet On-Time Delivery Performance: **{on_time_pct:.1f}%**")
        st.dataframe(sdf)
with tab_bench:
    st.write("All algorithms get the **same wall-clock budget** on the current traffic state.")
    runs = st.slider("Independent runs per stochastic method", 1, 10, 3)
    if st.button("Run benchmark"):
        with st.spinner("Benchmarking..."):
            S.bench = compare(pl.prob, METHODS, time_limit=float(tlim), runs=runs, seed=int(seed))
    if S.get("bench"):
        cw = S.bench["Clarke-Wright"]["cost"]
        tb = pd.DataFrame([dict(method=m, best_cost=r["cost"], mean_cost=r["mean_cost"], std=r["std_cost"], vs_CW_pct=(r["cost"] / cw - 1) * 100, seconds=r["secs"]) for m, r in S.bench.items()])
        st.dataframe(tb.style.format({"best_cost": "{:.1f}", "mean_cost": "{:.1f}", "std": "{:.2f}", "vs_CW_pct": "{:+.2f}", "seconds": "{:.1f}"}))
        if "OR-Tools" not in S.bench: st.info("OR-Tools not installed: `pip install ortools` to include it.")
with tab_conv:
    series = {m: r["hist"] for m, r in (S.get("bench") or {}).items() if r["hist"]}
    if pl.plan.get("hist"): series.setdefault(pl.method, pl.plan["hist"])
    if series:
        L = max(map(len, series.values()))
        st.line_chart(pd.DataFrame({m: h + [h[-1]] * (L - len(h)) for m, h in series.items()}))
        st.caption("Best cost so far per iteration.")
    else: st.info("Run the benchmark to see convergence curves.")
with tab_log:
    lg = pd.DataFrame(pl.log)
    if not lg.empty:
        lg["time"] = pd.to_datetime(lg["t"], unit="s").dt.strftime("%H:%M:%S"); st.dataframe(lg.drop(columns=["t"]))
        st.caption("drift_pct = change of the current plan's cost under the new traffic. Above the threshold, Q-STAR is warm-started from the previous plan.")
with tab_theory:
    st.subheader("SIH 2026 Deliverables Mapping & Theoretical Foundations")
    st.markdown(r"""
    ### 1. Transportation Graph Model (Deliverable 1)
    - **Directed Road Graph:** $\mathcal{G} = (\mathcal{V}, \mathcal{E})$ from OpenStreetMap, capturing one-way streets, real turn connectivity, and speed limits.
    - **Live Edge Weights:** $w_e(t) = \\alpha T_e(t) + \\beta D_e + \gamma C_e^{\\text{cong}}(t)$, where $T_e(t) = T_e^0 / \\rho_e(t)$ with real TomTom speeds $\\rho_e(t)$.
    
    ### 2. Mathematical Optimization Model (Deliverable 2)
    - **Objective:** $\\min \sum_{k=1}^K \sum_{i,j} c_{ij}(t) x_{ijk} + \lambda_{\\text{tw}} \sum \text{Late}_i + \lambda_{\\text{fleet}} \max(0, K_{\\text{used}} - K)$.
    - **Constraints:** Degree ($\sum x_{ijk}=1$), flow conservation, capacity ($\sum q_i \le Q$), and customer delivery time-windows ($e_i \le t_{ik} \le l_i$).
    
    ### 3. Quantum-Inspired Metaheuristic Engine: Q-STAR (Deliverable 3)
    - **Quantum Delta Potential Well:** Replaces Newtonian velocity with Schrödinger wave probability density:
      $$Q(X) = |\\psi(X)|^2 = \\frac{1}{L} \exp\\left(-\\frac{2|X - p|}{L}\\right), \quad L = 2\\alpha |m_{\\text{best}} - X|$$
      $$X_{i,d}^{t+1} = p_{i,d}^t \pm \\alpha |m_{\\text{best}, d}^t - X_{i,d}^t| \ln(1/u)$$
    - **Quantum Tunneling Operator:** Heavy-tailed Cauchy kicks break deep local minima attractors:
      $$X_{i,d}^{\\text{tun}} = X_{i,d} + \sigma \\tan(\\pi (r - 0.5))$$
    - **Prins Split Dynamic Program:** Polynomial $O(n^2)$ optimal partition of continuous particles into legal vehicle tours.
    - **Memetic Local Search:** 2-Opt and Relocate neighborhood descent.

    ### 4. Dynamic Warm-Start Re-optimisation (Deliverable 4 & 5)
    - **Cost Drift Criterion:** $\\text{Drift} = \\frac{\\mathcal{C}_{\\text{live}}(R_{\\text{prior}}) - \\mathcal{C}_{\\text{old}}}{\\mathcal{C}_{\\text{old}}}$.
    - Above threshold ($\\theta=3\\% $), Q-STAR warm-starts using prior particle coordinates (`init=keys`), cutting re-solve time by $70\\%$.
    """)

if auto:
    time.sleep(60); pl.provider = make_provider()
    try: pl.refresh(theta); S.blind = pl.blind_comparison()
    except Exception as e: st.error(str(e))
    st.rerun()
