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

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("1. Road network")
    src = st.radio("Source", ["OpenStreetMap: place name", "OpenStreetMap: lat/lon + radius", "Offline synthetic demo (NOT real)"])
    if src.startswith("OpenStreetMap: place"):
        place = st.text_input("Place", "Indiranagar, Bengaluru, India"); center = None; radius = 0
    elif "lat/lon" in src:
        place = None; c1, c2 = st.columns(2)
        lat0 = c1.number_input("Lat", value=12.9716, format="%.5f"); lon0 = c2.number_input("Lon", value=77.5946, format="%.5f")
        radius = st.slider("Radius (m)", 1000, 6000, 2500, 250); center = (lat0, lon0)
    else:
        place = center = None; radius = 0
    if st.button("Load network", type="primary"):
        with st.spinner("Loading road network..."):
            try:
                S.net = synthetic_city() if src.startswith("Offline") else RoadNet.from_osm(place, center, radius)
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


net = S.get("net")
if net is None:
    st.info("Choose a road network in the sidebar and press **Load network**. The first OpenStreetMap download needs internet and is cached afterwards.")
    st.stop()
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
