import os
import time
import osmnx as ox
import geopandas as gpd

ox.settings.use_cache = True
ox.settings.log_console = True
ox.settings.overpass_rate_limit = False
ox.settings.timeout = 180

# Chennai to Vellore highway corridor
# West: 79.10 (Vellore), East: 80.25 (Chennai), South: 12.85, North: 13.15
bbox = (79.10, 12.85, 80.25, 13.15)
cf = '["highway"~"motorway|trunk|primary|secondary|motorway_link|trunk_link|primary_link|secondary_link"]'

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
os.makedirs(RAW_DATA_DIR, exist_ok=True)

# 1. Download Road Network
max_attempts = 10
G = None

for attempt in range(1, max_attempts + 1):
    try:
        print(f"\n[Attempt {attempt}/{max_attempts}] Fetching corridor road network...")
        G = ox.graph_from_bbox(bbox=bbox, custom_filter=cf, retain_all=False)
        print(f"\n[SUCCESS] Loaded network: {len(G.nodes)} nodes, {len(G.edges)} edges.")
        break
    except Exception as e:
        print(f"[-] Attempt {attempt} failed: {e}")
        if attempt < max_attempts:
            wait_sec = min(15 * attempt, 60)
            print(f"[i] Backing off for {wait_sec}s. Cached chunks are safely saved in cache/...")
            time.sleep(wait_sec)

if G is None:
    print("[ERROR] Could not complete road network download.")
    exit(1)

print("[+] Extracting GeoDataFrames...")
gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)

nodes_path = os.path.join(RAW_DATA_DIR, "corridor_nodes.geojson")
edges_path = os.path.join(RAW_DATA_DIR, "corridor_edges.geojson")

print(f"[+] Saving nodes to {nodes_path}...")
gdf_nodes.to_file(nodes_path, driver="GeoJSON")

print(f"[+] Saving edges to {edges_path}...")
for col in gdf_edges.columns:
    if gdf_edges[col].apply(lambda x: isinstance(x, list)).any():
        gdf_edges[col] = gdf_edges[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)
gdf_edges.to_file(edges_path, driver="GeoJSON")
print(f"[OK] Road network saved successfully ({len(gdf_nodes)} nodes, {len(gdf_edges)} edges).")

# 2. Extract Fuel Stations
print("\n[+] Extracting fuel stations (amenity=fuel)...")
tags_fuel = {"amenity": "fuel"}
for attempt in range(1, 6):
    try:
        gdf_fuel = ox.features_from_bbox(bbox=bbox, tags=tags_fuel)
        fuel_path = os.path.join(RAW_DATA_DIR, "corridor_fuel_stations.geojson")
        for col in gdf_fuel.columns:
            if gdf_fuel[col].apply(lambda x: isinstance(x, list)).any():
                gdf_fuel[col] = gdf_fuel[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)
        gdf_fuel.to_file(fuel_path, driver="GeoJSON")
        print(f"[OK] Saved {len(gdf_fuel)} fuel stations to {fuel_path}!")
        break
    except Exception as e:
        print(f"[-] Fuel station attempt {attempt} failed: {e}")
        time.sleep(15)

# 3. Extract POIs
print("\n[+] Extracting travel and emergency POIs...")
tags_poi = {
    "amenity": ["hospital", "police", "charging_station"],
    "barrier": ["toll_booth"],
    "highway": ["rest_area"]
}
for attempt in range(1, 6):
    try:
        gdf_pois = ox.features_from_bbox(bbox=bbox, tags=tags_poi)
        pois_path = os.path.join(RAW_DATA_DIR, "corridor_pois.geojson")
        for col in gdf_pois.columns:
            if gdf_pois[col].apply(lambda x: isinstance(x, list)).any():
                gdf_pois[col] = gdf_pois[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)
        gdf_pois.to_file(pois_path, driver="GeoJSON")
        print(f"[OK] Saved {len(gdf_pois)} POIs to {pois_path}!")
        break
    except Exception as e:
        print(f"[-] POI attempt {attempt} failed: {e}")
        time.sleep(15)

print("\n=== Phase 1 Extraction Complete! All GeoJSON files saved in data/raw/ ===")
