"""
Unit and Integration Tests for Phase 2 Live Ingestion Pipeline.
Verifies:
1. Open-Meteo real live weather ingestion into WEATHER_OBS and INGESTION_RUN.
2. Real TomTom Traffic Flow payload processing & congestion index math.
3. Real TomTom Incident payload parsing, deduplication, and edge snapping.
4. Graceful degradation when external API keys are unconfigured.
"""

import os
import sys
import json
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection
from ingestion.weather_ingest import fetch_and_store_weather
from ingestion.traffic_ingest import process_traffic_flow_payload, poll_traffic_flow
from ingestion.incident_ingest import process_incidents_payload, poll_incidents

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def test_weather_live_ingestion():
    """Verify that Open-Meteo fetches real weather metrics and records to MySQL."""
    fetch_and_store_weather()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Verify WEATHER_OBS table contains fresh records
    cursor.execute("SELECT COUNT(*) AS c FROM WEATHER_OBS;")
    count = cursor.fetchone()['c']
    assert count >= 7, f"Expected at least 7 weather observations, got {count}"

    # Verify latest INGESTION_RUN status
    cursor.execute("""
        SELECT status, rows_in, error_message
        FROM INGESTION_RUN
        WHERE source = 'open_meteo_weather'
        ORDER BY run_id DESC
        LIMIT 1;
    """)
    run = cursor.fetchone()
    assert run['status'] == 'success', f"Ingestion run failed: {run['error_message']}"
    assert run['rows_in'] > 0, f"Expected at least 1 observation, got {run['rows_in']}"

    cursor.close()
    conn.close()

def test_traffic_flow_fixture_processing():
    """Verify traffic flow payload parsing and congestion index calculation."""
    fixture_path = os.path.join(FIXTURES_DIR, "tomtom_flow_sample.json")
    with open(fixture_path, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get an existing sample point ID
    cursor.execute("SELECT sample_point_id FROM TRAFFIC_SAMPLE_POINT LIMIT 1;")
    sample_pt = cursor.fetchone()
    assert sample_pt is not None, "TRAFFIC_SAMPLE_POINT must be initialized"
    pt_id = sample_pt['sample_point_id']

    # Process payload
    ok, snapshot_id = process_traffic_flow_payload(pt_id, payload, cursor, source='fixture_test')
    assert ok is True
    conn.commit()

    # Verify snapshot in MySQL
    cursor.execute("""
        SELECT current_speed, free_flow_speed, congestion_index, confidence, source
        FROM TRAFFIC_FLOW_SNAPSHOT
        WHERE snapshot_id = %s;
    """, (snapshot_id,))
    snap = cursor.fetchone()
    assert snap is not None
    assert float(snap['current_speed']) == 68.0
    assert float(snap['free_flow_speed']) == 82.0
    # Expected congestion_index = 1 - 68/82 = 0.1707 -> 0.171
    assert abs(float(snap['congestion_index']) - 0.171) < 0.01
    assert float(snap['confidence']) == 0.94

    cursor.close()
    conn.close()

def test_incident_fixture_processing_and_deduplication():
    """Verify incident parsing, spatial edge association, and idempotency / deduplication."""
    fixture_path = os.path.join(FIXTURES_DIR, "tomtom_incident_sample.json")
    with open(fixture_path, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    incidents_list = payload.get("incidents", [])

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. First Pass: Ingestion
    ins1, _ = process_incidents_payload(incidents_list, cursor, source='fixture_test')
    conn.commit()
    assert ins1 == 2, f"Expected 2 incidents processed, got {ins1}"

    # Verify records in INCIDENT table
    cursor.execute("""
        SELECT source_incident_id, category, severity, is_active
        FROM INCIDENT
        WHERE source = 'fixture_test';
    """)
    rows = {r['source_incident_id']: r for r in cursor.fetchall()}
    assert "tt_inc_nh48_001" in rows
    assert rows["tt_inc_nh48_001"]['category'] == 'accident'
    assert rows["tt_inc_nh48_001"]['is_active'] == 1

    assert "tt_inc_nh48_002" in rows
    assert rows["tt_inc_nh48_002"]['category'] == 'road_works'

    # 2. Second Pass: Deduplication test (same payload must not create duplicate primary/unique keys)
    ins2, _ = process_incidents_payload(incidents_list, cursor, source='fixture_test')
    conn.commit()

    cursor.execute("SELECT COUNT(*) AS c FROM INCIDENT WHERE source = 'fixture_test';")
    total_count = cursor.fetchone()['c']
    assert total_count == 2, f"Expected 2 deduplicated records, got {total_count}"

    cursor.close()
    conn.close()

def test_graceful_degradation_without_api_keys():
    """Verify that unconfigured third-party feeds fail safely without crashing."""
    # With default placeholder key, traffic flow returns False and logs error cleanly
    res_traffic = poll_traffic_flow()
    assert res_traffic is False

    res_incident = poll_incidents()
    assert res_incident is False

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT status, error_message
        FROM INGESTION_RUN
        WHERE source IN ('tomtom_traffic_flow', 'tomtom_incidents')
        ORDER BY run_id DESC
        LIMIT 2;
    """)
    runs = cursor.fetchall()
    assert len(runs) == 2
    for r in runs:
        assert r['status'] == 'failed'
        assert 'not configured' in r['error_message']

    cursor.close()
    conn.close()
