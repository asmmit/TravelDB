"""
Dynamic Rerouting Engine for TravelDB (Phase 5).
Monitors active trips and evaluates reroute triggers:
1. 'low_fuel': Actual fuel burns faster than planned, requiring immediate refuel diversion.
2. 'closure' / 'incident': Active road segment blocked by crash or hazard.
3. 'traffic': Major congestion delay exceeding threshold.
4. 'manual': Driver manually requests route re-optimization.
Computes new optimal route plan and records an audit trail in REROUTE_EVENT.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection
from engine.graph_loader import get_road_network
from engine.fuel_router import plan_fuel_trip

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("reroute")


def trigger_reroute(
    trip_id,
    trigger_reason,
    current_coords,
    current_fuel_l,
    blocked_edge_ids=None,
    reason_details=None
):
    """
    Executes a dynamic reroute for an active trip.

    Parameters:
    - trip_id: ID of the trip in TRIP table
    - trigger_reason: 'low_fuel' | 'incident' | 'closure' | 'traffic' | 'manual' | 'off_route'
    - current_coords: (lat, lon) tuple of vehicle's current location
    - current_fuel_l: Liters of fuel currently in the tank
    - blocked_edge_ids: list of edge_ids to avoid/block (e.g. incident closures)
    - reason_details: optional dict with additional diagnostic context

    Returns:
    Dictionary containing reroute event details, comparison with previous plan, and new plan ID.
    """
    t_start = time.time()
    conn = get_db_connection()
    net = get_road_network()

    try:
        cursor = conn.cursor(dictionary=True)

        # 1. Fetch Existing Trip and Latest Route Plan
        cursor.execute("SELECT * FROM TRIP WHERE trip_id = %s;", (trip_id,))
        trip = cursor.fetchone()
        if not trip:
            raise ValueError(f"Trip #{trip_id} not found in database.")

        cursor.execute("""
            SELECT * FROM ROUTE_PLAN
            WHERE trip_id = %s
            ORDER BY route_plan_id DESC LIMIT 1;
        """, (trip_id,))
        old_plan = cursor.fetchone()
        old_plan_id = old_plan["route_plan_id"] if old_plan else None
        cursor.close()

        dest_node_id = trip["dest_node"]
        dest_coords = net.get_vertex_coords(net.node_id_to_idx[dest_node_id])
        user_id = trip["user_id"]
        vehicle_id = trip["vehicle_id"]
        reserve_l = float(trip["reserve_l"])
        safety_margin = float(trip["safety_margin"])

        logger.info(f"Triggering reroute for Trip #{trip_id} (Reason: {trigger_reason}) from {current_coords} with {current_fuel_l:.2f}L...")

        # 2. Compute New Route Plan from Current Location
        new_plan_result = plan_fuel_trip(
            origin=current_coords,
            destination=dest_coords,
            vehicle_id=vehicle_id,
            user_id=user_id,
            initial_fuel_l=current_fuel_l,
            reserve_l=reserve_l,
            safety_margin=safety_margin,
            mode="fuel_safe",
            persist_to_db=True,
            trip_id=trip_id
        )

        new_plan_id = new_plan_result["route_plan_id"]

        # 3. Formulate Reroute Narrative
        explanation_text = (
            f"Dynamic reroute triggered due to '{trigger_reason}'. "
            f"Vehicle position: {current_coords}, current fuel: {current_fuel_l:.2f} L. "
            f"Old Plan #{old_plan_id} superseded by New Plan #{new_plan_id}. "
            f"New path: {new_plan_result['total_distance_km']:.2f} km, {new_plan_result['total_duration_min']:.1f} mins, "
            f"{new_plan_result['refuel_stops_count']} refuel stop(s) scheduled."
        )

        details_payload = reason_details or {}
        details_payload.update({
            "current_coords": list(current_coords),
            "current_fuel_l": current_fuel_l,
            "blocked_edges": blocked_edge_ids or [],
            "old_km": float(old_plan["total_km"]) if old_plan else None,
            "new_km": new_plan_result["total_distance_km"],
            "new_eta_min": new_plan_result["total_duration_min"],
            "refuel_stops_count": new_plan_result["refuel_stops_count"]
        })

        # 4. Record Audit Entry in REROUTE_EVENT
        cur_event = conn.cursor()
        cur_event.execute("""
            INSERT INTO REROUTE_EVENT (trip_id, trigger_reason, details, old_route_plan_id, new_route_plan_id, explanation)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (
            trip_id,
            trigger_reason,
            json.dumps(details_payload),
            old_plan_id,
            new_plan_id,
            explanation_text
        ))
        event_id = cur_event.lastrowid

        # Update Trip status to 'active'
        cur_event.execute("UPDATE TRIP SET status = 'active' WHERE trip_id = %s;", (trip_id,))
        conn.commit()
        cur_event.close()

        logger.info(f"[+] REROUTE_EVENT #{event_id} logged. Trip #{trip_id} updated to active.")

        return {
            "status": "success",
            "event_id": event_id,
            "trip_id": trip_id,
            "trigger_reason": trigger_reason,
            "old_route_plan_id": old_plan_id,
            "new_route_plan_id": new_plan_id,
            "explanation": explanation_text,
            "new_plan": new_plan_result
        }

    finally:
        conn.close()


if __name__ == "__main__":
    print("\n--- SIMULATING MID-TRIP LOW-FUEL REROUTE EVENT ---")
    # Simulate a driver who started with 15L (Trip #3), but at Sriperumbudur has only 2.5L remaining
    # (below safety reserve threshold), requiring an emergency diversion to the nearest pump!
    reroute_res = trigger_reroute(
        trip_id=3,
        trigger_reason="low_fuel",
        current_coords=(12.9675, 79.9436),  # Sriperumbudur
        current_fuel_l=2.5,                 # Critical fuel drop!
        reason_details={"sensor_reading_ts": datetime.now().isoformat(), "warning": "Low fuel sensor triggered"}
    )
    print(f"Reroute Event ID: #{reroute_res['event_id']}")
    print(f"Trigger: {reroute_res['trigger_reason']}")
    print(f"Explanation: {reroute_res['explanation']}")
    print(f"New Plan Stops: {reroute_res['new_plan']['refuel_stops_count']} stops scheduled.")
