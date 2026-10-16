# TravelDB: Fuel-Aware, Live-Data Travel Decision Support System for South India

A DBMS Course Project delivering a real, production-grade decision support platform for fuel-constrained navigation across South India (initial focus: Chennai – Vellore – Bengaluru corridor, NH 48 / AH 45).

---

## 1. Key Highlights
- **Real Road Graph (45,518 nodes, 84,908 directed edges)**: Extracted from OpenStreetMap (ODbL) into MySQL 8.0 with spatial point & linestring geometries (`SRID 4326`, `SPATIAL INDEX` R-Trees).
- **Giant Strongly Connected Component (89.1% coverage)**: Expanded two-way roads bidirectionally while strictly maintaining one-way dual carriageway highway semantics.
- **Sub-15ms In-Memory Execution**: `python-igraph` in-memory graph with $O(\log N)$ 2D KD-Tree spatial snapping directly into the giant SCC.
- **Fuel-Feasible Routing (Gas Station Problem Solver)**: Evaluates road friction ($\alpha_{\text{road\_type}}$) and weather drag ($\beta_{\text{weather}}$) per edge. When tank fuel is constrained, automatically identifies optimal refuel stops from 240+ verified pumps to prevent vehicle stranding.
- **Dynamic Mid-Trip Rerouting**: Evaluates live alerts (`low_fuel`, `incident`, `closure`) and executes atomic re-optimization logged to `REROUTE_EVENT` and `ROUTE_PLAN` within an ACID MySQL transaction.
- **Interactive Leaflet.js Web Dashboard**: Modern dark-mode interface with live corridor metrics, vehicle profile selector, fuel sliders, pulsing refuel stop pins, and MoRTH fatal blackspot overlays.
- **100% Test Pass Rate**: 34 unit, integration, and API tests passing cleanly.

---

## 2. Directory Structure

```text
C:\TravelDB2\
├── .env                      # Local configuration & credentials (gitignored)
├── README.md                 # Project architecture & setup
├── data\raw\                 # Extracted GeoJSON corridor datasets
├── docs\
│   ├── DATA_SOURCES.md       # Data Source Register & ToS compliance
│   ├── RELATIONAL_SCHEMA.md  # Functional dependencies & normal form proofs
│   ├── VIVA_QA.md            # Comprehensive defense sheet for viva (Q1 - Q15)
│   ├── DATA_QUALITY_REPORT_P1.md # Network & station coverage report
│   ├── PHASE2_INGESTION_REPORT.md# Live feeds & scheduler report
│   ├── PHASE3_RISK_ENGINE_REPORT.md # Risk scores & blackspots report
│   ├── PHASE4_ROUTING_REPORT.md  # Multi-objective router benchmarks
│   ├── PHASE5_FUEL_ROUTING_REPORT.md # Gas Station Problem solver report
│   └── PHASE6_UI_API_REPORT.md   # Flask REST API & Web Dashboard report
├── database\
│   ├── db_connection.py      # Thread-safe MySQL connection pool
│   ├── migrate.py            # Numbered SQL migration runner
│   ├── seed_demo_users.py    # Demo driver accounts & vehicle profiles
│   └── migrations\
│       ├── 001_initial_schema.sql # Core tables & spatial indexes
│       └── 002_risk_views_and_procedures.sql # Stored procedure & views
├── ingestion\
│   ├── osm_extractor.py      # Bounded corridor extraction (OSMnx)
│   ├── osm_loader.py         # MySQL loader with KDTree spatial snapping
│   ├── weather_ingest.py     # Live Open-Meteo weather pipeline
│   ├── tomtom_traffic_ingest.py # Live traffic flow & incidents pipeline
│   ├── static_layers_ingest.py  # Boundaries, blackspots, fuel prices
│   ├── risk_engine.py        # Computes EDGE_RISK v1 scores
│   └── pipeline_scheduler.py # Master ingestion orchestrator
├── engine\
│   ├── graph_loader.py       # In-memory igraph & 2D KD-Tree spatial index
│   ├── router.py             # Multi-objective Dijkstra router (fastest, shortest, safest)
│   ├── fuel_router.py        # 2-Stage Gas Station Problem solver & fuel physics
│   └── reroute.py            # Dynamic mid-trip reroute engine (ACID logging)
├── web\
│   ├── app.py                # Flask 3.1 REST API server
│   ├── templates\index.html  # Modern Leaflet.js interactive dashboard
│   └── static\
│       ├── css\style.css     # Dark glassmorphic styling
│       └── js\app.js         # Map rendering & simulation logic
└── tests\                    # Automated pytest test suite (34 tests)
    ├── test_environment.py   # Phase 0 & 1 environment tests (4 passed)
    ├── test_phase2_ingestion.py # Ingestion & feed degradation tests (4 passed)
    ├── test_phase3_static_and_risk.py # Static layers & risk engine tests (7 passed)
    ├── test_phase4_router.py # Graph topology & router tests (7 passed)
    ├── test_phase5_fuel_and_reroute.py # Fuel planning & reroute tests (4 passed)
    └── test_phase6_api.py    # Flask REST API & web dashboard tests (8 passed)
```

---

## 3. How to Run the Web Application

```powershell
# 1. Activate Virtual Environment
cd C:\TravelDB2
.\venv\Scripts\activate

# 2. Start the Flask Server
.\venv\Scripts\python.exe web\app.py

# 3. Open in Browser
# Navigate to: http://127.0.0.1:5000
```

---

## 4. How to Run the Automated Test Suite

```powershell
# Run the entire test suite (all 34 tests)
.\venv\Scripts\python.exe -m pytest -v

# Run individual phase test suites
.\venv\Scripts\python.exe -m pytest -v tests\test_phase6_api.py
.\venv\Scripts\python.exe -m pytest -v tests\test_phase5_fuel_and_reroute.py
```
