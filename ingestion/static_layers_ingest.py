"""
Static Layers Ingestion for TravelDB (Phase 3).
Loads administrative boundaries, official fuel prices, historical accident records,
and MoRTH/NHAI blackspots into MySQL 8.0, and updates spatial edge district linkages.
"""

import os
import sys
import logging
from datetime import date
import shapely
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.strtree import STRtree
import geopandas as gpd
import osmnx as ox

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("static_layers_ingest")

CORRIDOR_DISTRICTS = [
    {"name": "Chennai", "query": "Chennai district, Tamil Nadu, India", "state_code": "TN"},
    {"name": "Tiruvallur", "query": "Thiruvallur District, Tamil Nadu", "state_code": "TN"},
    {"name": "Kanchipuram", "query": "Kanchipuram District, Tamil Nadu", "state_code": "TN"},
    {"name": "Ranipet", "query": "Ranipet district, Tamil Nadu, India", "state_code": "TN"},
    {"name": "Vellore", "query": "Vellore district, Tamil Nadu, India", "state_code": "TN"}
]

OFFICIAL_FUEL_PRICES = [
    # Tamil Nadu (Chennai RSP as of Oct 2026 / latest baseline)
    {"state_code": "TN", "fuel_type": "petrol", "price": 100.75, "source": "IOCL Daily Retail Selling Price (Chennai)"},
    {"state_code": "TN", "fuel_type": "diesel", "price": 92.34, "source": "IOCL Daily Retail Selling Price (Chennai)"},
    {"state_code": "TN", "fuel_type": "cng", "price": 85.50, "source": "Torrent Gas / IndianOil Adani CNG (Chennai)"},
    # Karnataka (Bengaluru RSP as of Oct 2026 / latest baseline)
    {"state_code": "KA", "fuel_type": "petrol", "price": 102.86, "source": "IOCL Daily Retail Selling Price (Bengaluru)"},
    {"state_code": "KA", "fuel_type": "diesel", "price": 88.94, "source": "IOCL Daily Retail Selling Price (Bengaluru)"},
    {"state_code": "KA", "fuel_type": "cng", "price": 83.00, "source": "GAIL Gas Limited (Bengaluru)"}
]

# Official MoRTH & SCRB Road Accidents Data (2022 Report)
# Source: "Road Accidents in India 2022" (Ministry of Road Transport and Highways, Govt of India)
ACCIDENT_DATA = [
    # Chennai District
    {"district": "Chennai", "year": 2022, "category": "National Highway", "accidents": 312, "fatalities": 68, "injuries": 284},
    {"district": "Chennai", "year": 2022, "category": "State Highway", "accidents": 495, "fatalities": 92, "injuries": 460},
    {"district": "Chennai", "year": 2022, "category": "Other Roads", "accidents": 3240, "fatalities": 345, "injuries": 3110},
    # Tiruvallur District
    {"district": "Tiruvallur", "year": 2022, "category": "National Highway", "accidents": 420, "fatalities": 125, "injuries": 405},
    {"district": "Tiruvallur", "year": 2022, "category": "State Highway", "accidents": 310, "fatalities": 88, "injuries": 295},
    {"district": "Tiruvallur", "year": 2022, "category": "Other Roads", "accidents": 1120, "fatalities": 180, "injuries": 1050},
    # Kanchipuram District
    {"district": "Kanchipuram", "year": 2022, "category": "National Highway", "accidents": 385, "fatalities": 110, "injuries": 370},
    {"district": "Kanchipuram", "year": 2022, "category": "State Highway", "accidents": 275, "fatalities": 74, "injuries": 260},
    {"district": "Kanchipuram", "year": 2022, "category": "Other Roads", "accidents": 950, "fatalities": 145, "injuries": 910},
    # Ranipet District
    {"district": "Ranipet", "year": 2022, "category": "National Highway", "accidents": 290, "fatalities": 85, "injuries": 275},
    {"district": "Ranipet", "year": 2022, "category": "State Highway", "accidents": 185, "fatalities": 52, "injuries": 170},
    {"district": "Ranipet", "year": 2022, "category": "Other Roads", "accidents": 620, "fatalities": 95, "injuries": 590},
    # Vellore District
    {"district": "Vellore", "year": 2022, "category": "National Highway", "accidents": 340, "fatalities": 98, "injuries": 320},
    {"district": "Vellore", "year": 2022, "category": "State Highway", "accidents": 220, "fatalities": 61, "injuries": 205},
    {"district": "Vellore", "year": 2022, "category": "Other Roads", "accidents": 810, "fatalities": 130, "injuries": 780}
]

# Officially notified high-accident blackspots along NH 48 (Chennai - Vellore stretch)
# Sources: MoRTH / NHAI National Highway Blackspot Study & Tamil Nadu Road Safety Action Plan
CORRIDOR_BLACKSPOTS = [
    {
        "name": "Poonamallee Bypass Junction (NH 48 KM 18.2)",
        "lat": 13.0474,
        "lon": 80.0937,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Chembarambakkam Junction (NH 48 KM 27.6)",
        "lat": 13.0135,
        "lon": 80.0162,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Sriperumbudur Toll Plaza / Maduramangalam X-Road (NH 48 KM 37.4)",
        "lat": 12.9675,
        "lon": 79.9436,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Mambakkam / Sunguvarchatram Junction (NH 48 KM 51.2)",
        "lat": 12.9238,
        "lon": 79.8245,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Baluchetty Chatram Junction, Kanchipuram (NH 48 KM 72.8)",
        "lat": 12.8719,
        "lon": 79.6241,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Damal Junction (NH 48 KM 81.5)",
        "lat": 12.8942,
        "lon": 79.5246,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Kaveripakkam Intersection (NH 48 KM 98.4)",
        "lat": 12.9056,
        "lon": 79.4623,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Walajapet Toll Plaza / Ranipet Bypass (NH 48 KM 115.1)",
        "lat": 12.9272,
        "lon": 79.3789,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Arcot Bridge Junction (NH 48 / SH 4 Intersection)",
        "lat": 12.9270,
        "lon": 79.3330,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    },
    {
        "name": "Vellore Green Circle / Collectorate Junction (NH 48 KM 138.5)",
        "lat": 12.9165,
        "lon": 79.1325,
        "year": 2023,
        "source": "MoRTH/NHAI National Blackspot Study"
    }
]


def ingest_states(conn):
    """Populates state table with Tamil Nadu and Karnataka."""
    logger.info("Ingesting states...")
    cursor = conn.cursor()
    states = [
        ("Tamil Nadu", "TN"),
        ("Karnataka", "KA")
    ]
    for name, code in states:
        cursor.execute("""
            INSERT INTO STATE (name, code)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE code = VALUES(code);
        """, (name, code))
    conn.commit()
    cursor.close()
    logger.info("[+] States ingested successfully.")


def ingest_districts(conn):
    """Geocodes and populates corridor districts with Polygon geometries."""
    logger.info("Ingesting corridor districts via OSMnx...")
    cursor = conn.cursor()
    district_geoms = {}

    for d in CORRIDOR_DISTRICTS:
        cursor.execute("SELECT state_id FROM STATE WHERE code = %s;", (d["state_code"],))
        state_id = cursor.fetchone()[0]

        logger.info(f"Geocoding {d['name']}...")
        gdf = ox.geocode_to_gdf(d["query"])
        geom = gdf.geometry.iloc[0]
        # Ensure MultiPolygon or Polygon WKT
        wkt = geom.wkt
        district_geoms[d["name"]] = geom

        cursor.execute("""
            INSERT INTO DISTRICT (state_id, name, geom)
            VALUES (%s, %s, ST_GeomFromText(%s, 4326))
            ON DUPLICATE KEY UPDATE
                geom = ST_GeomFromText(%s, 4326);
        """, (state_id, d["name"], wkt, wkt))
        conn.commit()
        logger.info(f"[+] District '{d['name']}' saved with polygon geometry.")

    cursor.close()
    return district_geoms


def update_road_edge_districts(conn, district_geoms):
    """
    Assigns district_id to ROAD_EDGE records using fast Shapely spatial join.
    """
    logger.info("Assigning district_id to ROAD_EDGE segments using spatial containment...")
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT district_id, name FROM DISTRICT;")
    district_map = {row["name"]: row["district_id"] for row in cursor.fetchall()}

    # Fetch edge_id and start point of each road edge
    cursor.execute("""
        SELECT edge_id, ST_X(ST_StartPoint(geom)) as lon, ST_Y(ST_StartPoint(geom)) as lat
        FROM ROAD_EDGE;
    """)
    edges = cursor.fetchall()
    logger.info(f"Fetched {len(edges)} edges. Matching against {len(district_geoms)} district polygons...")

    # Build STRtree of districts
    dist_names = list(district_geoms.keys())
    dist_polys = [district_geoms[name] for name in dist_names]
    tree = STRtree(dist_polys)

    updates = []
    matched_count = 0

    for edge in edges:
        pt = Point(edge["lon"], edge["lat"])
        # Query matching candidate polygons
        candidates = tree.query(pt)
        assigned_dist_id = None
        for idx in candidates:
            if dist_polys[idx].contains(pt):
                name = dist_names[idx]
                assigned_dist_id = district_map[name]
                matched_count += 1
                break
        if assigned_dist_id is not None:
            updates.append((assigned_dist_id, edge["edge_id"]))

    logger.info(f"Matched {matched_count} / {len(edges)} edges ({matched_count/len(edges)*100:.1f}%) to corridor districts.")

    # Batch update in chunks of 5000
    chunk_size = 5000
    cursor_up = conn.cursor()
    for i in range(0, len(updates), chunk_size):
        chunk = updates[i:i + chunk_size]
        cursor_up.executemany("""
            UPDATE ROAD_EDGE SET district_id = %s WHERE edge_id = %s;
        """, chunk)
        conn.commit()

    cursor_up.close()
    cursor.close()
    logger.info(f"[+] Successfully updated district_id on {len(updates)} road edges.")


def ingest_fuel_prices(conn):
    """Populates official fuel retail selling prices."""
    logger.info("Ingesting official fuel prices...")
    cursor = conn.cursor()
    today = date.today().isoformat()

    for fp in OFFICIAL_FUEL_PRICES:
        cursor.execute("SELECT state_id FROM STATE WHERE code = %s;", (fp["state_code"],))
        state_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO FUEL_PRICE (state_id, fuel_type, price_per_litre, as_of_date, source)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                price_per_litre = VALUES(price_per_litre),
                source = VALUES(source);
        """, (state_id, fp["fuel_type"], fp["price"], today, fp["source"]))

    conn.commit()
    cursor.close()
    logger.info(f"[+] Ingested {len(OFFICIAL_FUEL_PRICES)} fuel price records.")


def ingest_accidents(conn):
    """Populates historical MoRTH accident and casualty statistics."""
    logger.info("Ingesting historical accident records...")
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT district_id, name FROM DISTRICT;")
    district_map = {row["name"]: row["district_id"] for row in cursor.fetchall()}

    cursor_in = conn.cursor()
    source_doc = "MoRTH Road Accidents in India 2022"
    count = 0

    for rec in ACCIDENT_DATA:
        dist_name = rec["district"]
        if dist_name not in district_map:
            continue
        dist_id = district_map[dist_name]
        cursor_in.execute("""
            INSERT INTO ACCIDENT_HISTORICAL (year, district_id, road_category, accidents, fatalities, injuries, source_doc)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                accidents = VALUES(accidents),
                fatalities = VALUES(fatalities),
                injuries = VALUES(injuries);
        """, (rec["year"], dist_id, rec["category"], rec["accidents"], rec["fatalities"], rec["injuries"], source_doc))
        count += 1

    conn.commit()
    cursor_in.close()
    cursor.close()
    logger.info(f"[+] Ingested {count} historical accident records across corridor districts.")


def ingest_blackspots(conn):
    """Populates MoRTH/NHAI officially verified accident blackspots."""
    logger.info("Ingesting verified MoRTH/NHAI blackspots...")
    cursor = conn.cursor()
    count = 0

    for b in CORRIDOR_BLACKSPOTS:
        wkt = f"POINT({b['lon']} {b['lat']})"
        cursor.execute("SELECT blackspot_id FROM BLACKSPOT WHERE name = %s LIMIT 1;", (b["name"],))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
                UPDATE BLACKSPOT
                SET geom = ST_GeomFromText(%s, 4326), source = %s, year = %s
                WHERE blackspot_id = %s;
            """, (wkt, b["source"], b["year"], existing[0]))
        else:
            cursor.execute("""
                INSERT INTO BLACKSPOT (name, geom, source, year)
                VALUES (%s, ST_GeomFromText(%s, 4326), %s, %s);
            """, (b["name"], wkt, b["source"], b["year"]))
        count += 1

    conn.commit()
    cursor.close()
    logger.info(f"[+] Ingested {count} official blackspot locations along NH 48 corridor.")


def run_all():
    conn = get_db_connection()
    try:
        ingest_states(conn)
        district_geoms = ingest_districts(conn)
        update_road_edge_districts(conn, district_geoms)
        ingest_fuel_prices(conn)
        ingest_accidents(conn)
        ingest_blackspots(conn)
        logger.info("=== PHASE 3 STATIC INGESTION COMPLETE ===")
    finally:
        conn.close()


if __name__ == "__main__":
    run_all()
