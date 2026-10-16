"""
Risk Engine for TravelDB (Phase 3).
Computes composite safety risk scores (0 to 100) for road edges along the corridor.
Synthesizes:
1. Road Type Baseline Hazard (motorway, trunk, primary, secondary, tertiary)
2. MoRTH/NHAI Blackspot Proximity (geodesic distance via cKDTree)
3. Live Weather Hazards (precipitation, low visibility, high wind from WEATHER_OBS)
4. Historical Accident Density (district-level statistics from ACCIDENT_HISTORICAL)
Stores scores and detailed JSON components into EDGE_RISK table.
"""

import os
import sys
import json
import logging
import time
from datetime import datetime
import numpy as np
from scipy.spatial import cKDTree

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("risk_engine")

# Base risk values by road classification
ROAD_TYPE_BASE_RISK = {
    "motorway": 10.0,
    "motorway_link": 12.0,
    "trunk": 15.0,
    "trunk_link": 18.0,
    "primary": 22.0,
    "primary_link": 24.0,
    "secondary": 28.0,
    "secondary_link": 30.0,
    "tertiary": 32.0,
    "tertiary_link": 34.0,
    "unclassified": 35.0,
    "residential": 30.0,
    "service": 25.0
}
DEFAULT_BASE_RISK = 25.0

# Conversion: 1 degree latitude ~= 111,000 meters; 1 degree longitude at lat 13 ~= 108,000 meters
METERS_PER_DEG_LAT = 110900.0
METERS_PER_DEG_LON = 108300.0


def fast_approx_distance_meters(lon1, lat1, lon2, lat2):
    """Fast Euclidean approximation in meters for small local distances (~13 deg N)."""
    dx = (lon1 - lon2) * METERS_PER_DEG_LON
    dy = (lat1 - lat2) * METERS_PER_DEG_LAT
    return np.sqrt(dx * dx + dy * dy)


def load_blackspots(conn):
    """Loads all official blackspots with coordinates."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT blackspot_id, name, ST_X(geom) as lon, ST_Y(geom) as lat, year
        FROM BLACKSPOT;
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def load_latest_weather(conn):
    """Loads latest weather observations for corridor checkpoints."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT w.obs_id, ST_X(w.grid_point) as lon, ST_Y(w.grid_point) as lat,
               w.precip_mm, w.visibility_m, w.wind_kph, w.temp_c, w.ts
        FROM WEATHER_OBS w
        INNER JOIN (
            SELECT ST_AsText(grid_point) as pt_wkt, MAX(obs_id) as max_id
            FROM WEATHER_OBS
            GROUP BY ST_AsText(grid_point)
        ) latest ON w.obs_id = latest.max_id;
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def load_district_accident_rates(conn):
    """Loads district accident factor normalized to [0, 15]."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT d.district_id, d.name, SUM(a.accidents) as total_accidents, SUM(a.fatalities) as total_fatalities
        FROM DISTRICT d
        LEFT JOIN ACCIDENT_HISTORICAL a ON d.district_id = a.district_id
        GROUP BY d.district_id, d.name;
    """)
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        return {}

    max_acc = float(max([r["total_accidents"] or 0 for r in rows] + [1]))
    rates = {}
    for r in rows:
        acc = float(r["total_accidents"] or 0)
        score = (acc / max_acc) * 15.0
        rates[r["district_id"]] = {
            "name": r["name"],
            "score": round(score, 2),
            "accidents": int(acc),
            "fatalities": int(r["total_fatalities"] or 0)
        }
    return rates


def compute_edge_risks(conn=None):
    """
    Main computation routine for EDGE_RISK scores.
    Evaluates all edges in ROAD_EDGE and persists risk scores and JSON components.
    """
    owns_conn = False
    if conn is None:
        conn = get_db_connection()
        owns_conn = True

    try:
        start_time = time.time()
        logger.info("Initializing Risk Engine calculation...")

        # 1. Load context layers
        blackspots = load_blackspots(conn)
        weather_stations = load_latest_weather(conn)
        district_factors = load_district_accident_rates(conn)

        logger.info(f"Loaded {len(blackspots)} blackspots, {len(weather_stations)} weather stations, {len(district_factors)} district profiles.")

        # Build KD-tree for blackspots (in projected meters)
        b_pts_proj = np.array([
            [b["lon"] * METERS_PER_DEG_LON, b["lat"] * METERS_PER_DEG_LAT]
            for b in blackspots
        ])
        b_tree = cKDTree(b_pts_proj) if len(blackspots) > 0 else None

        # Build KD-tree for weather stations (in projected meters)
        w_pts_proj = np.array([
            [w["lon"] * METERS_PER_DEG_LON, w["lat"] * METERS_PER_DEG_LAT]
            for w in weather_stations
        ])
        w_tree = cKDTree(w_pts_proj) if len(weather_stations) > 0 else None

        # 2. Fetch all road edges
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT edge_id, road_type, district_id,
                   ST_X(ST_StartPoint(geom)) as lon, ST_Y(ST_StartPoint(geom)) as lat
            FROM ROAD_EDGE;
        """)
        edges = cursor.fetchall()
        cursor.close()
        logger.info(f"Loaded {len(edges)} road edges. Calculating composite risk factors...")

        # Prepare edge coordinates in projected meters
        edge_coords_proj = np.array([
            [e["lon"] * METERS_PER_DEG_LON, e["lat"] * METERS_PER_DEG_LAT]
            for e in edges
        ])

        # Batch query nearest blackspots
        if b_tree is not None:
            b_dists, b_indices = b_tree.query(edge_coords_proj, k=1)
        else:
            b_dists, b_indices = np.full(len(edges), 99999.0), np.zeros(len(edges), dtype=int)

        # Batch query nearest weather stations
        if w_tree is not None:
            w_dists, w_indices = w_tree.query(edge_coords_proj, k=1)
        else:
            w_dists, w_indices = np.full(len(edges), 99999.0), np.zeros(len(edges), dtype=int)

        records_to_upsert = []

        for i, edge in enumerate(edges):
            # A. Base Road Type Risk
            rtype = edge["road_type"].lower() if edge["road_type"] else "unclassified"
            base_risk = ROAD_TYPE_BASE_RISK.get(rtype, DEFAULT_BASE_RISK)

            # B. Blackspot Proximity Penalty (within 500 meters)
            b_dist_m = float(b_dists[i])
            if b_dist_m <= 500.0:
                # Up to +40 points directly at the blackspot, tapering linearly to 0 at 500m
                b_penalty = round(40.0 * (1.0 - (b_dist_m / 500.0)), 2)
                matched_b = blackspots[b_indices[i]]
                b_name = matched_b["name"]
                b_id = matched_b["blackspot_id"]
            else:
                b_penalty = 0.0
                b_name = None
                b_id = None

            # C. Live Weather Hazard Penalty
            w_obs = weather_stations[w_indices[i]] if len(weather_stations) > 0 else None
            weather_penalty = 0.0
            station_name = None
            if w_obs:
                # Rain factor: +2.0 per mm, max 20.0
                precip = float(w_obs["precip_mm"] or 0.0)
                weather_penalty += min(20.0, precip * 2.0)
                # Visibility factor: under 3000m visibility adds up to +20.0
                vis = float(w_obs["visibility_m"] or 10000.0)
                if vis < 3000.0:
                    weather_penalty += 20.0 * (1.0 - (vis / 3000.0))
                # Wind factor: strong wind > 30 km/h adds +5.0
                wind = float(w_obs["wind_kph"] or 0.0)
                if wind > 30.0:
                    weather_penalty += 5.0
                weather_penalty = round(weather_penalty, 2)

            # D. Historical District Accident Factor
            dist_id = edge["district_id"]
            if dist_id in district_factors:
                d_info = district_factors[dist_id]
                d_factor = d_info["score"]
                d_name = d_info["name"]
            else:
                d_factor = 7.50  # Corridor average fallback
                d_name = "Corridor Average"

            # Composite Risk Score (bounded in [0.0, 100.0])
            total_risk = round(min(100.0, base_risk + b_penalty + weather_penalty + d_factor), 2)

            components = {
                "base_risk": base_risk,
                "road_type": rtype,
                "blackspot_penalty": b_penalty,
                "blackspot_id": b_id,
                "nearest_blackspot": b_name,
                "blackspot_dist_m": round(b_dist_m, 1) if b_dist_m <= 1000 else ">1000",
                "weather_penalty": weather_penalty,
                "weather_obs_id": w_obs["obs_id"] if w_obs else None,
                "district_factor": d_factor,
                "district_name": d_name
            }

            records_to_upsert.append((
                edge["edge_id"],
                total_risk,
                json.dumps(components)
            ))

        logger.info(f"Calculation complete in {time.time() - start_time:.2f}s. Upserting {len(records_to_upsert)} rows into EDGE_RISK...")

        # Batch upsert in chunks of 5000
        chunk_size = 5000
        upsert_cursor = conn.cursor()
        for i in range(0, len(records_to_upsert), chunk_size):
            chunk = records_to_upsert[i:i + chunk_size]
            upsert_cursor.executemany("""
                INSERT INTO EDGE_RISK (edge_id, risk_score, components)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    risk_score = VALUES(risk_score),
                    components = VALUES(components),
                    computed_at = CURRENT_TIMESTAMP;
            """, chunk)
            conn.commit()

        upsert_cursor.close()
        elapsed = time.time() - start_time
        logger.info(f"[+] Successfully computed and persisted EDGE_RISK for {len(records_to_upsert)} edges in {elapsed:.2f}s.")
        return len(records_to_upsert)

    finally:
        if owns_conn:
            conn.close()


def get_risk_summary():
    """Returns descriptive statistics of computed edge risk scores."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT
            COUNT(*) as total_edges,
            MIN(risk_score) as min_score,
            AVG(risk_score) as avg_score,
            MAX(risk_score) as max_score,
            SUM(CASE WHEN risk_score >= 60 THEN 1 ELSE 0 END) as high_risk_count,
            SUM(CASE WHEN risk_score >= 40 AND risk_score < 60 THEN 1 ELSE 0 END) as medium_risk_count,
            SUM(CASE WHEN risk_score < 40 THEN 1 ELSE 0 END) as low_risk_count
        FROM EDGE_RISK;
    """)
    summary = cursor.fetchone()
    cursor.close()
    conn.close()
    return summary


if __name__ == "__main__":
    compute_edge_risks()
    stats = get_risk_summary()
    print("\n=== EDGE RISK SUMMARY ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
