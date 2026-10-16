"""
Phase 1 Full Data Pipeline & Loader for TravelDB.
1. Builds graph from cached Overpass network responses -> saves GeoJSON.
2. Formats raw fuel stations (240 stations) and POIs (897 POIs) -> saves GeoJSON.
3. Loads ROAD_NODE and ROAD_EDGE into MySQL 8.0 with spatial SRID 4326.
4. Snaps FUEL_STATION to nearest ROAD_NODE using KDTree and populates nearest_node_id & snap_dist_m.
5. Loads travel & emergency POI records into POI table.
"""

import os
import sys
import glob
import json
import time
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
from scipy.spatial import cKDTree
import osmnx as ox

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
RAW_DATA_DIR = os.path.join(BASE_DIR, "data", "raw")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

VALID_ROAD_TYPES = {
    'motorway', 'motorway_link', 'trunk', 'trunk_link',
    'primary', 'primary_link', 'secondary', 'secondary_link',
    'tertiary', 'tertiary_link', 'unclassified'
}

def step1_build_and_save_network():
    print("\n--- STEP 1: Building Road Network from Cache ---")
    cache_files = glob.glob(os.path.join(CACHE_DIR, "*.json"))
    print(f"[+] Found {len(cache_files)} cached network responses.")
    
    response_jsons = []
    for f in cache_files:
        with open(f, 'r', encoding='utf-8') as fp:
            response_jsons.append(json.load(fp))

    print("[+] Assembling MultiDiGraph with OSMnx...")
    G = ox.graph._create_graph(response_jsons, bidirectional=False)
    print(f"[+] Graph constructed: {len(G.nodes):,} nodes, {len(G.edges):,} edges.")

    print("[+] Converting graph to GeoDataFrames...")
    gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)
    gdf_nodes = gdf_nodes.reset_index()
    gdf_edges = gdf_edges.reset_index()

    nodes_path = os.path.join(RAW_DATA_DIR, "corridor_nodes.geojson")
    edges_path = os.path.join(RAW_DATA_DIR, "corridor_edges.geojson")

    print(f"[+] Saving nodes to {nodes_path}...")
    gdf_nodes.to_file(nodes_path, driver="GeoJSON")

    print(f"[+] Saving edges to {edges_path}...")
    for col in gdf_edges.columns:
        if gdf_edges[col].apply(lambda x: isinstance(x, list)).any():
            gdf_edges[col] = gdf_edges[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)
    gdf_edges.to_file(edges_path, driver="GeoJSON")

    print(f"[OK] Step 1 Complete: Network saved to disk.")
    return gdf_nodes, gdf_edges

def step2_format_fuel_and_pois():
    print("\n--- STEP 2: Formatting Fuel Stations and POIs ---")
    # 1. Fuel Stations
    fuel_raw_file = os.path.join(RAW_DATA_DIR, "corridor_fuel_raw.json")
    with open(fuel_raw_file, 'r', encoding='utf-8') as f:
        fuel_data = json.load(f)

    fuel_records = []
    for el in fuel_data.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not lat or not lon:
            continue
        tags = el.get("tags", {})
        fuel_records.append({
            "osmid": el["id"],
            "name": tags.get("name"),
            "brand": tags.get("brand") or tags.get("operator"),
            "opening_hours": tags.get("opening_hours"),
            "geometry": Point(lon, lat)
        })

    gdf_fuel = gpd.GeoDataFrame(fuel_records, crs="EPSG:4326")
    fuel_path = os.path.join(RAW_DATA_DIR, "corridor_fuel_stations.geojson")
    gdf_fuel.to_file(fuel_path, driver="GeoJSON")
    print(f"[OK] Saved {len(gdf_fuel)} fuel stations to {fuel_path}")

    # 2. POIs
    poi_raw_file = os.path.join(RAW_DATA_DIR, "corridor_poi_raw.json")
    with open(poi_raw_file, 'r', encoding='utf-8') as f:
        poi_data = json.load(f)

    poi_records = []
    for el in poi_data.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not lat or not lon:
            continue
        tags = el.get("tags", {})
        
        # Categorize
        cat = None
        if tags.get("amenity") == "hospital":
            cat = "hospital"
        elif tags.get("amenity") == "police":
            cat = "police"
        elif tags.get("amenity") == "charging_station":
            cat = "charging_station"
        elif tags.get("barrier") == "toll_booth":
            cat = "toll"
        elif tags.get("highway") == "rest_area":
            cat = "rest_area"

        if cat:
            poi_records.append({
                "osmid": el["id"],
                "name": tags.get("name") or f"Unnamed {cat.replace('_', ' ').title()}",
                "category_id": cat,
                "geometry": Point(lon, lat)
            })

    gdf_pois = gpd.GeoDataFrame(poi_records, crs="EPSG:4326")
    poi_path = os.path.join(RAW_DATA_DIR, "corridor_pois.geojson")
    gdf_pois.to_file(poi_path, driver="GeoJSON")
    print(f"[OK] Saved {len(gdf_pois)} classified POIs to {poi_path}")

    return gdf_fuel, gdf_pois

def step3_load_mysql(gdf_nodes, gdf_edges, gdf_fuel, gdf_pois):
    print("\n--- STEP 3: Loading All Entities into MySQL 8.0 ---")
    conn = get_db_connection()
    cursor = conn.cursor()

    # Clear existing data in topological order to enable clean idempotent loading
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
    for tbl in ["ROAD_EDGE", "ROAD_NODE", "FUEL_STATION", "POI"]:
        cursor.execute(f"TRUNCATE TABLE {tbl};")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
    conn.commit()

    # Fetch default speeds
    cursor.execute("SELECT road_type, default_speed_kph FROM ROAD_TYPE;")
    default_speeds = {row[0]: float(row[1]) for row in cursor.fetchall()}

    # A. Insert ROAD_NODE
    print(f"[+] Inserting {len(gdf_nodes):,} road nodes...")
    node_sql = "INSERT IGNORE INTO ROAD_NODE (osm_id, geom) VALUES (%s, ST_GeomFromText(%s, 4326));"
    node_rows = []
    node_coords = []
    node_osm_ids = []

    for idx, row in gdf_nodes.iterrows():
        osm_id = int(row['osmid'])
        lon, lat = row.geometry.x, row.geometry.y
        wkt = f"POINT({lon} {lat})"
        node_rows.append((osm_id, wkt))
        node_coords.append((lon, lat))
        node_osm_ids.append(osm_id)

    chunk_size = 5000
    for i in range(0, len(node_rows), chunk_size):
        cursor.executemany(node_sql, node_rows[i:i+chunk_size])
    conn.commit()
    print(f"[OK] Road nodes inserted successfully.")

    # Retrieve node_id mapping from MySQL
    print("[+] Building node ID lookup map...")
    cursor.execute("SELECT osm_id, node_id FROM ROAD_NODE;")
    osm_to_node_id = {row[0]: row[1] for row in cursor.fetchall()}

    # B. Insert ROAD_EDGE
    print(f"[+] Processing {len(gdf_edges):,} road edges...")
    edge_sql = """
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
    skipped = 0

    for idx, row in gdf_edges.iterrows():
        u = int(row['u'])
        v = int(row['v'])
        if u not in osm_to_node_id or v not in osm_to_node_id:
            skipped += 1
            continue

        from_nid = osm_to_node_id[u]
        to_nid = osm_to_node_id[v]
        osm_way_id = int(str(row.get('osmid', 0)).split(',')[0])
        name = str(row.get('name', ''))[:255] if row.get('name') and str(row.get('name')) != 'nan' else None
        ref = str(row.get('ref', ''))[:50] if row.get('ref') and str(row.get('ref')) != 'nan' else None

        # Road type
        hw = str(row.get('highway', 'unclassified')).split(',')[0].strip()
        rtype = hw if hw in VALID_ROAD_TYPES else 'unclassified'
        length_m = round(float(row.get('length', 0.0)), 2)

        # Speed limit
        maxspeed_val = row.get('maxspeed')
        speed_kph = None
        speed_source = 'default'
        if maxspeed_val and str(maxspeed_val) != 'nan':
            digits = ''.join(c for c in str(maxspeed_val).split(',')[0] if c.isdigit())
            if digits:
                parsed = float(digits)
                if 10.0 <= parsed <= 150.0:
                    speed_kph = parsed
                    speed_source = 'osm'

        if speed_kph is None:
            speed_kph = default_speeds.get(rtype, 40.0)
            speed_source = 'default'

        # Lanes & Toll
        lanes_val = row.get('lanes', 1)
        try:
            lanes = max(1, int(str(lanes_val).split(',')[0]))
        except (ValueError, TypeError):
            lanes = 1

        oneway = bool(row.get('oneway', False))
        toll_val = str(row.get('toll', 'no')).lower()
        is_toll = toll_val in ('yes', 'true', '1')
        surface = str(row.get('surface', ''))[:50] if row.get('surface') and str(row.get('surface')) != 'nan' else None
        geom_wkt = row.geometry.wkt

        edge_rows.append((
            from_nid, to_nid, osm_way_id, name, ref,
            rtype, length_m, speed_kph, speed_source,
            lanes, oneway, is_toll, surface, geom_wkt
        ))

    print(f"[+] Inserting {len(edge_rows):,} edges into MySQL (skipped {skipped} unconnected)...")
    for i in range(0, len(edge_rows), chunk_size):
        cursor.executemany(edge_sql, edge_rows[i:i+chunk_size])
    conn.commit()
    print(f"[OK] Road edges inserted successfully.")

    # C. Snap and Insert FUEL_STATION using KDTree
    print(f"[+] Snapping {len(gdf_fuel):,} fuel stations to nearest road nodes via KDTree...")
    tree = cKDTree(np.array(node_coords)) # (lon, lat)

    station_sql = """
        INSERT IGNORE INTO FUEL_STATION (
            osm_id, name, brand, geom, nearest_node_id, snap_dist_m, opening_hours, verified_status
        ) VALUES (
            %s, %s, %s, ST_GeomFromText(%s, 4326), %s, %s, %s, 'osm_unverified'
        );
    """

    station_rows = []
    for idx, row in gdf_fuel.iterrows():
        lon, lat = row.geometry.x, row.geometry.y
        dist_deg, nearest_idx = tree.query([lon, lat])
        nearest_osm_id = node_osm_ids[nearest_idx]
        nearest_nid = osm_to_node_id.get(nearest_osm_id)
        snap_m = round(dist_deg * 111320.0, 2)

        name = str(row.get('name', ''))[:255] if row.get('name') and str(row.get('name')) != 'nan' else None
        brand = str(row.get('brand', ''))[:100] if row.get('brand') and str(row.get('brand')) != 'nan' else None
        opening = str(row.get('opening_hours', ''))[:255] if row.get('opening_hours') and str(row.get('opening_hours')) != 'nan' else None
        geom_wkt = f"POINT({lon} {lat})"

        station_rows.append((
            int(row['osmid']), name, brand, geom_wkt, nearest_nid, snap_m, opening
        ))

    cursor.executemany(station_sql, station_rows)
    conn.commit()
    print(f"[OK] {len(station_rows)} fuel stations inserted and snapped successfully.")

    # D. Snap and Insert POI
    print(f"[+] Snapping and inserting {len(gdf_pois):,} travel POIs...")
    poi_sql = """
        INSERT IGNORE INTO POI (
            osm_id, name, category_id, geom, nearest_node_id
        ) VALUES (
            %s, %s, %s, ST_GeomFromText(%s, 4326), %s
        );
    """

    poi_rows = []
    for idx, row in gdf_pois.iterrows():
        lon, lat = row.geometry.x, row.geometry.y
        dist_deg, nearest_idx = tree.query([lon, lat])
        nearest_osm_id = node_osm_ids[nearest_idx]
        nearest_nid = osm_to_node_id.get(nearest_osm_id)

        name = str(row.get('name', ''))[:255]
        cat = row['category_id']
        geom_wkt = f"POINT({lon} {lat})"

        poi_rows.append((int(row['osmid']), name, cat, geom_wkt, nearest_nid))

    cursor.executemany(poi_sql, poi_rows)
    conn.commit()
    print(f"[OK] {len(poi_rows)} POIs inserted successfully.")

    # Record Ingestion Run
    cursor.execute("""
        INSERT INTO INGESTION_RUN (source, started, finished, status, rows_in)
        VALUES ('osm_corridor_phase1', NOW(), NOW(), 'success', %s);
    """, (len(node_rows) + len(edge_rows) + len(station_rows) + len(poi_rows),))
    conn.commit()

    cursor.close()
    conn.close()
    print("\n[SUCCESS] Phase 1 Database Loading Completed!")

if __name__ == "__main__":
    t0 = time.time()
    gdf_nodes, gdf_edges = step1_build_and_save_network()
    gdf_fuel, gdf_pois = step2_format_fuel_and_pois()
    step3_load_mysql(gdf_nodes, gdf_edges, gdf_fuel, gdf_pois)
    print(f"\nPipeline finished in {round(time.time() - t0, 2)}s.")
