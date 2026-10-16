import requests

query = """[out:json][timeout:25];
(
  node["amenity"="fuel"](12.90, 80.00, 13.10, 80.25);
);
out body;
"""

endpoints = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter"
]

for ep in endpoints:
    try:
        r = requests.post(
            ep,
            data={"data": query},
            headers={"User-Agent": "TravelDB_Corridor/1.0 (academic research project)"},
            timeout=10
        )
        print(f"{ep}: status {r.status_code}, len {len(r.text)}")
        if r.status_code == 200:
            data = r.json()
            print(f"  -> SUCCESS! Elements returned: {len(data.get('elements', []))}")
    except Exception as e:
        print(f"{ep}: error {e}")
