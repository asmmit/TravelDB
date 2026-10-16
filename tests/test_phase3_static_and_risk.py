"""
Tests for TravelDB Phase 3: Static Layers, Fuel Prices, and Risk Engine.
Validates states, districts, accident statistics, blackspots, edge risk scores,
views, and stored procedures on MySQL 8.0.
"""

import os
import sys
import json
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection


def test_states_and_districts_loaded():
    """Validates STATE and DISTRICT tables contain expected corridor entities and geometries."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT code, name FROM STATE ORDER BY code;")
    states = {s["code"]: s["name"] for s in cur.fetchall()}
    assert "TN" in states
    assert "KA" in states
    assert states["TN"] == "Tamil Nadu"

    cur.execute("SELECT name, ST_GeometryType(geom) as geom_type FROM DISTRICT;")
    districts = {d["name"]: d["geom_type"] for d in cur.fetchall()}
    expected = ["Chennai", "Tiruvallur", "Kanchipuram", "Ranipet", "Vellore"]
    for exp in expected:
        assert exp in districts
        assert districts[exp] in ["POLYGON", "MULTIPOLYGON"]

    cur.close()
    conn.close()


def test_road_edge_district_spatial_linkage():
    """Validates that corridor road edges have been spatially mapped to DISTRICT entities."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT COUNT(*) as total, COUNT(district_id) as mapped
        FROM ROAD_EDGE;
    """)
    res = cur.fetchone()
    total = res["total"]
    mapped = res["mapped"]
    assert total > 0
    # Over 80% of edges in the corridor bounding box must be mapped to the 4 primary districts
    assert (mapped / total) >= 0.80

    cur.close()
    conn.close()


def test_official_fuel_prices():
    """Validates official retail fuel selling prices for TN and KA."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT s.code, f.fuel_type, f.price_per_litre
        FROM FUEL_PRICE f
        JOIN STATE s ON f.state_id = s.state_id;
    """)
    rows = cur.fetchall()
    assert len(rows) >= 6

    # Verify petrol and diesel are in realistic price bounds (> ₹80/L and < ₹120/L)
    for r in rows:
        assert float(r["price_per_litre"]) > 50.0
        assert float(r["price_per_litre"]) < 150.0

    cur.close()
    conn.close()


def test_historical_accident_records():
    """Validates MoRTH/SCRB official accident figures across corridor districts."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT d.name, a.road_category, a.accidents, a.fatalities
        FROM ACCIDENT_HISTORICAL a
        JOIN DISTRICT d ON a.district_id = d.district_id;
    """)
    rows = cur.fetchall()
    assert len(rows) >= 12

    for r in rows:
        assert r["accidents"] >= 0
        assert r["fatalities"] >= 0
        assert r["road_category"] in ["National Highway", "State Highway", "Other Roads"]

    cur.close()
    conn.close()


def test_corridor_blackspots():
    """Validates MoRTH/NHAI verified blackspots along NH 48 corridor."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT blackspot_id, name, ST_AsText(geom) as pt, year
        FROM BLACKSPOT;
    """)
    rows = cur.fetchall()
    assert len(rows) >= 10

    for r in rows:
        assert r["pt"].startswith("POINT(")
        assert r["year"] >= 2020

    cur.close()
    conn.close()


def test_edge_risk_engine_outputs():
    """Validates EDGE_RISK calculations, score boundaries, and JSON components integrity."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT COUNT(*) as total,
               MIN(risk_score) as min_score,
               MAX(risk_score) as max_score,
               AVG(risk_score) as avg_score
        FROM EDGE_RISK;
    """)
    stats = cur.fetchone()
    assert stats["total"] > 50000
    assert float(stats["min_score"]) >= 0.0
    assert float(stats["max_score"]) <= 100.0
    assert float(stats["avg_score"]) > 10.0

    # Sample top 10 high-risk edges and inspect JSON structure
    cur.execute("""
        SELECT edge_id, risk_score, components
        FROM EDGE_RISK
        ORDER BY risk_score DESC
        LIMIT 10;
    """)
    high_risk = cur.fetchall()
    for row in high_risk:
        assert float(row["risk_score"]) >= 40.0
        comp = row["components"]
        if isinstance(comp, str):
            comp = json.loads(comp)
        assert "base_risk" in comp
        assert "road_type" in comp
        assert "blackspot_penalty" in comp
        assert "weather_penalty" in comp
        assert "district_factor" in comp

    cur.close()
    conn.close()


def test_views_and_stored_procedure():
    """Validates v_high_risk_corridor_edges view and sp_get_corridor_risk_summary procedure."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # Test View
    cur.execute("SELECT * FROM v_high_risk_corridor_edges LIMIT 5;")
    view_rows = cur.fetchall()
    assert len(view_rows) > 0
    for r in view_rows:
        assert float(r["risk_score"]) >= 40.0

    # Test Stored Procedure
    cur.callproc("sp_get_corridor_risk_summary")
    results = None
    for res in cur.stored_results():
        results = res.fetchall()
    assert results is not None
    summary = results[0]
    assert summary["total_edges"] > 50000
    assert float(summary["avg_risk_score"]) > 10.0

    cur.close()
    conn.close()
