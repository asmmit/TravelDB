"""
Open-Meteo Weather Ingestion Pipeline for TravelDB.
Polls hourly/current weather metrics along corridor grid points (Chennai to Vellore).
Stores observations in WEATHER_OBS and logs execution in INGESTION_RUN.
License: CC-BY 4.0 (Open-Meteo.com)
"""

import os
import sys
import time
import requests
from datetime import datetime

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

# Key geographic observation checkpoints along the NH 48 corridor
CORRIDOR_GRID_POINTS = [
    {"name": "Chennai", "lat": 13.0827, "lon": 80.2707},
    {"name": "Poonamallee", "lat": 13.0489, "lon": 80.0967},
    {"name": "Sriperumbudur", "lat": 12.9692, "lon": 79.9406},
    {"name": "Kanchipuram", "lat": 12.8342, "lon": 79.7036},
    {"name": "Walajapet", "lat": 12.9298, "lon": 79.3582},
    {"name": "Ranipet", "lat": 12.9229, "lon": 79.3326},
    {"name": "Vellore", "lat": 12.9165, "lon": 79.1325}
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

def fetch_and_store_weather():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Open-Meteo Weather Ingestion...")
    t_start = datetime.now()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create ingestion run log entry
    cursor.execute("""
        INSERT INTO INGESTION_RUN (source, started, status)
        VALUES ('open_meteo_weather', %s, 'running');
    """, (t_start,))
    conn.commit()
    run_id = cursor.lastrowid

    rows_inserted = 0
    error_msg = None

    try:
        insert_sql = """
            INSERT INTO WEATHER_OBS (
                grid_point, ts, precip_mm, visibility_m, wind_kph, temp_c
            ) VALUES (
                ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s
            );
        """

        obs_rows = []

        headers = {"User-Agent": "TravelDB-Ingestion/1.0 (academic-project)"}
        for pt in CORRIDOR_GRID_POINTS:
            params = {
                "latitude": pt["lat"],
                "longitude": pt["lon"],
                "current": "temperature_2m,precipitation,visibility,wind_speed_10m",
                "timezone": "Asia/Kolkata"
            }

            resp = None
            for attempt in range(3):
                try:
                    resp = requests.get(OPEN_METEO_URL, params=params, headers=headers, timeout=12)
                    if resp.status_code == 200:
                        break
                except (requests.RequestException, ConnectionResetError):
                    time.sleep(1.0)

            if resp is not None and resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})
                
                precip = float(current.get("precipitation", 0.0))
                vis_m = float(current.get("visibility", 10000.0))
                wind_kph = float(current.get("wind_speed_10m", 0.0))
                temp_c = float(current.get("temperature_2m", 28.0))
                obs_time = current.get("time", datetime.now().isoformat())

                wkt_point = f"POINT({pt['lon']} {pt['lat']})"
                obs_rows.append((wkt_point, obs_time, precip, vis_m, wind_kph, temp_c))
                print(f"  [+] {pt['name']:<15}: {temp_c}°C, Precip: {precip}mm, Vis: {vis_m}m, Wind: {wind_kph}km/h")
            else:
                code_str = str(resp.status_code) if resp else "Connection Error"
                print(f"  [!] Failed {pt['name']}: HTTP {code_str}")

        if obs_rows:
            cursor.executemany(insert_sql, obs_rows)
            conn.commit()
            rows_inserted = len(obs_rows)

        # Update run status
        cursor.execute("""
            UPDATE INGESTION_RUN
            VALUES (finished=%s, status='success', rows_in=%s)
            WHERE run_id=%s;
        """ if False else """
            UPDATE INGESTION_RUN
            SET finished=%s, status='success', rows_in=%s
            WHERE run_id=%s;
        """, (datetime.now(), rows_inserted, run_id))
        conn.commit()
        print(f"[OK] Open-Meteo Ingestion successful: {rows_inserted} observations recorded.")

    except Exception as e:
        error_msg = str(e)
        cursor.execute("""
            UPDATE INGESTION_RUN
            SET finished=%s, status='failed', error_message=%s
            WHERE run_id=%s;
        """, (datetime.now(), error_msg[:500], run_id))
        conn.commit()
        print(f"[ERROR] Weather Ingestion failed: {e}")

    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    fetch_and_store_weather()
