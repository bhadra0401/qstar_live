# Mathematical Formulation and System Architecture
## SIH 2026 Problem Statement 1 (SIH26137)
### Quantum-Inspired Intelligent Traffic Route Optimization in Transportation Systems Using Metaheuristic Optimization

---

## 1. Graph-Based Network Modeling (Deliverable 1)

The urban transportation network is modeled as a directed, weighted multigraph $\mathcal{G} = (\mathcal{V}_{\text{road}}, \mathcal{E}_{\text{road}})$, where:
- $\mathcal{V}_{\text{road}}$ represents road intersections, junctions, and logistics depot facilities.
- $\mathcal{E}_{\text{road}} \subseteq \mathcal{V}_{\text{road}} \times \mathcal{V}_{\text{road}}$ represents directed street segments, explicitly modeling one-way traffic corridors, turn prohibitions, and speed limits downloaded via OpenStreetMap (OSM).

### 1.1 Edge Attributes & Real-Time Dynamic Weights
Each directed edge $e = (u, v) \in \mathcal{E}_{\text{road}}$ possesses:
- Free-flow length: $D_e$ (kilometers)
- Legal speed limit: $V_e^0$ (km/h) derived from OSM `maxspeed` or road classification
- Free-flow transit time: $T_e^0 = \frac{D_e}{V_e^0} \times 60$ (minutes)

Under dynamic traffic conditions observed at epoch $t$, the TomTom Traffic Flow API (or dynamic volume-delay model) provides a speed ratio:
$$\rho_e(t) = \frac{V_e(t)}{V_e^0} \in [0.03, 1.20]$$
where $\rho_e(t) \to 1.0$ indicates free flow, $\rho_e(t) \approx 0.30$ indicates heavy congestion, and $\rho_e(t) \le 0.03$ represents physical road closures.

The generalized dynamic cost $w_e(t)$ for traversing edge $e$ is formulated as a multi-objective trade-off:
$$w_e(t) = \alpha \cdot T_e(t) + \beta \cdot D_e + \gamma \cdot C_e^{\text{cong}}(t)$$
where:
- $T_e(t) = \frac{T_e^0}{\rho_e(t)}$ is the live transit time (minutes).
- $C_e^{\text{cong}}(t) = D_e \cdot \max\left(0, \frac{1}{\rho_e(t)} - 1\right)$ represents congestion exposure (delay-weighted kilometers).
- $\alpha, \beta, \gamma \ge 0$ are user-configurable trade-off weights (default: $\alpha=1.0, \beta=0.3, \gamma=0.6$).

---

## 2. Mathematical Optimization Model (Deliverable 2)

Given a logistics request with depot $0$ and customer stop set $\mathcal{C} = \{1, 2, \dots, n\}$, we construct the customer-level complete directed graph $\mathcal{K} = (\mathcal{V}, \mathcal{A})$ where $\mathcal{V} = \{0\} \cup \mathcal{C}$ and arc costs $c_{ij}(t)$, distances $d_{ij}$, and travel times $\tau_{ij}(t)$ are computed via all-pairs directed Dijkstra searches on $(\mathcal{V}_{\text{road}}, \mathcal{E}_{\text{road}}, w(t))$.

### 2.1 Decision Variables
- $x_{ijk} \in \{0, 1\}$: Binary variable equal to $1$ if vehicle $k \in \{1, \dots, K\}$ traverses arc $(i, j)$, $0$ otherwise.
- $t_{ik} \ge 0$: Continuous variable representing the arrival time of vehicle $k$ at node $i \in \mathcal{V}$.
- $u_{ik} \ge 0$: Continuous variable representing the accumulated load of vehicle $k$ after visiting node $i$.

### 2.2 Objective Function
The goal is to minimize total generalized routing cost, driver overtime/delay penalties, and fleet allocation:
$$\min \quad \mathcal{Z} = \sum_{k=1}^K \sum_{i \in \mathcal{V}} \sum_{j \in \mathcal{V}} c_{ij}(t) x_{ijk} + \lambda_{\text{tw}} \sum_{i \in \mathcal{C}} \max(0, t_{ik} - l_i) + \lambda_{\text{fleet}} \max(0, K_{\text{used}} - K_{\text{target}})$$

### 2.3 Mathematical Constraints
1. **Customer Visit Requirement**: Each customer is visited exactly once by exactly one vehicle:
   $$\sum_{k=1}^K \sum_{j \in \mathcal{V}, j \neq i} x_{ijk} = 1 \quad \forall i \in \mathcal{C}$$

2. **Flow Conservation at Depot**: Every vehicle departs from and returns to the depot:
   $$\sum_{j \in \mathcal{C}} x_{0jk} = \sum_{i \in \mathcal{C}} x_{i0k} \le 1 \quad \forall k \in \{1, \dots, K\}$$

3. **Continuity of Route**:
   $$\sum_{i \in \mathcal{V}, i \neq p} x_{ipk} - \sum_{j \in \mathcal{V}, j \neq p} x_{pjk} = 0 \quad \forall p \in \mathcal{C}, \forall k \in \{1, \dots, K\}$$

4. **Vehicle Capacity Constraints**:
   $$\sum_{i \in \mathcal{C}} q_i \sum_{j \in \mathcal{V}, j \neq i} x_{ijk} \le Q \quad \forall k \in \{1, \dots, K\}$$

5. **Customer Time Windows (VRPTW)**:
   $$t_{ik} + s_i + \tau_{ij}(t) - M(1 - x_{ijk}) \le t_{jk} \quad \forall i \in \mathcal{V}, j \in \mathcal{C}, i \neq j, \forall k$$
   $$e_i \le t_{ik} \le l_i + \text{slack}_i \quad \forall i \in \mathcal{C}, \forall k$$
   where $[e_i, l_i]$ is the designated delivery window, $s_i$ is the service time, and $M$ is a sufficiently large positive constant.

6. **Subtour Elimination**: Enforced implicitly via the vehicle capacity cumul flow $u_{ik}$ (Miller-Tucker-Zemlin theorem) and the exact Prins split partitioning.

---

## 3. Quantum-Inspired Metaheuristic Engine: Q-STAR (Deliverable 3)

Classical PSO suffers from premature convergence in high-dimensional discrete routing because velocity updates collapse into local minima. Q-STAR replaces Newton-classical trajectories with a **quantum wave function in a delta potential well**.

### 3.1 Quantum Delta Potential Well Wave Equation
In quantum mechanics, a particle moving in a one-dimensional delta potential well centered at point $p$ satisfies the stationary Schrödinger equation:
$$\frac{d^2 \psi(y)}{dy^2} + \frac{2m}{\hbar^2} \left[ E + V_0 \delta(y - p) \right] \psi(y) = 0$$

Solving for bound eigenstates yields the probability density function for the particle's coordinate $X$:
$$Q(X) = |\psi(X)|^2 = \frac{1}{L} \exp\left( - \frac{2 |X - p|}{L} \right)$$
where $L$ is the characteristic quantum length scale:
$$L = 2 \alpha |m_{\text{best}} - X|$$
Here, $m_{\text{best}}$ is the mean best position of the swarm:
$$m_{\text{best}} = \sum_{j=1}^m w_j P_{\text{best}, j}, \quad w_j = \frac{\ln(m + 1) - \ln(j)}{\sum \dots}$$

### 3.2 Position Update via Inversion Sampling
Using Monte Carlo inversion of the cumulative distribution function with uniform random numbers $u \sim \mathcal{U}(0, 1)$ and stochastic attractor $p = \phi P_{\text{best}} + (1 - \phi) G_{\text{best}}$:
$$X_{i, d}^{t+1} = p_{i, d}^t \pm \alpha \left| m_{\text{best}, d}^t - X_{i, d}^t \right| \ln\left( \frac{1}{u} \right)$$
The contraction-expansion parameter $\alpha$ dynamically adjusts based on population diversity feedback:
$$\alpha(t) = \left[ \alpha_{\max} - (\alpha_{\max} - \alpha_{\min}) \left( \frac{t}{T_{\max}} \right)^{0.7} \right] \times \left( 1 + 0.8 \max\left(0, 1 - \frac{\mathcal{D}(t)}{\mathcal{D}_0}\right) \right)$$

### 3.3 Quantum Tunneling Operator (Cauchy Kicks)
When a particle stagnates for $\ge 6$ consecutive iterations without improvement, a quantum tunneling event is simulated. Classical Gaussian mutations fail to escape deep basin attractors; Q-STAR samples from a heavy-tailed Cauchy-Lorentz distribution:
$$f(x; x_0, \gamma) = \frac{1}{\pi \gamma \left[ 1 + \left( \frac{x - x_0}{\gamma} \right)^2 \right]}$$
$$X_{i, d}^{\text{tun}} = X_{i, d} + \sigma \cdot \tan\left( \pi (r - 0.5) \right)$$
The infinite variance of the Cauchy distribution provides non-zero probability for long-range "tunneling" leaps across energetic barriers in the solution landscape.

### 3.4 Continuous-to-Discrete Mapping: Prins Split Decoder
1. **Random-Key Encoding**: Continuous vector $X_i \in [0, 1]^n$ is converted to rank permutation $\pi = \text{argsort}(X_i) + 1$.
2. **Exact Split Dynamic Program**: An auxiliary DAG is constructed where arc $(i, j)$ represents a feasible vehicle route serving $\pi[i+1 \dots j]$ satisfying capacity $Q$ and time windows $[e, l]$. Bellman-Ford/Dijkstra finds the provably optimal vehicle partition in $O(n^2)$.
3. **Memetic Local Search**: Lamarckian refinement applies intra-route 2-Opt and inter-route Relocate operators, immediately writing improvements back to the particle representation (`encode()`).

---

## 4. Dynamic Loop & Drift Warm-Start (Deliverable 4 & 5)

When traffic conditions shift from state $\mathcal{S}_1$ to $\mathcal{S}_2$:
1. **Drift Evaluation**:
   $$\text{Drift} = \frac{\mathcal{Z}_{\mathcal{S}_2}(\mathcal{R}_{\text{prior}}) - \mathcal{Z}_{\mathcal{S}_1}(\mathcal{R}_{\text{prior}})}{\mathcal{Z}_{\mathcal{S}_1}(\mathcal{R}_{\text{prior}})}$$
2. **Decision Rule**:
   - If $|\text{Drift}| \le \theta$ (default $\theta = 0.03$), the plan is retained with updated ETAs.
   - If $|\text{Drift}| > \theta$, Q-STAR executes a **warm-start re-optimisation** seeded with canonical random keys $X_{\text{seed}} = \text{encode}(\mathcal{R}_{\text{prior}})$.
   - Solves in $\le 30\%$ of the initial compute budget while maintaining driver territorial stability.
