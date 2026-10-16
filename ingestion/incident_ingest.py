"""
Live Incident Ingestion Pipeline for TravelDB.
Polls TomTom Incident Details API for the corridor bounding box.
Deduplicates incidents by (source, source_incident_id) and manages lifecycle (first_seen, last_seen, is_active).
Snaps active incidents to impacted ROAD_EDGE segments and logs to INGESTION_RUN.
Provides graceful fallback if API key is unconfigured.
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
TOMTOM_INCIDENT_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"

# Chennai to Vellore bounding box
CORRIDOR_BBOX = "79.393,12.766,80.263,13.198"

CATEGORY_MAP = {
    0: "other",
    1: "accident",
    2: "flooding",
    3: "hazard",
    4: "jam",
    5: "broken_down_vehicle",
    6: "road_closed",
    7: "road_closed",
    8: "road_works",
    9: "hazard",
    10: "other",
    11: "hazard"
}

SEVERITY_MAP = {
    0: "minor",
    1: "minor",
    2: "moderate",
    3: "major",
    4: "critical"
}

def process_incidents_payload(incidents_list, cursor, source='tomtom'):
    """
    Ingests and deduplicates incident objects from feed into INCIDENT and INCIDENT_EDGE.
    Returns (inserted_count, updated_count).
    """
    if not incidents_list:
        return 0, 0

    seen_source_ids = []
    inserted_count = 0
    updated_count = 0

    for inc in incidents_list:
        source_id = str(inc.get("id") or inc.get("properties", {}).get("id"))
        if not source_id:
            continue
        seen_source_ids.append(source_id)

        props = inc.get("properties", {})
        geom = inc.get("geometry", {})
        coords = geom.get("coordinates", [])

        if not coords or len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        wkt_geom = f"POINT({lon} {lat})"

        # Determine category and severity
        icon_cat = props.get("iconCategory", 0)
        category = CATEGORY_MAP.get(icon_cat, "hazard")
        
        delay_mag = props.get("magnitudeOfDelay", 1)
        severity = SEVERITY_MAP.get(delay_mag, "moderate")

        events = props.get("events", [])
        desc = events[0].get("description") if events else props.get("from", "Traffic incident reported")

        def parse_iso_ts(ts_str):
            if not ts_str:
                return None
            try:
                clean = ts_str.replace("Z", "+00:00")
                return datetime.fromisoformat(clean).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return None

        start_ts = parse_iso_ts(props.get("startTime"))
        end_ts = parse_iso_ts(props.get("endTime"))

        # Upsert into INCIDENT
        upsert_sql = """
            INSERT INTO INCIDENT (
                source, source_incident_id, category, severity, description,
                geom, start_ts, end_ts, first_seen, last_seen, is_active
            ) VALUES (
                %s, %s, %s, %s, %s,
                ST_GeomFromText(%s, 4326), %s, %s, NOW(), NOW(), TRUE
            ) ON DUPLICATE KEY UPDATE
                category = VALUES(category),
                severity = VALUES(severity),
                description = VALUES(description),
                last_seen = NOW(),
                is_active = TRUE;
        """
        cursor.execute(upsert_sql, (
            source, source_id, category, severity, desc,
            wkt_geom, start_ts, end_ts
        ))

        # Retrieve incident_id
        cursor.execute("SELECT incident_id FROM INCIDENT WHERE source=%s AND source_incident_id=%s;", (source, source_id))
        inc_row = cursor.fetchone()
        if inc_row:
            inc_id = inc_row[0] if isinstance(inc_row, tuple) else inc_row['incident_id']

            # Spatial snap: Find nearest road edge within 500 meters and associate in INCIDENT_EDGE
            edge_snap_sql = """
                INSERT IGNORE INTO INCIDENT_EDGE (incident_id, edge_id)
                SELECT %s, edge_id
                FROM ROAD_EDGE
                WHERE ST_Distance(geom, ST_GeomFromText(%s, 4326)) <= 500
                ORDER BY ST_Distance(geom, ST_GeomFromText(%s, 4326)) ASC
                LIMIT 2;
            """
            cursor.execute(edge_snap_sql, (inc_id, wkt_geom, wkt_geom))
            inserted_count += 1

    # Mark incidents no longer present in feed as inactive
    if seen_source_ids:
        placeholders = ', '.join(['%s'] * len(seen_source_ids))
        cursor.execute(f"""
            UPDATE INCIDENT
            SET is_active = FALSE, end_ts = COALESCE(end_ts, NOW())
            WHERE source = %s AND source_incident_id NOT IN ({placeholders}) AND is_active = TRUE;
        """, [source] + seen_source_ids)

    return inserted_count, updated_count

def poll_incidents():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Incident Ingestion...")
    t_start = datetime.now()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        INSERT INTO INGESTION_RUN (source, started, status)
        VALUES ('tomtom_incidents', %s, 'running');
    """, (t_start,))
    conn.commit()
    run_id = cursor.lastrowid

    if not TOMTOM_API_KEY or TOMTOM_API_KEY.strip() == "your_tomtom_api_key_here":
        msg = "TOMTOM_API_KEY is not configured in .env. Live incident feed is inactive. Falling back to static safety baseline."
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

    params = {
        "bbox": CORRIDOR_BBOX,
        "key": TOMTOM_API_KEY,
        "fields": "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code},startTime,endTime,from,to,length,delay}}}"
    }

    try:
        resp = requests.get(TOMTOM_INCIDENT_URL, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            incidents_list = data.get("incidents", [])
            print(f"[+] Retrieved {len(incidents_list)} live incidents from TomTom feed.")
            ins, upd = process_incidents_payload(incidents_list, cursor)
            conn.commit()

            cursor.execute("""
                UPDATE INGESTION_RUN
                SET finished=%s, status='success', rows_in=%s
                WHERE run_id=%s;
            """, (datetime.now(), ins, run_id))
            conn.commit()
            print(f"[OK] Ingested and deduplicated {ins} incidents successfully.")
            res = True
        else:
            msg = f"TomTom API returned HTTP {resp.status_code}: {resp.text[:200]}"
            print(f"[!] {msg}")
            cursor.execute("""
                UPDATE INGESTION_RUN
                SET finished=%s, status='failed', error_message=%s
                WHERE run_id=%s;
            """, (datetime.now(), msg, run_id))
            conn.commit()
            res = False
    except Exception as e:
        msg = str(e)
        print(f"[ERROR] Incident ingestion failed: {e}")
        cursor.execute("""
            UPDATE INGESTION_RUN
            SET finished=%s, status='failed', error_message=%s
            WHERE run_id=%s;
        """, (datetime.now(), msg[:500], run_id))
        conn.commit()
        res = False

    cursor.close()
    conn.close()
    return res

if __name__ == "__main__":
    poll_incidents()
