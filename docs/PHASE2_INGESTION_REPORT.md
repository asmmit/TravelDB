# TravelDB Phase 2: Live Ingestion Pipeline Report

## 1. Executive Summary
Phase 2 establishes the dynamic data ingestion layer for TravelDB across the Chennai–Vellore corridor (NH 48 / AH 45). The system integrates live meteorological feeds (Open-Meteo), traffic flow, and incident monitoring with automated audit logging, spatial edge mapping, and 100% resilient graceful degradation when third-party API credentials are not present.

---

## 2. Ingestion Modules & Architecture

### A. Weather Ingestion (`ingestion/weather_ingest.py`)
- **Source**: Open-Meteo Weather API (`https://api.open-meteo.com/v1/forecast`).
- **Authentication**: Free tier, no API key required.
- **Coverage Nodes**: 7 strategic corridor stations:
  1. Chennai (`13.0827, 80.2707`)
  2. Poonamallee (`13.0474, 80.0937`)
  3. Sriperumbudur (`12.9675, 79.9436`)
  4. Kanchipuram (`12.8342, 79.7036`)
  5. Walajapet (`12.9272, 79.3789`)
  6. Ranipet (`12.9270, 79.3330`)
  7. Vellore (`12.9165, 79.1325`)
- **Logged Metrics**: Temperature (°C), Precipitation (mm), Visibility (m), Wind Speed (km/h), WMO Weather Code.
- **Target Table**: `WEATHER_OBS` (`obs_id`, `station_name`, `geom`, `temp_c`, `precipitation_mm`, `visibility_m`, `wind_speed_kmh`, `weather_code`, `observed_at`).

### B. Traffic Flow Ingestion (`ingestion/traffic_ingest.py`)
- **Source**: TomTom Traffic Flow API (v4).
- **Sampling Mesh**: 41 corridor sample points (`TRAFFIC_SAMPLE_POINT`) spaced across NH 48.
- **Derived Metrics**:
  - Congestion Index: $C = \max\left(0, 1 - \frac{\text{current\_speed}}{\text{free\_flow\_speed}}\right)$
  - Speed Ratio: $\frac{\text{current\_speed}}{\text{free\_flow\_speed}}$
- **Target Table**: `TRAFFIC_FLOW_OBS` (`flow_id`, `sample_point_id`, `current_speed_kmh`, `free_flow_speed_kmh`, `congestion_index`, `observed_at`).
- **ToS Compliance & Ephemerality**: In compliance with TomTom and HERE Developer Terms of Service, raw historical flow records are not archived for AI training (M2 disabled). Live flow acts strictly as an operational cache for real-time routing penalty overlays.

### C. Incident Ingestion & Spatial Snapping (`ingestion/incident_ingest.py`)
- **Source**: TomTom Traffic Incidents API.
- **Deduplication**: Composite unique identifier `(source, source_incident_id)`.
- **Lifecycle Tracking**: Updates `last_seen` timestamp and toggles `is_active = FALSE` when an incident clears from subsequent polling runs.
- **Spatial Edge Snapping**:
  ```sql
  SELECT edge_id, ST_Distance(geom, ST_GeomFromText(%s, 4326)) AS dist_m
  FROM ROAD_EDGE
  WHERE ST_Distance(geom, ST_GeomFromText(%s, 4326)) <= 500
  ORDER BY dist_m ASC
  LIMIT 1;
  ```
- **Target Tables**: `INCIDENT` (`incident_id`, `source`, `source_incident_id`, `incident_type`, `severity`, `description`, `geom`, `delay_sec`, `start_time`, `end_time`, `is_active`, `first_seen`, `last_seen`) and `EDGE_INCIDENT` junction table (`edge_id`, `incident_id`, `distance_to_edge_m`).

### D. Audit Logging (`INGESTION_RUN`)
Every ingestion execution across weather, traffic, and incidents registers an atomic entry in the `INGESTION_RUN` table:
- `source`: Service identifier (`open_meteo_weather`, `tomtom_traffic_flow`, `tomtom_incidents`)
- `started`: Cycle start timestamp
- `finished`: Cycle finish timestamp
- `status`: `'running'` -> `'success'` or `'failed'`
- `rows_in`: Number of records written to the database
- `error_message`: Full diagnostic message upon failure or graceful fallback notice

---

## 3. Graceful Degradation Strategy
The pipeline guarantees zero crashes and high availability under missing or expired credentials:
1. When `TOMTOM_API_KEY` is empty or missing in `.env`, the pipeline gracefully logs a warning to stderr and records a diagnostic entry in `INGESTION_RUN`.
2. The system automatically falls back to:
   - **Static Edge Speeds**: Stored in `ROAD_EDGE.speed_limit` (computed from OSM highway classification: motorway 100 km/h, trunk 80 km/h, primary 65 km/h, etc.).
   - **Baseline Risk Weights**: Preserved from historical black-spots and MoRTH safety baselines.

---

## 4. Test Suite Verification
All 4 dedicated Phase 2 tests passed with zero failures:
1. `test_weather_live_ingestion`: Hits live Open-Meteo endpoint, validates 7 records stored in `WEATHER_OBS`, verifies non-null temperatures and valid visibility meters.
2. `test_traffic_flow_fixture_processing`: Validates ingestion of TomTom flow response, congestion index math, and database insertions using real API sample fixture.
3. `test_incident_fixture_processing_and_deduplication`: Verifies deduplication logic, spatial edge attachment, and lifecycle updates using real TomTom incident fixture.
4. `test_graceful_degradation_without_api_keys`: Ensures missing API keys log cleanly without raising exceptions or terminating background scheduler tasks.
