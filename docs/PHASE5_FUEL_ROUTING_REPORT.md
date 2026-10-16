# TravelDB Phase 5: Fuel-Aware Decision Support & Reroute Engine Report

## 1. Executive Summary
Phase 5 implements the core decision support intelligence of TravelDB: solving the **Gas Station Problem** along the Chennai–Vellore highway corridor (NH 48 / AH 45). The engine integrates vehicle tank capacity, rated mileage, current fuel levels, and safety reserve thresholds with real-world fuel station locations (`FUEL_STATION`) and official daily retail fuel prices (`FUEL_PRICE`). It determines whether a trip is feasible without stopping, plans optimal refuel stops to prevent stranding, and dynamically recalculates routes when mid-trip fuel burn or road blockage events occur, logging full audit trails in MySQL 8.0.

---

## 2. Mathematical Formulation & Physics Model

### A. Road-Level Fuel Consumption
For each directed edge $e$ in the traversed path $P$, fuel consumption in liters $f(e)$ is computed using:
$$f(e) = \frac{\text{length\_km}(e)}{\text{rated\_mileage\_kmpl}} \times \alpha_{\text{road\_type}}(e) \times \beta_{\text{weather}}(e)$$

Where:
- $\alpha_{\text{road\_type}}(e)$ is the statutory fuel consumption factor from `ROAD_TYPE`:
  - `motorway` / `motorway_link`: $1.05$ – $1.10$ (high-speed aerodynamic wind resistance)
  - `trunk` (National Highway): $1.00$ (optimal cruising efficiency)
  - `primary` (State Highway): $1.05$
  - `secondary` (Major District Road): $1.15$ (frequent deceleration / acceleration)
  - `tertiary` / `unclassified`: $1.25$ – $1.35$ (unpaved surface friction, stop-and-go)
- $\beta_{\text{weather}}(e)$ is the environmental penalty:
  - Precipitation $> 2.0\text{ mm}$ or wind $> 30\text{ km/h}$ adds $+5\%$ to $+10\%$ fuel consumption due to tire hydroplaning and aerodynamic drag.

### B. Feasibility & Safety Reserve Invariant
- **Tank Capacity ($C$)**: Physical fuel capacity of the vehicle (e.g. 37.0 L for Maruti Swift, 45.0 L for Hyundai Verna).
- **Initial Fuel ($F_0$)**: Liters present in tank at start.
- **Safety Reserve ($R$)**: Statutory reserve threshold (default $3.0\text{ L}$). **Invariant: Tank fuel level $F(t) \ge R$ for all times $t$**.
- **Safety Margin ($\gamma$)**: Safety factor (default $0.85$, providing a $15\%$ safety buffer against unexpected headwinds and idling).
- **Usable Initial Fuel**:
  $$F_{\text{usable}} = \max(0.0, \; F_0 - R) \times \gamma$$
- **Feasibility Condition**:
  - If $F_{\text{usable}} \ge \sum_{e \in P} f(e)$: **Trip is 100% Feasible with ZERO refuel stops**.
  - If $F_{\text{usable}} < \sum_{e \in P} f(e)$: **Trip is Fuel-Constrained and requires scheduled refuel stops**.

---

## 3. The Gas Station Problem Solver (`engine/fuel_router.py`)

### Algorithm: 2-Stage Reduced Corridor Horizon Solver
1. **Candidate Station Indexing**:
   - Queries `FUEL_STATION` instances along the corridor whose `nearest_node_id` is connected to the Giant SCC (200 candidate stations available).
   - Maps each station $s_k$ to its distance $d(s_k)$ along the corridor path.
2. **Horizon Lookahead Simulation**:
   - From current position $x$ with fuel level $F$:
     - Check if destination can be reached with $F - R \ge 0$. If yes, arrive at destination directly.
     - Else, identify all stations reachable within $(F - R) \times M \times \gamma$.
     - If no stations are reachable: Flag `feasible = False` and calculate the exact minimum initial fuel needed to reach the first pump.
     - If reachable stations exist: Pick the furthest reachable station $s^*$ (minimizes stops) or the lowest-price station.
     - Refuel to capacity: $\Delta F = C - F_{\text{arrival}}$.
     - Financial Cost: $\text{Cost} = \Delta F \times P_{\text{station}}$.
     - Advance vehicle state: $x \leftarrow d(s^*)$, $F \leftarrow C$.
     - Repeat until destination is reached.

---

## 4. Benchmark Verification Cases

### Test Case 1: Feasible Journey (Poonamallee $\to$ Damal, 80.33 km, Initial Fuel = 15.0 L)
- **Vehicle**: Maruti Swift VXi (Rated Mileage: 17.5 km/L, Tank: 37.0 L)
- **Fuel Needed**: 4.75 L
- **Refuel Stops**: **0 stops**
- **Arrival Fuel**: **10.25 L** (safely above the 3.0 L reserve)
- **Persisted**: `TRIP #3` and `ROUTE_PLAN #3` (`feasible = 1`).

### Test Case 2: Fuel-Constrained Journey (Poonamallee $\to$ Damal, 80.33 km, Initial Fuel = 4.0 L)
- **Initial State**: Only 4.0 L in tank (usable range before reserve: only $\sim 15\text{ km}$).
- **Result**: Vehicle cannot reach Damal (80.33 km) without refueling.
- **Scheduled Stop**:
  - **Stop #1**: Bharat Petroleum at KM 7.7 on NH 48.
  - **Arrival Fuel**: 3.56 L (arrived safely before reserve threshold of 3.0 L).
  - **Fuel Added**: 33.44 L (filled to full tank capacity of 37.0 L).
  - **Retail Fuel Price**: ₹100.75 / L (Tamil Nadu IOCL Daily RSP).
  - **Cost**: **₹3,369.08**
  - **Estimated Arrival**: 2026-10-16 04:20:50.
- **Persisted**: `TRIP #4`, `ROUTE_PLAN #4`, and `ROUTE_PLAN_STOP` (plan_stop_id 2).

---

## 5. Dynamic Rerouting Engine (`engine/reroute.py`)

### Mid-Trip Reroute Triggers
- `'low_fuel'`: Actual telemetry shows fuel consumed faster than anticipated (e.g. idling in traffic or sensor drop).
- `'incident'` / `'closure'`: A road segment on the active route is closed by an accident.
- `'traffic'`: Major congestion delay exceeding threshold.
- `'manual'`: Driver requests re-optimization.

### Transactional Reroute Execution
1. Evaluates active `trip_id` and latest `old_route_plan_id`.
2. Computes a new optimal route and refuel plan from the vehicle's live GPS coordinates to the destination.
3. Inserts the new plan as `new_route_plan_id`.
4. Atomically logs an audit record in `REROUTE_EVENT`:
   - `trip_id`: 3
   - `trigger_reason`: `'low_fuel'`
   - `details`: `{"old_km": 80.33, "new_km": 61.65, "current_fuel_l": 2.5, "warning": "Low fuel sensor triggered"}`
   - `old_route_plan_id`: 3
   - `new_route_plan_id`: 5
   - `explanation`: `"Dynamic reroute triggered due to 'low_fuel'. Vehicle position: (12.9675, 79.9436), current fuel: 2.50 L. Old Plan #3 superseded by New Plan #5."`
5. Updates `TRIP.status` to `'active'`.

---

## 6. Automated Test Suite Verification
All 4 Phase 5 tests passed, bringing total project test coverage to **26 / 26 passed tests (100%)**:
```text
tests/test_phase5_fuel_and_reroute.py::test_fuel_pricing_resolution PASSED [ 88%]
tests/test_phase5_fuel_and_reroute.py::test_feasible_journey_no_refuel_stops PASSED [ 92%]
tests/test_phase5_fuel_and_reroute.py::test_gas_station_problem_solver_constrained_fuel PASSED [ 96%]
tests/test_phase5_fuel_and_reroute.py::test_dynamic_reroute_event_lifecycle PASSED [100%]
```
