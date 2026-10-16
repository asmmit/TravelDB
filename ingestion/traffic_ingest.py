"""
Traffic Flow Ingestion Pipeline for TravelDB.
Polls TomTom Flow Segment Data API for corridor sample points in TRAFFIC_SAMPLE_POINT.
Computes congestion_index = 1 - currentSpeed / freeFlowSpeed.
Records snapshots into TRAFFIC_FLOW_SNAPSHOT and logs execution into INGESTION_RUN.
Provides graceful fallback if API key is unconfigured or service is unavailable.
"""

import os
import sys
import time
import requests
from datetime import datetime

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json"

def process_traffic_flow_payload(sample_point_id, payload, cursor, source='tomtom'):
    """
    Parses a single flow segment response and inserts a snapshot row.
    Returns (True, snapshot_id) or (False, error).
    """
    flow = payload.get("flowSegmentData", {})
    if not flow:
        return False, "Missing flowSegmentData key"

    curr_speed = float(flow.get("currentSpeed", 0.0))
    free_speed = float(flow.get("freeFlowSpeed", curr_speed or 60.0))
    confidence = float(flow.get("confidence", 1.0))

    # Congestion index calculation: 0.0 = completely free flow, 1.0 = gridlock
    if free_speed > 0:
        congestion_index = max(0.0, min(1.0, 1.0 - (curr_speed / free_speed)))
    else:
        congestion_index = 0.0

    snapshot_sql = """
        INSERT INTO TRAFFIC_FLOW_SNAPSHOT (
            sample_point_id, ts, current_speed, free_flow_speed, congestion_index, confidence, source
        ) VALUES (
            %s, NOW(), %s, %s, %s, %s, %s
        );
    """
    cursor.execute(snapshot_sql, (
        sample_point_id,
        curr_speed,
        free_speed,
        round(congestion_index, 3),
        confidence,
        source
    ))
    return True, cursor.lastrowid

def poll_traffic_flow():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Traffic Flow Ingestion...")
    t_start = datetime.now()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        INSERT INTO INGESTION_RUN (source, started, status)
        VALUES ('tomtom_traffic_flow', %s, 'running');
    """, (t_start,))
    conn.commit()
    run_id = cursor.lastrowid

    # Check for valid API key
    if not TOMTOM_API_KEY or TOMTOM_API_KEY.strip() == "your_tomtom_api_key_here":
        msg = "TOMTOM_API_KEY is not configured in .env. Live traffic flow is inactive. Falling back to static road speed limits."
        print(f"[WARN] {msg}")
        cursor.execute("""
            UPDATE INGESTION_RUN
            SET finished=%s, status='failed', error_message=%s
            WHERE run_id=%s;
        """, (datetime.now(), msg, run_id))
        conn.commit()
        cursor.close()
        conn.close()
        return False

    # Retrieve active sample points
    cursor.execute("""
        SELECT sample_point_id, ST_X(geom) AS lon, ST_Y(geom) AS lat, corridor_name
        FROM TRAFFIC_SAMPLE_POINT;
    """)
    sample_points = cursor.fetchall()
    print(f"[+] Querying live flow for {len(sample_points)} corridor sample points...")

    success_count = 0
    fail_count = 0

    for pt in sample_points:
        params = {
            "point": f"{pt['lat']},{pt['lon']}",
            "key": TOMTOM_API_KEY
        }
        try:
            resp = requests.get(TOMTOM_FLOW_URL, params=params, timeout=8)
            if resp.status_code == 200:
                ok, res = process_traffic_flow_payload(pt['sample_point_id'], resp.json(), cursor)
                if ok:
                    success_count += 1
            else:
                fail_count += 1
            time.sleep(0.2) # Rate limiting: 5 QPS limit
        except Exception as e:
            fail_count += 1

    conn.commit()
    cursor.execute("""
        UPDATE INGESTION_RUN
        SET finished=%s, status='success', rows_in=%s
        WHERE run_id=%s;
    """, (datetime.now(), success_count, run_id))
    conn.commit()

    print(f"[OK] Traffic flow poll finished: {success_count} snapshots recorded ({fail_count} failed).")
    cursor.close()
    conn.close()
    return True

if __name__ == "__main__":
    poll_traffic_flow()
