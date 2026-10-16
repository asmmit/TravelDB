"""
OSM Data Extractor for TravelDB.
Extracts drivable road network and POIs for the Chennai-Vellore-Bengaluru corridor.
Saves raw GeoDataFrames to disk (data/raw/) to enable offline/reproducible loading into MySQL.
"""

import os
import json
import osmnx as ox
import geopandas as gpd

# Configure OSMnx settings
ox.settings.use_cache = True
ox.settings.log_console = True

# Chennai-Vellore-Bengaluru corridor bounding box (North, South, East, West)
# Covers NH 48 / AH 45 connecting Chennai, Sriperumbudur, Kanchipuram, Walajapet, Ranipet, Vellore, Ambur, Vaniyambadi, Krishnagiri, Hosur, Bengaluru.
BBOX = {
    "north": 13.30,
    "south": 12.60,
    "east": 80.35,
    "west": 77.40
}

RAW_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")

def extract_road_network(bbox=BBOX):
    """
    Downloads drivable road network for motorway, trunk, primary, secondary, tertiary roads.
    """
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    print(f"\n[+] Extracting road network for BBOX: N={bbox['north']}, S={bbox['south']}, E={bbox['east']}, W={bbox['west']}...")

    # Filter for major drivable roads only (motorway to tertiary)
    cf = '["highway"~"motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"]'

    # In OSMnx 2.x, bbox is (left, bottom, right, top) -> (west, south, east, north)
    bbox_tuple = (bbox['west'], bbox['south'], bbox['east'], bbox['north'])

    # Download graph
    G = ox.graph_from_bbox(
        bbox=bbox_tuple,
        network_type="drive",
        custom_filter=cf,
        retain_all=False,
        truncate_by_edge=True
    )

    print(f"[+] Download complete: {len(G.nodes)} nodes, {len(G.edges)} edges.")

    # Convert to GeoDataFrames
    gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)

    # Save to disk as GeoJSON for inspection & offline loading
    nodes_path = os.path.join(RAW_DATA_DIR, "corridor_nodes.geojson")
    edges_path = os.path.join(RAW_DATA_DIR, "corridor_edges.geojson")

    print(f"[+] Saving nodes to {nodes_path}...")
    gdf_nodes.to_file(nodes_path, driver="GeoJSON")

    print(f"[+] Saving edges to {edges_path}...")
    # Convert list attributes to strings so GeoJSON driver doesn't choke
    for col in gdf_edges.columns:
        if gdf_edges[col].apply(lambda x: isinstance(x, list)).any():
            gdf_edges[col] = gdf_edges[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)
    gdf_edges.to_file(edges_path, driver="GeoJSON")

    print(f"[OK] Road network saved successfully!")
    return gdf_nodes, gdf_edges

def extract_fuel_stations(bbox=BBOX):
    """
    Downloads fuel stations (amenity=fuel) within the corridor.
    """
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    print(f"\n[+] Extracting fuel stations (amenity=fuel)...")
    tags = {"amenity": "fuel"}

    bbox_tuple = (bbox['west'], bbox['south'], bbox['east'], bbox['north'])
    gdf_fuel = ox.features_from_bbox(bbox=bbox_tuple, tags=tags)

    print(f"[+] Found {len(gdf_fuel)} fuel stations.")
    fuel_path = os.path.join(RAW_DATA_DIR, "corridor_fuel_stations.geojson")

    # Keep relevant tags
    for col in gdf_fuel.columns:
        if gdf_fuel[col].apply(lambda x: isinstance(x, list)).any():
            gdf_fuel[col] = gdf_fuel[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)

    gdf_fuel.to_file(fuel_path, driver="GeoJSON")
    print(f"[OK] Fuel stations saved to {fuel_path}!")
    return gdf_fuel

def extract_pois(bbox=BBOX):
    """
    Downloads emergency and travel POIs: hospitals, police stations, EV charging, toll booths.
    """
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    print(f"\n[+] Extracting POIs (hospitals, police, EV charging, toll booths)...")
    tags = {
        "amenity": ["hospital", "police", "charging_station"],
        "barrier": ["toll_booth"],
        "highway": ["rest_area"]
    }

    bbox_tuple = (bbox['west'], bbox['south'], bbox['east'], bbox['north'])
    gdf_pois = ox.features_from_bbox(bbox=bbox_tuple, tags=tags)

    print(f"[+] Found {len(gdf_pois)} POIs.")
    pois_path = os.path.join(RAW_DATA_DIR, "corridor_pois.geojson")

    for col in gdf_pois.columns:
        if gdf_pois[col].apply(lambda x: isinstance(x, list)).any():
            gdf_pois[col] = gdf_pois[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)

    gdf_pois.to_file(pois_path, driver="GeoJSON")
    print(f"[OK] POIs saved to {pois_path}!")
    return gdf_pois

if __name__ == "__main__":
    print("=== TravelDB OSM Corridor Extractor ===")
    extract_road_network()
    extract_fuel_stations()
    extract_pois()
    print("\nExtraction complete! Files ready in data/raw/")
