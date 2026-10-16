import requests
import json
import os

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
os.makedirs(RAW_DATA_DIR, exist_ok=True)

bbox_str = "12.766, 79.393, 13.198, 80.263"
headers = {"User-Agent": "TravelDB_Student_Project/1.0 (academic; student@traveldb.local)"}

# 1. Fetch Fuel Stations
print(f"Fetching fuel stations in bbox ({bbox_str})...")
fuel_query = f"""[out:json][timeout:60];
(
  node["amenity"="fuel"]({bbox_str});
  way["amenity"="fuel"]({bbox_str});
);
out center;
"""

r_fuel = requests.post("https://overpass-api.de/api/interpreter", data={"data": fuel_query}, headers=headers, timeout=60)
print(f"Fuel status: {r_fuel.status_code}")

if r_fuel.status_code == 200:
    fuel_data = r_fuel.json()
    elements = fuel_data.get("elements", [])
    print(f"Found {len(elements)} real fuel stations!")
    with open(os.path.join(RAW_DATA_DIR, "corridor_fuel_raw.json"), "w", encoding="utf-8") as f:
        json.dump(fuel_data, f, indent=2)

# 2. Fetch Travel POIs
print(f"\nFetching travel & emergency POIs in bbox ({bbox_str})...")
poi_query = f"""[out:json][timeout:60];
(
  node["amenity"="hospital"]({bbox_str});
  node["amenity"="police"]({bbox_str});
  node["amenity"="charging_station"]({bbox_str});
  node["barrier"="toll_booth"]({bbox_str});
  node["highway"="rest_area"]({bbox_str});
);
out center;
"""

r_poi = requests.post("https://overpass-api.de/api/interpreter", data={"data": poi_query}, headers=headers, timeout=60)
print(f"POI status: {r_poi.status_code}")

if r_poi.status_code == 200:
    poi_data = r_poi.json()
    elements = poi_data.get("elements", [])
    print(f"Found {len(elements)} real travel/emergency POIs!")
    with open(os.path.join(RAW_DATA_DIR, "corridor_poi_raw.json"), "w", encoding="utf-8") as f:
        json.dump(poi_data, f, indent=2)
