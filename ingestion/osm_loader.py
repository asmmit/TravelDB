"""
OSM Data Loader for TravelDB.
Loads raw corridor nodes, edges, fuel stations, and POIs into MySQL 8.0.
Computes nearest-node snapping for fuel stations and tags speed_source ('osm' vs 'default').
"""

import os
import sys
import json
import geopandas as gpd
from shapely.geometry import Point, LineString
from scipy.spatial import cKDTree
import numpy as np

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

RAW_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")

VALID_ROAD_TYPES = {
    'motorway', 'motorway_link', 'trunk', 'trunk_link',
    'primary', 'primary_link', 'secondary', 'secondary_link',
    'tertiary', 'tertiary_link', 'unclassified'
}

def load_road_types_defaults(cursor):
    """Fetches default speeds for road types from ROAD_TYPE table."""
    cursor.execute("SELECT road_type, default_speed_kph FROM ROAD_TYPE;")
    return {row[0]: float(row[1]) for row in cursor.fetchall()}

def load_nodes_and_edges():
    """
    Loads nodes and edges from GeoJSON into MySQL.
    """
    nodes_file = os.path.join(RAW_DATA_DIR, "corridor_nodes.geojson")
    edges_file = os.path.join(RAW_DATA_DIR, "corridor_edges.geojson")

    if not os.path.exists(nodes_file) or not os.path.exists(edges_file):
        print("[!] GeoJSON files not found. Run osm_extractor.py first.")
        return

    print("\n[+] Reading nodes and edges GeoJSON...")
    gdf_nodes = gpd.read_file(nodes_file)
    gdf_edges = gpd.read_file(edges_file)

    conn = get_db_connection()
    cursor = conn.cursor()

    default_speeds = load_road_types_defaults(cursor)

    # 1. Insert Nodes
    print(f"[+] Inserting {len(gdf_nodes)} nodes into ROAD_NODE...")
    node_insert_sql = """
        INSERT INTO ROAD_NODE (osm_id, geom)
        VALUES (%s, ST_GeomFromText(%s, 4326))
        ON DUPLICATE KEY UPDATE node_id=node_id;
    """

    node_rows = []
    for idx, row in gdf_nodes.iterrows():
        osm_id = int(row['osmid'])
        geom_wkt = f"POINT({row.geometry.x} {row.geometry.y})"
        node_rows.append((osm_id, geom_wkt))

    # Batch insert in chunks of 5000
    chunk_size = 5000
    for i in range(0, len(node_rows), chunk_size):
        cursor.executemany(node_insert_sql, node_rows[i:i+chunk_size])
    conn.commit()
    print(f"[OK] Nodes inserted successfully.")

    # 2. Build in-memory lookup: osm_id -> node_id
    print("[+] Building node ID lookup table from MySQL...")
    cursor.execute("SELECT osm_id, node_id FROM ROAD_NODE;")
    osm_to_node_id = {row[0]: row[1] for row in cursor.fetchall()}

    # 3. Insert Edges
    print(f"[+] Processing {len(gdf_edges)} edges for ROAD_EDGE...")
    edge_insert_sql = """
        INSERT INTO ROAD_EDGE (
            from_node, to_node, osm_way_id, road_name, ref,
            road_type, length_m, speed_kph, speed_source,
            lanes, oneway, is_toll, surface, geom
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            ST_GeomFromText(%s, 4326)
        );
    """

    edge_rows = []
    skipped_edges = 0

    for idx, row in gdf_edges.iterrows():
        u = int(row['u'])
        v = int(row['v'])

        if u not in osm_to_node_id or v not in osm_to_node_id:
            skipped_edges += 1
            continue

        from_node_id = osm_to_node_id[u]
        to_node_id = osm_to_node_id[v]

        # OSM Way ID
        osm_way_id = int(str(row.get('osmid', 0)).split(',')[0])

        # Road name & Ref
        name = str(row.get('name', ''))[:255] if row.get('name') and str(row.get('name')) != 'nan' else None
        ref = str(row.get('ref', ''))[:50] if row.get('ref') and str(row.get('ref')) != 'nan' else None

        # Road Type
        highway = str(row.get('highway', 'unclassified')).split(',')[0].strip()
        road_type = highway if highway in VALID_ROAD_TYPES else 'unclassified'

        # Length in meters
        length_m = round(float(row.get('length', 0.0)), 2)

        # Maxspeed & speed source
        maxspeed_val = row.get('maxspeed')
        speed_kph = None
        speed_source = 'default'

        if maxspeed_val and str(maxspeed_val) != 'nan':
            # Parse digits from maxspeed string (e.g., "80", "100 km/h")
            digits = ''.join(c for c in str(maxspeed_val).split(',')[0] if c.isdigit())
            if digits:
                parsed_speed = float(digits)
                if 10.0 <= parsed_speed <= 150.0:
                    speed_kph = parsed_speed
                    speed_source = 'osm'

        if speed_kph is None:
            speed_kph = default_speeds.get(road_type, 40.00)
            speed_source = 'default'

        # Lanes
        lanes_val = row.get('lanes', 1)
        try:
            lanes = max(1, int(str(lanes_val).split(',')[0]))
        except (ValueError, TypeError):
            lanes = 1

        # Oneway
        oneway = bool(row.get('oneway', False))

        # Toll
        toll_val = str(row.get('toll', 'no')).lower()
        is_toll = toll_val in ('yes', 'true', '1')

        # Surface
        surface = str(row.get('surface', ''))[:50] if row.get('surface') and str(row.get('surface')) != 'nan' else None

        # LineString geometry to WKT
        geom_wkt = row.geometry.wkt

        edge_rows.append((
            from_node_id, to_node_id, osm_way_id, name, ref,
            road_type, length_m, speed_kph, speed_source,
            lanes, oneway, is_toll, surface, geom_wkt
        ))

    print(f"[+] Inserting {len(edge_rows)} edges (skipped {skipped_edges} unconnected)...")
    for i in range(0, len(edge_rows), chunk_size):
        cursor.executemany(edge_insert_sql, edge_rows[i:i+chunk_size])
    conn.commit()

    print(f"[OK] Edges inserted successfully.")
    cursor.close()
    conn.close()

def snap_and_load_fuel_stations():
    """
    Loads fuel stations, snaps each station to the nearest ROAD_NODE using KDTree,
    and populates nearest_node_id and snap_dist_m.
    """
    fuel_file = os.path.join(RAW_DATA_DIR, "corridor_fuel_stations.geojson")
    if not os.path.exists(fuel_file):
        print("[!] Fuel station GeoJSON not found.")
        return

    print("\n[+] Loading fuel stations and snapping to nearest road nodes...")
    gdf_fuel = gpd.read_file(fuel_file)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Load all nodes with their coordinates for KDTree
    cursor.execute("SELECT node_id, ST_X(geom), ST_Y(geom) FROM ROAD_NODE;")
    nodes_data = cursor.fetchall()

    if not nodes_data:
        print("[!] No nodes in ROAD_NODE to snap fuel stations to.")
        return

    node_ids = [row[0] for row in nodes_data]
    node_coords = np.array([(row[1], row[2]) for row in nodes_data]) # (lon, lat)

    # Build KDTree for sub-millisecond nearest neighbor lookup
    tree = cKDTree(node_coords)

    station_insert_sql = """
        INSERT INTO FUEL_STATION (
            osm_id, name, brand, geom, nearest_node_id, snap_dist_m, opening_hours, verified_status
        ) VALUES (
            %s, %s, %s, ST_GeomFromText(%s, 4326), %s, %s, %s, 'osm_unverified'
        ) ON DUPLICATE KEY UPDATE
            nearest_node_id = VALUES(nearest_node_id),
            snap_dist_m = VALUES(snap_dist_m);
    """

    station_rows = []
    for idx, row in gdf_fuel.iterrows():
        # Representative point (handles both Point and Polygon geometries)
        pt = row.geometry.centroid
        lon, lat = pt.x, pt.y

        # Query KDTree for nearest node
        dist_deg, nearest_idx = tree.query([lon, lat])
        nearest_node_id = node_ids[nearest_idx]

        # Convert degree distance to approximate meters (1 deg lat ~ 111,000m)
        snap_dist_m = round(dist_deg * 111320.0, 2)

        osm_id = int(row['osmid']) if 'osmid' in row and str(row['osmid']).isdigit() else None
        name = str(row.get('name', ''))[:255] if row.get('name') and str(row.get('name')) != 'nan' else None
        brand = str(row.get('brand', ''))[:100] if row.get('brand') and str(row.get('brand')) != 'nan' else None
        opening_hours = str(row.get('opening_hours', ''))[:255] if row.get('opening_hours') and str(row.get('opening_hours')) != 'nan' else None
        geom_wkt = f"POINT({lon} {lat})"

        station_rows.append((
            osm_id, name, brand, geom_wkt, nearest_node_id, snap_dist_m, opening_hours
        ))

    print(f"[+] Inserting {len(station_rows)} fuel stations with snapped nodes...")
    for i in range(0, len(station_rows), 1000):
        cursor.executemany(station_insert_sql, station_rows[i:i+1000])
    conn.commit()

    print(f"[OK] Fuel stations loaded and snapped successfully.")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    load_nodes_and_edges()
    snap_and_load_fuel_stations()
