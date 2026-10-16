# TravelDB Phase 6: Flask REST API & Interactive Leaflet Dashboard Report

## 1. Executive Summary
Phase 6 completes the primary user-facing layer of the **TravelDB** decision support system. It establishes a Flask 3.1 REST API that exposes the in-memory `python-igraph` routing engine, the 2-Stage Gas Station Problem solver, and spatial layers directly from MySQL 8.0 to an interactive browser frontend built with Leaflet.js.

All **34 unit and integration tests** across Phases 0 through 6 pass with a **100% success rate**.

---

## 2. API Endpoints Specification

### A. System Metadata & Metrics
| Method | Endpoint | Description | Sample Output |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Serves interactive Leaflet web dashboard | HTML + CSS + JS |
| `GET` | `/api/stats` | Corridor graph statistics & DB counts | `{"nodes": 45518, "directed_edges": 84908, "fuel_stations": 240, ...}` |
| `GET` | `/api/vehicles` | Registered vehicle fleet with specs | `[{"make_model": "Maruti Swift VXi", "tank_capacity_l": 37.0, ...}]` |
| `GET` | `/api/places` | Pre-indexed corridor highway landmarks | `[{"id": "poonamallee", "lat": 13.0474, "lon": 80.0937}, ...]` |

### B. GeoJSON Spatial Layers
| Method | Endpoint | Source Table | Features Returned |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/layers/blackspots` | `BLACKSPOT` | 10 MoRTH/NHAI verified fatal blackspots with accident years and spatial coordinates |
| `GET` | `/api/layers/fuel-stations` | `FUEL_STATION` | 240+ corridor fuel pumps with brand names and highway snap distance |
| `GET` | `/api/layers/weather` | `WEATHER_OBS` | Live Open-Meteo observation grid with temperature, rain (mm), wind, and visibility |

### C. Routing & Decision Support
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/route` | Computes unconstrained multi-objective path (`fastest`, `shortest`, `safest`). Supports blackspot avoidance. |
| `POST` | `/api/fuel-plan` | Solves the **Gas Station Problem** along the corridor under initial fuel, tank capacity, mileage, and reserve limits. Persists to `TRIP`, `ROUTE_PLAN`, and `ROUTE_PLAN_STOP`. |
| `POST` | `/api/trip/<id>/reroute` | Executes **dynamic mid-trip rerouting** upon low fuel, incident, or closure triggers. Persists to `ROUTE_PLAN` and `REROUTE_EVENT` within an atomic MySQL transaction. |
| `POST` | `/api/trip/<id>/ping` | Records real-time GPS telemetry to `GPS_PING`. |
| `POST` | `/api/reports` | Records crowdsourced road hazard reports to `USER_REPORT`. |
| `GET` | `/api/trips/<id>` | Retrieves complete trip audit history, route plans, refuel stops, and reroute events. |

---

## 3. Frontend Architecture & Features (`web/templates/index.html`)

- **Interactive Leaflet.js Canvas**:
  - Dark Matter tiles with high-contrast road overlays.
  - Emerald green / indigo route polylines with turn-by-turn navigation.
  - Golden pulsing pins highlighting scheduled **Refuel Stops** showing fuel volume to add and total INR cost.
  - Red hazard shields for MoRTH fatal blackspots.
  - Cyan thermometer badges for live Open-Meteo weather stations.
- **Trip Configuration Sidebar**:
  - Origin / Destination preset selectors and coordinate pickers.
  - Vehicle Profile selector (Swift, Verna, City) with live tank capacity and mileage pill badges.
  - Fuel Sliders for Initial Tank Fuel ($1.0\text{ L}$ to full capacity) and Safety Reserve ($1.0\text{ L}$ to $10.0\text{ L}$).
  - Multi-objective selector (`Fastest`, `Safest`, `Shortest`) and Blackspot Avoidance checkbox.
- **Dynamic Simulation Controls**:
  - **"Simulate Low Fuel (2.0 L left)"**: Triggers dynamic mid-trip reroute event on the active journey.
  - Renders an amber dashed diversion polyline on the map leading directly to the newly scheduled refuel pump.
  - Updates the Results Drawer with an animated **Reroute Event Banner** comparing old vs. new route plan metrics.
- **Crowdsourced Hazard Reporting Modal**:
  - Allows drivers to log potholes, accidents, waterlogging, or closures directly into `USER_REPORT`.

---

## 4. Verification Suite Results (34 / 34 Tests Passed)

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.7.0 -- C:\TravelDB2\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\TravelDB2
collecting ... collected 34 items

tests/test_environment.py::test_imports PASSED                           [  2%]
tests/test_environment.py::test_project_structure PASSED                 [  5%]
tests/test_environment.py::test_sql_migration_syntax PASSED              [  8%]
tests/test_environment.py::test_database_loaded_entities PASSED          [ 11%]
tests/test_phase2_ingestion.py::test_weather_live_ingestion PASSED       [ 14%]
tests/test_phase2_ingestion.py::test_traffic_flow_fixture_processing PASSED [ 17%]
tests/test_phase2_ingestion.py::test_incident_fixture_processing_and_deduplication PASSED [ 20%]
tests/test_phase2_ingestion.py::test_graceful_degradation_without_api_keys PASSED [ 23%]
tests/test_phase3_static_and_risk.py::test_states_and_districts_loaded PASSED [ 26%]
tests/test_phase3_static_and_risk.py::test_road_edge_district_spatial_linkage PASSED [ 29%]
tests/test_phase3_static_and_risk.py::test_official_fuel_prices PASSED   [ 32%]
tests/test_phase3_static_and_risk.py::test_historical_accident_records PASSED [ 35%]
tests/test_phase3_static_and_risk.py::test_corridor_blackspots PASSED    [ 38%]
tests/test_phase3_static_and_risk.py::test_edge_risk_engine_outputs PASSED [ 41%]
tests/test_phase3_static_and_risk.py::test_views_and_stored_procedure PASSED [ 44%]
tests/test_phase4_router.py::test_network_topology_integrity PASSED      [ 47%]
tests/test_phase4_router.py::test_spatial_snapping_to_routable_component PASSED [ 50%]
tests/test_phase4_router.py::test_fastest_route_computation PASSED       [ 52%]
tests/test_phase4_router.py::test_shortest_vs_fastest PASSED             [ 55%]
tests/test_phase4_router.py::test_safest_route_objective PASSED          [ 58%]
tests/test_phase4_router.py::test_avoid_blackspots_flag PASSED           [ 61%]
tests/test_phase4_router.py::test_same_origin_and_destination PASSED     [ 64%]
tests/test_phase5_fuel_and_reroute.py::test_fuel_pricing_resolution PASSED [ 67%]
tests/test_phase5_fuel_and_reroute.py::test_feasible_journey_no_refuel_stops PASSED [ 70%]
tests/test_phase5_fuel_and_reroute.py::test_gas_station_problem_solver_constrained_fuel PASSED [ 73%]
tests/test_phase5_fuel_and_reroute.py::test_dynamic_reroute_event_lifecycle PASSED [ 76%]
tests/test_phase6_api.py::test_index_page_loads PASSED                   [ 79%]
tests/test_phase6_api.py::test_api_stats_and_metadata PASSED             [ 82%]
tests/test_phase6_api.py::test_api_spatial_layers PASSED                 [ 85%]
tests/test_phase6_api.py::test_api_multi_objective_route PASSED          [ 88%]
tests/test_phase6_api.py::test_api_fuel_planning_ample_fuel PASSED       [ 91%]
tests/test_phase6_api.py::test_api_fuel_planning_constrained_fuel PASSED [ 94%]
tests/test_phase6_api.py::test_api_dynamic_reroute_lifecycle PASSED      [ 97%]
tests/test_phase6_api.py::test_api_hazard_reporting_and_telemetry_ping PASSED [100%]

================== 34 passed, 1 warning in 76.83s (0:01:16) ===================
```
