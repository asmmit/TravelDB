"""
Corridor Traffic Sample Points Initializer for TravelDB.
Selects key representative highway segments along NH 48 (Chennai - Vellore corridor)
and populates the TRAFFIC_SAMPLE_POINT table with spatial Point geometries.
"""

import os
import sys
from shapely import wkt

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

def initialize_sample_points():
    print("=== Initializing Corridor Traffic Sample Points ===")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Check if sample points already exist
    cursor.execute("SELECT COUNT(*) AS c FROM TRAFFIC_SAMPLE_POINT;")
    count = cursor.fetchone()['c']
    if count > 0:
        print(f"[i] TRAFFIC_SAMPLE_POINT already contains {count} sample points.")
        cursor.close()
        conn.close()
        return

    # Select representative highway edges along NH 48 / AH 45 corridor
    query = """
        SELECT edge_id, road_name, ref, road_type, length_m, ST_AsText(geom) AS geom_wkt
        FROM ROAD_EDGE
        WHERE road_type IN ('trunk', 'motorway', 'primary')
          AND length_m >= 100
        ORDER BY edge_id ASC;
    """
    cursor.execute(query)
    edges = cursor.fetchall()
    print(f"[+] Found {len(edges):,} major highway edges.")

    # Select roughly every 25th edge to get an even spatial spread along the corridor (~40 sample points)
    step = max(1, len(edges) // 40)
    sample_edges = edges[::step][:45]

    insert_sql = """
        INSERT INTO TRAFFIC_SAMPLE_POINT (edge_id, geom, corridor_name)
        VALUES (%s, ST_GeomFromText(%s, 4326), %s);
    """

    sample_rows = []
    for edge in sample_edges:
        geom_line = wkt.loads(edge['geom_wkt'])
        midpoint = geom_line.interpolate(0.5, normalized=True)
        mid_wkt = f"POINT({midpoint.x:.6f} {midpoint.y:.6f})"
        sample_rows.append((
            edge['edge_id'],
            mid_wkt,
            'Chennai-Vellore-NH48'
        ))

    cursor.executemany(insert_sql, sample_rows)
    conn.commit()

    print(f"[SUCCESS] Inserted {len(sample_rows)} sample points into TRAFFIC_SAMPLE_POINT.")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    initialize_sample_points()
