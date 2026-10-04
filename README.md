# Q-STAR Live: quantum-inspired routing on real roads with live traffic

Runs the Q-STAR optimiser (quantum-behaved particle swarm + tunnelling + local refinement) on:

- **real road networks** from OpenStreetMap (directed graph, one-way streets, real speed limits)
- **live traffic** from the TomTom Traffic Flow Segment Data API (or recorded real snapshots, or a simulator)
- compared against Clarke-Wright, GA, PSO, standard QPSO and **Google OR-Tools**, under the *same time budget*

## Honest status (read this first)

| Part | Tested where |
|---|---|
| Optimiser, directed cost matrix, one-way roads, dynamic re-optimisation, drift test | Automated tests, offline (`python tests/test_pipeline.py`, 7 tests) |
| TomTom provider (request format, parsing, interpolation, caching, closures) | Tested **against a mocked API only**. Never called the real service. |
| OpenStreetMap download (OSMnx), OR-Tools baseline, Streamlit dashboard, Leaflet map | Written to the documented APIs, **not executed** in the environment where this was built (no internet, packages not installed). Expect to fix small version issues on first run. |
| CVRPLIB loader | Tested on a toy file; real CVRPLIB instances not downloaded. |

So the first thing to do on your machine is run the steps below and fix anything that breaks. Nothing here has produced a real-world result yet; **do not quote numbers until you have produced them yourself** with real data.

## Setup (10 minutes)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python tests/test_pipeline.py                         # all 7 should print PASS
```

1. Free TomTom key: create an account at developer.tomtom.com, create an app, copy the key. The free tier has a daily request quota; check your current limits there.
2. `export TOMTOM_API_KEY=your_key` (Windows: `set TOMTOM_API_KEY=your_key`)

## Run the dashboard

```bash
streamlit run app.py
```

Sidebar: load a place (for example a few square km of your city), choose *TomTom live traffic*, set customers and capacity, press **Fetch traffic and optimise**. Tabs show the map (traffic colours + routes), KPIs, the **traffic-blind versus traffic-aware** comparison, a same-budget benchmark and the dynamic-update log. **Refresh traffic and re-optimise** runs the drift test and warm-starts Q-STAR when traffic changed enough.

No internet or key yet? Choose *Offline synthetic demo* + *Simulated rush hour* to see the full flow (labelled NOT real).

## Produce real evidence (do these before the demo)

```bash
# 1. benchmark on a real city with live traffic; writes results/benchmark.csv
python scripts/run_benchmark.py --place "Indiranagar, Bengaluru, India" --traffic tomtom --n 60 --runs 5 --time 20 --instances 5

# 2. record a day of real traffic (about 40 requests x 48 snapshots = 1,920 requests; check your quota), replay it later offline
python scripts/collect_traffic.py --place "Indiranagar, Bengaluru, India" --samples 40 --every-min 30 --count 48 --out data/traffic_day.json
python scripts/run_benchmark.py --place "Indiranagar, Bengaluru, India" --traffic replay --replay-file data/traffic_day.json

# 3. public VRP benchmark (download an instance such as A-n32-k5 from CVRPLIB): gap to best known
python scripts/cvrplib_benchmark.py path/to/A-n32-k5.vrp --best-known <value from CVRPLIB> --time 30
```

The benchmark prints, per method, the cost relative to Clarke-Wright, plus the **impact table**: the same optimiser planned with free-flow speeds versus live speeds, both driven through the live traffic (time, distance, congestion).

## How live traffic enters the model

- Each directed road segment has a free-flow time from OSM `maxspeed` (or a default per road class).
- TomTom returns `currentSpeed` and `freeFlowSpeed` for the road nearest a probe point. Ratio = current / free-flow. Segment time = free-flow time / ratio. Closures get ratio 0.03 (practically avoided).
- Probe points are spread over the area by farthest-point sampling (major roads first). **Only the probed segments are measured; all others are estimated** by distance-weighted interpolation that fades back to free flow with distance (assumption: 2 km). The dashboard shows how many segments are directly measured. State this openly to judges.
- Cost between stops = Dijkstra on `alpha*time + beta*km + gamma*congestion-km` over the directed graph, so one-way streets and traffic change the matrix; Q-STAR then optimises assignment and order.

## Suggested 5-minute demo

1. Load a congested part of your city; show the map with live traffic colours (it should match what the TomTom/Google map shows right now).
2. Optimise 40 to 60 deliveries: routes appear on real streets.
3. Show *KPIs and impact*: live-aware plan versus traffic-blind plan driven through the same live traffic.
4. Press **Refresh traffic and re-optimise** (or replay a recorded rush hour): show the drift value and the warm-start result.
5. *Benchmark* tab: same time budget for Q-STAR, GA, PSO, QPSO, Clarke-Wright, OR-Tools; show the table as measured, whatever it says.
6. Show the CVRPLIB gap result and the book's exact-optimum test for credibility.

## What you can and cannot claim

- Can claim (once you have run it): works on a real OSM network with live TomTom speeds; handles one-way streets and closures; quantifies the value of live traffic data; compared with OR-Tools and classical metaheuristics under equal time.
- Do **not** claim: that the quantum-inspired operators beat PSO (in our offline tests Q-STAR and PSO+LS were within noise of each other); that it beats OR-Tools or hybrid genetic search (unknown until you measure; OR-Tools is often very strong); that it scales to very large cities (tests stopped around 100-200 customers).
- Be ready to answer: "Is the whole city measured?" (No: probes plus interpolation.) "Is the traffic real-time?" (Updated at each refresh, limited by your quota.)

## Layout

```
app.py                      Streamlit dashboard
qstar/network.py            OSM / networkx road graph, synthetic offline city
qstar/traffic.py            FreeFlow, Simulated (BPR), TomTom live, Replay providers
qstar/problem.py            directed cost matrix, plan evaluation under any traffic state
qstar/algos.py              Q-STAR, QPSO, PSO, GA, Clarke-Wright, local search, exact DP
qstar/planner.py            dynamic loop: refresh, drift test, warm start
qstar/runner.py             equal-time comparison harness
qstar/ortools_baseline.py   OR-Tools baseline
qstar/cvrplib.py            CVRPLIB (.vrp) loader
qstar/viz.py                Leaflet map (OpenStreetMap tiles)
scripts/                    run_benchmark.py, collect_traffic.py, cvrplib_benchmark.py
tests/test_pipeline.py      offline tests
```

## Data licences

Map data: (c) OpenStreetMap contributors (ODbL). Traffic: TomTom Traffic API under your own key and TomTom's terms; do not redistribute recorded snapshots without checking those terms.
