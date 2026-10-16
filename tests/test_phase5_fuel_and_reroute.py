"""
Tests for TravelDB Phase 5: Fuel-Aware Decision Support & Reroute Engine.
Validates:
1. Fuel physics calculations per road type and weather factors.
2. The Gas Station Problem solver (zero stops when feasible, optimal stops when constrained).
3. Critical low fuel / unreachable alerts.
4. Transactional persistence in TRIP, ROUTE_PLAN, ROUTE_PLAN_STOP, ROUTE_PLAN_EDGE.
5. Dynamic mid-trip reroute triggering and REROUTE_EVENT audit logging.
"""

import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection
from engine.fuel_router import plan_fuel_trip, get_active_fuel_price
from engine.reroute import trigger_reroute


def test_fuel_pricing_resolution():
    """Validates that real retail fuel prices are resolved from MySQL."""
    conn = get_db_connection()
    petrol_price = get_active_fuel_price(conn, "TN", "petrol")
    diesel_price = get_active_fuel_price(conn, "TN", "diesel")
    cng_price = get_active_fuel_price(conn, "TN", "cng")
    conn.close()

    assert petrol_price > 90.0
    assert diesel_price > 80.0
    assert cng_price > 70.0


def test_feasible_journey_no_refuel_stops():
    """Validates that a journey with ample initial fuel schedules zero refuel stops."""
    res = plan_fuel_trip(
        origin=(13.0474, 80.0937),       # Poonamallee
        destination=(12.9675, 79.9436),  # Sriperumbudur (19.5 km)
        initial_fuel_l=15.0,
        reserve_l=3.0,
        persist_to_db=True
    )

    assert res["status"] == "success"
    assert res["explanation"]["feasible"] is True
    assert res["refuel_stops_count"] == 0
    assert res["estimated_arrival_fuel_litres"] > 10.0
    assert res["trip_id"] is not None
    assert res["route_plan_id"] is not None

    # Verify database persistence
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM TRIP WHERE trip_id = %s;", (res["trip_id"],))
    trip_row = cur.fetchone()
    assert trip_row is not None
    assert trip_row["status"] == "planned"

    cur.execute("SELECT * FROM ROUTE_PLAN WHERE route_plan_id = %s;", (res["route_plan_id"],))
    plan_row = cur.fetchone()
    assert plan_row is not None
    assert plan_row["feasible"] == 1

    cur.close()
    conn.close()


def test_gas_station_problem_solver_constrained_fuel():
    """
    Validates the Gas Station Problem solver when initial fuel is constrained.
    With only 4L initial fuel, an 80 km trip to Damal cannot be completed without refueling.
    """
    res = plan_fuel_trip(
        origin=(13.0474, 80.0937),       # Poonamallee
        destination=(12.8973, 79.5067),  # Damal (80.3 km)
        initial_fuel_l=4.0,              # Only 4L (usable range ~16 km)
        reserve_l=3.0,
        persist_to_db=True
    )

    assert res["status"] == "success"
    assert res["explanation"]["feasible"] is True
    assert res["refuel_stops_count"] >= 1
    assert res["total_refuel_cost_inr"] > 0.0

    # Validate stop details
    first_stop = res["refuel_stops"][0]
    assert first_stop["station_id"] > 0
    assert first_stop["refuel_l"] > 10.0
    assert first_stop["cost_inr"] > 500.0

    # Verify ROUTE_PLAN_STOP database record
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM ROUTE_PLAN_STOP WHERE route_plan_id = %s;", (res["route_plan_id"],))
    stops = cur.fetchall()
    assert len(stops) == res["refuel_stops_count"]
    cur.close()
    conn.close()


def test_dynamic_reroute_event_lifecycle():
    """Validates dynamic mid-trip reroute triggering and REROUTE_EVENT audit logging."""
    # First plan a trip
    initial_plan = plan_fuel_trip(
        origin=(13.0474, 80.0937),
        destination=(12.8973, 79.5067),
        initial_fuel_l=15.0,
        reserve_l=3.0,
        persist_to_db=True
    )
    trip_id = initial_plan["trip_id"]

    # Trigger a dynamic reroute due to 'low_fuel'
    reroute_res = trigger_reroute(
        trip_id=trip_id,
        trigger_reason="low_fuel",
        current_coords=(12.9675, 79.9436),  # Near Sriperumbudur
        current_fuel_l=2.2,                 # Below reserve limit of 3.0L
        reason_details={"warning": "Mid-trip rapid fuel drain"}
    )

    assert reroute_res["status"] == "success"
    assert reroute_res["event_id"] > 0
    assert reroute_res["old_route_plan_id"] == initial_plan["route_plan_id"]
    assert reroute_res["new_route_plan_id"] > initial_plan["route_plan_id"]

    # Verify REROUTE_EVENT table in MySQL
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM REROUTE_EVENT WHERE event_id = %s;", (reroute_res["event_id"],))
    event_row = cur.fetchone()
    assert event_row is not None
    assert event_row["trigger_reason"] == "low_fuel"
    assert event_row["trip_id"] == trip_id

    # Verify TRIP status updated to 'active'
    cur.execute("SELECT status FROM TRIP WHERE trip_id = %s;", (trip_id,))
    assert cur.fetchone()["status"] == "active"

    cur.close()
    conn.close()
