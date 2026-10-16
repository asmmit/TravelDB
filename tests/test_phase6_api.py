"""
Phase 6 Integration Tests: Flask REST API & Web Application.
Validates all HTTP endpoints, spatial layers, fuel routing, dynamic rerouting,
telemetry pings, and crowdsourced hazard reporting against real MySQL 8.0 and igraph data.
"""

import pytest
import json
import sys
import os

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from web.app import app
from database.db_connection import get_db_connection


@pytest.fixture
def client():
    """Flask test client fixture."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_page_loads(client):
    """Confirms that the Leaflet web dashboard loads with HTTP 200 and required elements."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "TravelDB" in html
    assert "map" in html
    assert "Gas Station Problem" in html or "Journey Configuration" in html


def test_api_stats_and_metadata(client):
    """Validates /api/stats, /api/vehicles, and /api/places endpoints."""
    # 1. Stats
    res_stats = client.get("/api/stats")
    assert res_stats.status_code == 200
    stats_data = res_stats.get_json()
    assert stats_data["status"] == "success"
    s = stats_data["stats"]
    assert s["nodes"] >= 45000
    assert s["directed_edges"] >= 80000
    assert s["fuel_stations"] >= 200
    assert s["blackspots"] >= 10
    assert s["giant_component_pct"] >= 85.0

    # 2. Vehicles
    res_veh = client.get("/api/vehicles")
    assert res_veh.status_code == 200
    veh_data = res_veh.get_json()
    assert veh_data["status"] == "success"
    assert len(veh_data["vehicles"]) >= 3
    make_models = [v["make_model"] for v in veh_data["vehicles"]]
    assert any("Swift" in m for m in make_models)

    # 3. Places
    res_places = client.get("/api/places")
    assert res_places.status_code == 200
    places_data = res_places.get_json()
    assert places_data["status"] == "success"
    assert len(places_data["places"]) >= 6


def test_api_spatial_layers(client):
    """Validates GeoJSON layers for blackspots, fuel stations, and weather."""
    # 1. Blackspots
    res_bs = client.get("/api/layers/blackspots")
    assert res_bs.status_code == 200
    bs_data = res_bs.get_json()
    assert bs_data["status"] == "success"
    assert bs_data["count"] >= 10
    for f in bs_data["features"]:
        assert f["geometry"]["type"] == "Point"
        coords = f["geometry"]["coordinates"]
        assert len(coords) == 2
        # Corridor longitude (79 to 81) and latitude (12.5 to 13.5)
        assert 79.0 <= coords[0] <= 81.0
        assert 12.5 <= coords[1] <= 13.5

    # 2. Fuel Stations
    res_fs = client.get("/api/layers/fuel-stations")
    assert res_fs.status_code == 200
    fs_data = res_fs.get_json()
    assert fs_data["status"] == "success"
    assert fs_data["count"] >= 200

    # 3. Weather
    res_wx = client.get("/api/layers/weather")
    assert res_wx.status_code == 200
    wx_data = res_wx.get_json()
    assert wx_data["status"] == "success"
    assert wx_data["count"] > 0


def test_api_multi_objective_route(client):
    """Validates unconstrained multi-objective routing endpoint (/api/route)."""
    payload = {
        "origin": [13.0474, 80.0937],       # Poonamallee
        "destination": [12.9675, 79.9436],  # Sriperumbudur
        "objective": "fastest",
        "avoid_blackspots": True
    }
    response = client.post("/api/route", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    r = data["route"]
    assert r["distance_km"] > 15.0
    assert r["eta_minutes"] > 0
    assert len(r["polyline"]) > 50
    assert len(r["turn_instructions"]) > 0


def test_api_fuel_planning_ample_fuel(client):
    """Validates fuel planning when fuel is ample (0 refuel stops scheduled)."""
    payload = {
        "origin": [13.0474, 80.0937],       # Poonamallee
        "destination": [12.8973, 79.5067],  # Damal (~80 km)
        "vehicle_id": 1,                    # Swift (17.5 kmpl, 37 L tank)
        "initial_fuel_l": 15.0,
        "reserve_l": 5.0,
        "safety_margin": 0.85,
        "objective": "fastest"
    }
    response = client.post("/api/fuel-plan", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    plan = data["plan"]
    assert plan["trip_id"] is not None
    assert plan["route_plan_id"] is not None
    assert plan["feasible"] is True
    assert plan["refuel_stops_count"] == 0
    assert plan["total_refuel_cost_inr"] == 0.0
    assert plan["estimated_arrival_fuel_l"] > 5.0
    assert len(plan["polyline"]) > 200


def test_api_fuel_planning_constrained_fuel(client):
    """Validates Gas Station Problem solver with constrained initial fuel (scheduled refuel stop)."""
    payload = {
        "origin": [13.0474, 80.0937],       # Poonamallee
        "destination": [12.8973, 79.5067],  # Damal (~80 km)
        "vehicle_id": 1,                    # Swift
        "initial_fuel_l": 4.0,              # Low fuel!
        "reserve_l": 3.0,
        "safety_margin": 0.85,
        "objective": "fastest"
    }
    response = client.post("/api/fuel-plan", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    plan = data["plan"]
    assert plan["trip_id"] is not None
    assert plan["feasible"] is True
    assert plan["refuel_stops_count"] >= 1
    assert plan["total_refuel_cost_inr"] > 1000.0
    assert len(plan["refuel_stops"]) >= 1

    first_stop = plan["refuel_stops"][0]
    assert first_stop["refuel_l"] > 10.0
    assert first_stop["cost_inr"] > 1000.0


def test_api_dynamic_reroute_lifecycle(client):
    """Validates dynamic mid-trip reroute endpoint and audit logging in REROUTE_EVENT."""
    # 1. Create a trip first
    plan_res = client.post("/api/fuel-plan", json={
        "origin": [13.0474, 80.0937],
        "destination": [12.8973, 79.5067],
        "vehicle_id": 1,
        "initial_fuel_l": 15.0,
        "reserve_l": 2.0
    })
    trip_id = plan_res.get_json()["plan"]["trip_id"]

    # 2. Trigger low_fuel reroute near Sriperumbudur
    reroute_payload = {
        "trigger_reason": "low_fuel",
        "current_coords": [12.9675, 79.9436],  # Sriperumbudur
        "current_fuel_l": 3.0,                  # Low fuel drop
        "reason_details": {"alert": "Simulated sudden fuel drop"}
    }
    reroute_res = client.post(f"/api/trip/{trip_id}/reroute", json=reroute_payload)
    assert reroute_res.status_code == 200
    reroute_data = reroute_res.get_json()
    assert reroute_data["status"] == "success"
    r = reroute_data["reroute"]
    assert r["reroute_event_id"] > 0
    assert r["new_route_plan_id"] > r["old_route_plan_id"]
    assert r["new_plan"]["feasible"] is True

    # 3. Verify in MySQL database that REROUTE_EVENT row exists
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM REROUTE_EVENT WHERE event_id = %s;", (r["reroute_event_id"],))
    row = cursor.fetchone()
    assert row is not None
    assert row["trigger_reason"] == "low_fuel"
    assert row["trip_id"] == trip_id

    # 4. Verify trip details endpoint
    trip_res = client.get(f"/api/trips/{trip_id}")
    assert trip_res.status_code == 200
    trip_info = trip_res.get_json()
    assert trip_info["status"] == "success"
    assert len(trip_info["route_plans"]) >= 2
    assert len(trip_info["reroute_events"]) >= 1

    cursor.close()
    conn.close()


def test_api_hazard_reporting_and_telemetry_ping(client):
    """Validates crowdsourced hazard reporting and GPS telemetry ping recording."""
    # 1. Report hazard
    rep_res = client.post("/api/reports", json={
        "report_type": "waterlogging",
        "lat": 12.9348,
        "lon": 79.8450,
        "expires_in_hours": 8
    })
    assert rep_res.status_code == 200
    rep_data = rep_res.get_json()
    assert rep_data["status"] == "success"
    report_id = rep_data["report_id"]
    assert report_id > 0

    # 2. Telemetry ping
    # Create trip first
    plan_res = client.post("/api/fuel-plan", json={
        "origin": [13.0474, 80.0937],
        "destination": [12.9675, 79.9436],
        "vehicle_id": 1,
        "initial_fuel_l": 15.0
    })
    trip_id = plan_res.get_json()["plan"]["trip_id"]

    ping_res = client.post(f"/api/trip/{trip_id}/ping", json={
        "lat": 13.0100,
        "lon": 80.0200,
        "speed_kph": 82.5,
        "fuel_remaining_l": 13.8
    })
    assert ping_res.status_code == 200
    ping_data = ping_res.get_json()
    assert ping_data["status"] == "success"
    assert ping_data["ping_id"] > 0


def test_api_auth_lifecycle(client):
    """Validates user registration, login, and emergency profile endpoints."""
    import time
    ts = int(time.time())
    username = f"driver_{ts}"

    # 1. Register new user
    reg_payload = {
        "username": username,
        "password": "securepassword123",
        "full_name": "Test Driver",
        "age": 22,
        "gender": "Female",
        "phone": "+91 99999 11111",
        "emergency_phone": "+91 99999 22222"
    }
    reg_res = client.post("/api/auth/register", json=reg_payload)
    assert reg_res.status_code == 201
    user = reg_res.get_json()["user"]
    user_id = user["user_id"]
    assert user["username"] == username
    assert user["full_name"] == "Test Driver"
    assert user["emergency_phone"] == "+91 99999 22222"

    # 2. Login
    login_res = client.post("/api/auth/login", json={
        "username": username,
        "password": "securepassword123"
    })
    assert login_res.status_code == 200
    assert login_res.get_json()["user"]["user_id"] == user_id

    # 3. Update profile
    put_res = client.put("/api/auth/profile", json={
        "user_id": user_id,
        "phone": "+91 99999 33333",
        "age": 23
    })
    assert put_res.status_code == 200
    updated = put_res.get_json()["user"]
    assert updated["phone"] == "+91 99999 33333"
    assert updated["age"] == 23


def test_api_saved_trips_crud(client):
    """Validates full CRUD lifecycle for saved trips and travel notes."""
    # 1. Create saved trip
    payload = {
        "user_id": 1,
        "trip_title": "Chennai to Damal Highway Test",
        "origin_name": "Poonamallee",
        "destination_name": "Damal",
        "vehicle_name": "Maruti Swift",
        "distance_km": 80.33,
        "fuel_liters": 4.75,
        "refuel_stops": 1,
        "estimated_cost_inr": 3369.08,
        "trip_notes": "Stop at BPCL for refuel and check tire pressure."
    }
    post_res = client.post("/api/saved-trips", json=payload)
    assert post_res.status_code == 201
    saved_trip = post_res.get_json()["saved_trip"]
    saved_id = saved_trip["saved_trip_id"]
    assert saved_trip["trip_title"] == "Chennai to Damal Highway Test"
    assert saved_trip["refuel_stops"] == 1

    # 2. Get saved trips
    get_res = client.get("/api/saved-trips?user_id=1")
    assert get_res.status_code == 200
    trips = get_res.get_json()["saved_trips"]
    assert any(t["saved_trip_id"] == saved_id for t in trips)

    # 3. Update notes
    put_res = client.put(f"/api/saved-trips/{saved_id}", json={
        "trip_title": "Updated Highway Test",
        "trip_notes": "Tire pressure checked and confirmed."
    })
    assert put_res.status_code == 200
    assert put_res.get_json()["saved_trip"]["trip_notes"] == "Tire pressure checked and confirmed."

    # 4. Delete saved trip
    del_res = client.delete(f"/api/saved-trips/{saved_id}")
    assert del_res.status_code == 200
    assert "deleted" in del_res.get_json()["message"]

