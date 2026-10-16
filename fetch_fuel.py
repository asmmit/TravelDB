import requests
import json
import time

headers = {"User-Agent": "TravelDB_Fuel/1.0 (academic; student@traveldb.local)"}

# Split into two slices: East (Chennai to Kanchipuram) and West (Kanchipuram to Ranipet)
boxes = [
    ("East", "12.80, 79.80, 13.15, 80.26"),
    ("West", "12.80, 79.39, 13.15, 79.80")
]

all_elements = []
for name, bbox in boxes:
    q = f'[out:json][timeout:35];node["amenity"="fuel"]({bbox});out body;'
    for attempt in range(1, 4):
        try:
            print(f"[{name}] Attempt {attempt}: querying {bbox}...")
            r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=headers, timeout=40)
            print(f"[{name}] Status: {r.status_code}")
            if r.status_code == 200:
                elems = r.json().get("elements", [])
                print(f"[{name}] Found {len(elems)} fuel stations.")
                all_elements.extend(elems)
                break
        except Exception as e:
            print(f"[{name}] Error: {e}")
            time.sleep(10)

print(f"\nTotal fuel stations retrieved: {len(all_elements)}")
if all_elements:
    with open("data/raw/corridor_fuel_raw.json", "w", encoding="utf-8") as f:
        json.dump({"elements": all_elements}, f, indent=2)
    print("SUCCESS: Saved to data/raw/corridor_fuel_raw.json")
