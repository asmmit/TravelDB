"""
Unit and Integration Tests for TravelDB Environment & Schemas.
Verifies that all required packages, files, migrations, and database connections are sound.
"""

import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

def test_imports():
    """Verify that all core dependencies can be imported cleanly."""
    import osmnx
    import igraph
    import geopandas
    import shapely
    import mysql.connector
    import sqlalchemy
    import pandas
    import dotenv
    assert True

def test_project_structure():
    """Verify that all required project directories and migration files exist."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    
    expected_dirs = [
        os.path.join(base_dir, "database"),
        os.path.join(base_dir, "database", "migrations"),
        os.path.join(base_dir, "ingestion"),
        os.path.join(base_dir, "docs"),
        os.path.join(base_dir, "data", "raw")
    ]
    for d in expected_dirs:
        assert os.path.isdir(d), f"Missing required directory: {d}"

    migration_file = os.path.join(base_dir, "database", "migrations", "001_initial_schema.sql")
    assert os.path.isfile(migration_file), f"Missing migration file: {migration_file}"

def test_sql_migration_syntax():
    """Verify that 001_initial_schema.sql contains valid SQL syntax blocks."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    migration_file = os.path.join(base_dir, "database", "migrations", "001_initial_schema.sql")
    with open(migration_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify critical tables exist in the schema
    critical_tables = [
        "ROAD_NODE", "ROAD_EDGE", "FUEL_STATION", "POI",
        "TRIP", "ROUTE_PLAN", "GPS_PING", "REROUTE_EVENT",
        "TRAFFIC_SAMPLE_POINT", "TRAFFIC_FLOW_SNAPSHOT", "INCIDENT"
    ]
    for table in critical_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in content, f"Table {table} not defined in schema!"

    assert "SRID 4326" in content, "Spatial columns must enforce SRID 4326"
    assert "SPATIAL INDEX" in content, "Spatial indexes must be defined"

def test_database_loaded_entities():
    """Verify that MySQL contains real road network and POI rows from Phase 1 ingestion."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS c FROM ROAD_NODE;")
    nodes_count = cursor.fetchone()['c']
    assert nodes_count > 10000, f"Expected >10,000 nodes, got {nodes_count}"

    cursor.execute("SELECT COUNT(*) AS c FROM ROAD_EDGE;")
    edges_count = cursor.fetchone()['c']
    assert edges_count > 10000, f"Expected >10,000 edges, got {edges_count}"

    cursor.execute("SELECT COUNT(*) AS c FROM FUEL_STATION WHERE nearest_node_id IS NOT NULL;")
    snapped_fuel = cursor.fetchone()['c']
    assert snapped_fuel > 100, f"Expected >100 snapped fuel stations, got {snapped_fuel}"

    cursor.execute("SELECT COUNT(*) AS c FROM POI;")
    poi_count = cursor.fetchone()['c']
    assert poi_count > 100, f"Expected >100 POIs, got {poi_count}"

    cursor.close()
    conn.close()
