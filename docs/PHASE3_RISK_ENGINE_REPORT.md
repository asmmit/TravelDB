# TravelDB Phase 3: Static Layers, Fuel Pricing & Risk Engine Report

## 1. Executive Summary
Phase 3 implements the foundational safety, administrative, and economic layers for TravelDB across the Chennai–Vellore corridor (NH 48 / AH 45). The system integrates official administrative district boundary polygons, retail fuel prices, historical road accident statistics, and national highway blackspots from MoRTH. These layers feed the **Edge Risk Engine v1**, which scores all 59,468 road network edges and stores explainable JSON breakdowns directly in MySQL 8.0, backed by database Views and a Stored Procedure.

---

## 2. Ingested Data Layers & Official Sources

### A. Administrative Boundaries (`STATE` & `DISTRICT`)
- **States**: Tamil Nadu (`TN`) and Karnataka (`KA`).
- **Corridor Districts**: Geocoded directly from OpenStreetMap / Nominatim administrative boundary polygons (`SRID 4326`):
  1. Chennai (`district_id=1`, `POLYGON`)
  2. Tiruvallur (`district_id=2`, `POLYGON`)
  3. Kanchipuram (`district_id=3`, `POLYGON`)
  4. Ranipet (`district_id=4`, `POLYGON`)
  5. Vellore (`district_id=5`, `POLYGON`)
- **Spatial Containment Mapping**:
  - Utilizing an `STRtree` spatial index on the district polygons, 52,133 of 59,468 road edges (87.7%) were assigned their authoritative `district_id` in MySQL.
  - Distribution: Chennai: 19,925 edges; Kanchipuram: 13,150 edges; Tiruvallur: 12,372 edges; Ranipet: 6,686 edges.

### B. Retail Fuel Prices (`FUEL_PRICE`)
- **Source**: Indian Oil Corporation Limited (IOCL) official Daily Retail Selling Price (RSP).
- **As of Date**: Active baseline (October 2026).
- **Values Stored**:
  - **Tamil Nadu (Chennai RSP)**:
    - Petrol: ₹100.75 / litre
    - Diesel: ₹92.34 / litre
    - CNG: ₹85.50 / kg
  - **Karnataka (Bengaluru RSP)**:
    - Petrol: ₹102.86 / litre
    - Diesel: ₹88.94 / litre
    - CNG: ₹83.00 / kg

### C. MoRTH Road Accident Statistics (`ACCIDENT_HISTORICAL`)
- **Source**: "Road Accidents in India 2022" (Ministry of Road Transport and Highways, Govt of India) & Tamil Nadu State Crime Records Bureau (SCRB).
- **Breakdown**: 15 records across all 5 corridor districts classified by road category (`National Highway`, `State Highway`, `Other Roads`) with counts of accidents, fatalities, and injuries.
- **District Accident Densities**:
  - Chennai: 4,047 accidents (Urban density)
  - Tiruvallur: 1,850 accidents
  - Kanchipuram: 1,610 accidents
  - Vellore: 1,370 accidents
  - Ranipet: 1,095 accidents

### D. Verified Highway Blackspots (`BLACKSPOT`)
- **Source**: MoRTH / NHAI National Blackspot Study 2021–2023 & Tamil Nadu Road Safety Action Plan.
- **Spatial Storage**: `POINT SRID 4326` with `SPATIAL INDEX idx_blackspot_geom`.
- **Corridor Blackspots Mapped along NH 48**:
  1. Poonamallee Bypass Junction (`NH 48 KM 18.2` - `13.0474, 80.0937`)
  2. Chembarambakkam Junction (`NH 48 KM 27.6` - `13.0135, 80.0162`)
  3. Sriperumbudur Toll Plaza / Maduramangalam X-Road (`NH 48 KM 37.4` - `12.9675, 79.9436`)
  4. Mambakkam / Sunguvarchatram Junction (`NH 48 KM 51.2` - `12.9238, 79.8245`)
  5. Baluchetty Chatram Junction, Kanchipuram (`NH 48 KM 72.8` - `12.8719, 79.6241`)
  6. Damal Junction (`NH 48 KM 81.5` - `12.8942, 79.5246`)
  7. Kaveripakkam Intersection (`NH 48 KM 98.4` - `12.9056, 79.4623`)
  8. Walajapet Toll Plaza / Ranipet Bypass (`NH 48 KM 115.1` - `12.9272, 79.3789`)
  9. Arcot Bridge Junction (`NH 48 / SH 4` - `12.9270, 79.3330`)
  10. Vellore Green Circle / Collectorate Junction (`NH 48 KM 138.5` - `12.9165, 79.1325`)

---

## 3. Edge Risk Engine v1 (`ingestion/risk_engine.py`)

### Mathematical Formulation
The composite safety risk score $R(e) \in [0.00, 100.00]$ is computed as:
$$R(e) = \min\Big(100.0, \; \text{BaseRisk}(e) + \text{BlackspotPenalty}(e) + \text{WeatherPenalty}(e) + \text{DistrictAccidentFactor}(e)\Big)$$

Where:
1. **$\text{BaseRisk}(e)$**:
   - `motorway`: 10.0 | `trunk` (NH): 15.0 | `primary` (SH): 22.0 | `secondary`: 28.0 | `tertiary`/`unclassified`: 32.0–35.0.
2. **$\text{BlackspotPenalty}(e)$**:
   - If distance $d \le 500\text{ meters}$ to the nearest MoRTH blackspot:
     $$\text{BlackspotPenalty} = 40.0 \times \left(1 - \frac{d}{500.0}\right)$$
   - If $d > 500\text{m}$, penalty is $0$.
3. **$\text{WeatherPenalty}(e)$**:
   - Sampled from the nearest live observation in `WEATHER_OBS`:
     - Rain: $+2.0$ per mm of precipitation (max $+20.0$).
     - Fog/Visibility: if visibility $V < 3000\text{m}$, $+20.0 \times (1 - \frac{V}{3000})$.
     - Wind: if wind speed $> 30\text{ km/h}$, $+5.0$.
4. **$\text{DistrictAccidentFactor}(e)$**:
   - Derived from `ACCIDENT_HISTORICAL`:
     $$\text{DistrictFactor} = \left(\frac{\text{District Accidents}}{\text{Max District Accidents}}\right) \times 15.0$$

### Performance & Summary Statistics
- **Execution Time**: 7.43 seconds computation + 2.77 seconds batch database upsert for all 59,468 edges.
- **Total Edges Scored**: 59,468
- **Minimum Score**: 15.97
- **Average Score**: 32.51
- **Maximum Score**: 65.29
- **High Risk Edges ($\ge 60$)**: 16 segments (located within 100 meters of fatal blackspots, such as the Sriperumbudur Toll Plaza / Maduramangalam intersection on SH 57 / NH 48).
- **Medium Risk Edges ($[40, 60)$)**: 9,233 segments.
- **Low Risk Edges ($< 40$)**: 50,219 segments.

---

## 4. MySQL 8.0 Views & Stored Procedures (Migration 002)

### A. View: `v_high_risk_corridor_edges`
Extracts and casts JSON component attributes for fast SQL inspection:
```sql
CREATE OR REPLACE VIEW v_high_risk_corridor_edges AS
SELECT 
    r.edge_id, e.road_name, e.ref, e.road_type, e.length_m, e.speed_kph, r.risk_score,
    r.components->>'$.district_name' AS district_name,
    r.components->>'$.nearest_blackspot' AS nearest_blackspot,
    CAST(r.components->>'$.blackspot_dist_m' AS DECIMAL(8,1)) AS blackspot_dist_m,
    CAST(r.components->>'$.blackspot_penalty' AS DECIMAL(5,2)) AS blackspot_penalty,
    CAST(r.components->>'$.weather_penalty' AS DECIMAL(5,2)) AS weather_penalty,
    r.computed_at
FROM EDGE_RISK r
JOIN ROAD_EDGE e ON r.edge_id = e.edge_id
WHERE r.risk_score >= 40.00;
```

### B. View: `v_fuel_price_summary`
Summarizes retail fuel prices across states for pricing comparisons and trip budget estimations.

### C. Stored Procedure: `sp_get_corridor_risk_summary()`
Executes on-demand server-side risk aggregation returning edge counts partitioned into high, medium, and low tiers alongside min/avg/max scores.

---

## 5. Verification & Automated Test Results
All 7 Phase 3 tests passed cleanly in 0.55s, bringing the total passing project test count to **15 / 15**:
```text
tests/test_phase3_static_and_risk.py::test_states_and_districts_loaded PASSED [ 14%]
tests/test_phase3_static_and_risk.py::test_road_edge_district_spatial_linkage PASSED [ 28%]
tests/test_phase3_static_and_risk.py::test_official_fuel_prices PASSED   [ 42%]
tests/test_phase3_static_and_risk.py::test_historical_accident_records PASSED [ 57%]
tests/test_phase3_static_and_risk.py::test_corridor_blackspots PASSED    [ 71%]
tests/test_phase3_static_and_risk.py::test_edge_risk_engine_outputs PASSED [ 85%]
tests/test_phase3_static_and_risk.py::test_views_and_stored_procedure PASSED [100%]
```
