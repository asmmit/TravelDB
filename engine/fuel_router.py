"""
Fuel-Aware Decision Support System & Gas Station Problem Solver for TravelDB (Phase 5).
Optimizes corridor trips under vehicle tank capacity, rated mileage, initial fuel,
and safety reserve constraints.
Selects optimal refuel stops from 240+ corridor fuel stations and stores full audit trails in MySQL.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection
from engine.graph_loader import get_road_network
from engine.router import find_route

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("fuel_router")

# Default fuel price fallbacks if not resolved by state
DEFAULT_FUEL_PRICES = {
    "petrol": 100.75,
    "diesel": 92.34,
    "cng": 85.50,
    "electric": 18.00
}


def get_active_fuel_price(conn, state_code="TN", fuel_type="petrol"):
    """Fetches the latest official retail price for state and fuel type."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.price_per_litre
        FROM FUEL_PRICE f
        JOIN STATE s ON f.state_id = s.state_id
        WHERE s.code = %s AND f.fuel_type = %s
        ORDER BY f.as_of_date DESC LIMIT 1;
    """, (state_code, fuel_type))
    row = cursor.fetchone()
    cursor.close()
    if row:
        return float(row["price_per_litre"])
    return DEFAULT_FUEL_PRICES.get(fuel_type, 100.0)


def load_candidate_fuel_stations(conn):
    """Loads all routable fuel stations with coordinates and brands."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT station_id, name, brand, nearest_node_id, snap_dist_m,
               ST_X(geom) as lon, ST_Y(geom) as lat
        FROM FUEL_STATION
        WHERE nearest_node_id IS NOT NULL;
    """)
    stations = cursor.fetchall()
    cursor.close()
    return stations


def plan_fuel_trip(
    origin,
    destination,
    vehicle_id=1,
    user_id=1,
    initial_fuel_l=10.0,
    reserve_l=3.0,
    safety_margin=0.85,
    mode="fuel_safe",
    avoid_blackspots=False,
    persist_to_db=True,
    trip_id=None
):
    """
    Plans a fuel-aware journey, solving the Gas Station Problem when initial fuel is constrained.

    Parameters:
    - origin: (lat, lon) tuple or node_id
    - destination: (lat, lon) tuple or node_id
    - vehicle_id: ID of the vehicle from VEHICLE table
    - user_id: ID of the driver from APP_USER table
    - initial_fuel_l: Liters of fuel currently in tank
    - reserve_l: Reserve threshold (liters); tank must not drop below this
    - safety_margin: Safety multiplier (0.85 = 15% buffer against headwind/traffic)
    - mode: 'fastest' | 'shortest' | 'safest'
    - avoid_blackspots: whether to divert around high-risk collision zones
    - persist_to_db: If True, writes records to TRIP, ROUTE_PLAN, ROUTE_PLAN_STOP, ROUTE_PLAN_EDGE
    """
    t_start = time.time()
    conn = get_db_connection()
    net = get_road_network()
    g = net.graph

    try:
        # 1. Fetch Vehicle Specifications
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM VEHICLE WHERE vehicle_id = %s;", (vehicle_id,))
        vehicle = cursor.fetchone()
        cursor.close()

        if not vehicle:
            # Fallback vehicle specs if vehicle_id not found
            vehicle = {
                "vehicle_id": vehicle_id,
                "user_id": user_id,
                "fuel_type": "petrol",
                "tank_capacity_l": 37.0,
                "rated_mileage_kmpl": 17.5,
                "make_model": "Standard Sedan"
            }

        fuel_type = vehicle["fuel_type"]
        tank_capacity = float(vehicle["tank_capacity_l"])
        mileage = float(vehicle["rated_mileage_kmpl"])
        fuel_price_per_l = get_active_fuel_price(conn, "TN", fuel_type)

        # 2. Compute Primary Route
        if mode in ("shortest", "safest", "fastest"):
            routing_mode = mode
        else:
            routing_mode = "fastest"
        base_route = find_route(origin, destination, mode=routing_mode, avoid_blackspots=avoid_blackspots)

        if base_route["status"] != "success":
            return base_route

        route_edge_ids = base_route["edge_ids"]
        total_km = base_route["distance_km"]
        eta_min = base_route["duration_min"]
        risk_score = base_route["average_risk_score"]

        # 3. Accurate Fuel Consumption Physics per Edge
        total_fuel_needed = 0.0
        edge_fuel_list = []
        road_type_factors = {
            "motorway": 1.05, "motorway_link": 1.10,
            "trunk": 1.00, "trunk_link": 1.10,
            "primary": 1.05, "primary_link": 1.15,
            "secondary": 1.15, "secondary_link": 1.20,
            "tertiary": 1.25, "tertiary_link": 1.30,
            "unclassified": 1.35
        }

        for eid in route_edge_ids:
            e_info = net.edge_map.get(eid)
            if e_info:
                l_km = e_info["length_m"] / 1000.0
                rtype = e_info["road_type"] or "unclassified"
                factor = road_type_factors.get(rtype, 1.10)
                fuel_e = (l_km / mileage) * factor
            else:
                fuel_e = (0.05 / mileage)
            total_fuel_needed += fuel_e
            edge_fuel_list.append(fuel_e)

        total_fuel_needed = round(total_fuel_needed, 2)

        # 4. Feasibility & Gas Station Problem Analysis
        usable_initial_fuel = max(0.0, float(initial_fuel_l) - float(reserve_l)) * float(safety_margin)
        is_feasible_without_stop = usable_initial_fuel >= total_fuel_needed

        refuel_stops = []
        total_refuel_cost = 0.0
        trip_feasible = True
        explanation_notes = []

        if is_feasible_without_stop:
            # Trip is feasible without stopping
            est_arrival_fuel = round(float(initial_fuel_l) - total_fuel_needed, 2)
            explanation_notes.append(
                f"Trip is 100% fuel-feasible on initial tank ({initial_fuel_l:.1f} L). "
                f"Fuel needed: {total_fuel_needed:.2f} L. "
                f"Estimated arrival fuel: {est_arrival_fuel:.2f} L (safely above reserve threshold of {reserve_l:.1f} L). "
                f"Zero refuel stops required."
            )
        else:
            # Vehicle needs refueling! Solve the Gas Station Problem
            explanation_notes.append(
                f"Vehicle is fuel-constrained! Journey requires {total_fuel_needed:.2f} L, but usable initial fuel is only {usable_initial_fuel:.2f} L "
                f"(after holding {reserve_l:.1f} L safety reserve). Evaluating corridor gas stations..."
            )

            all_stations = load_candidate_fuel_stations(conn)

            # Map route vertices and their cumulative distance from origin
            route_node_positions = {}
            cum_dist = 0.0
            for eid in route_edge_ids:
                e_info = net.edge_map.get(eid)
                if e_info:
                    u = e_info["from_node"]
                    v = e_info["to_node"]
                    if u not in route_node_positions:
                        route_node_positions[u] = cum_dist
                    cum_dist += (e_info["length_m"] / 1000.0)
                    route_node_positions[v] = cum_dist

            # Find candidate stations whose nearest_node_id lies directly on or very close to route
            candidate_stations = []
            for s in all_stations:
                nid = s["nearest_node_id"]
                if nid in route_node_positions:
                    dist_along_route = route_node_positions[nid]
                    candidate_stations.append({
                        "station_id": s["station_id"],
                        "name": s["name"] or "Highway Fuel Station",
                        "brand": s["brand"] or "Public Retailer",
                        "nearest_node_id": nid,
                        "dist_along_route_km": dist_along_route,
                        "snap_dist_m": float(s["snap_dist_m"] or 0.0),
                        "lat": float(s["lat"]) if s.get("lat") is not None else None,
                        "lon": float(s["lon"]) if s.get("lon") is not None else None
                    })

            candidate_stations.sort(key=lambda x: x["dist_along_route_km"])

            # Greedy Horizon Refuel Selection
            current_km = 0.0
            current_fuel = float(initial_fuel_l)
            stop_seq = 1
            now = datetime.now()

            while current_km < total_km:
                remaining_km = total_km - current_km
                fuel_for_remaining = (remaining_km / mileage)

                # Check if destination can be reached on current fuel
                usable_fuel = max(0.0, current_fuel - float(reserve_l)) * float(safety_margin)
                if usable_fuel >= fuel_for_remaining:
                    # Can reach destination!
                    current_fuel -= fuel_for_remaining
                    current_km = total_km
                    break

                # Find reachable stations ahead
                max_reachable_km = current_km + (usable_fuel * mileage)
                reachable = [
                    s for s in candidate_stations
                    if current_km < s["dist_along_route_km"] <= max_reachable_km
                ]

                if not reachable:
                    # Stranded! No station reachable within usable fuel
                    trip_feasible = False
                    min_initial_needed = round((candidate_stations[0]["dist_along_route_km"] / mileage) + reserve_l + 0.5, 1) if candidate_stations else 5.0
                    explanation_notes.append(
                        f"CRITICAL WARNING: Vehicle will run out of fuel! No reachable fuel station found between KM {current_km:.1f} and maximum range KM {max_reachable_km:.1f}. "
                        f"Initial fuel of {initial_fuel_l:.1f} L is insufficient. Minimum required initial fuel to reach the first pump: {min_initial_needed:.1f} L."
                    )
                    break

                # Pick the furthest reachable station (to minimize unnecessary stops)
                best_station = reachable[-1]
                leg_km = best_station["dist_along_route_km"] - current_km
                fuel_burnt = (leg_km / mileage)
                current_fuel -= fuel_burnt
                current_km = best_station["dist_along_route_km"]

                # Refuel to full tank capacity
                fuel_to_add = round(tank_capacity - current_fuel, 2)
                cost = round(fuel_to_add * fuel_price_per_l, 2)
                total_refuel_cost += cost

                # Estimated arrival time
                leg_mins = (leg_km / 70.0) * 60.0  # Approx highway speed
                est_arrival = now + timedelta(minutes=leg_mins * stop_seq)

                refuel_stops.append({
                    "seq": stop_seq,
                    "station_id": best_station["station_id"],
                    "station_name": best_station["name"],
                    "brand": best_station["brand"],
                    "lat": best_station["lat"],
                    "lon": best_station["lon"],
                    "distance_from_origin_km": round(best_station["dist_along_route_km"], 2),
                    "at_distance_km": round(best_station["dist_along_route_km"], 1),
                    "arrival_fuel_l": round(current_fuel, 2),
                    "refuel_l": fuel_to_add,
                    "refuel_liters_added": fuel_to_add,
                    "price_per_l": fuel_price_per_l,
                    "cost_inr": cost,
                    "estimated_cost_inr": cost,
                    "estimated_arrival": est_arrival.strftime("%Y-%m-%d %H:%M:%S")
                })

                explanation_notes.append(
                    f"Stop #{stop_seq}: Refuel at {best_station['name']} ({best_station['brand']}) at KM {best_station['dist_along_route_km']:.1f}. "
                    f"Arrive with {current_fuel:.2f} L; add {fuel_to_add:.2f} L (cost: INR {cost:.2f}); depart with full tank ({tank_capacity:.1f} L)."
                )

                current_fuel = tank_capacity
                stop_seq += 1

            est_arrival_fuel = round(current_fuel, 2)

        explanation_json = {
            "feasible": trip_feasible,
            "vehicle": vehicle["make_model"],
            "fuel_type": fuel_type,
            "tank_capacity_l": tank_capacity,
            "rated_mileage_kmpl": mileage,
            "initial_fuel_l": float(initial_fuel_l),
            "reserve_threshold_l": float(reserve_l),
            "total_fuel_needed_l": total_fuel_needed,
            "refuel_stops_count": len(refuel_stops),
            "total_refuel_cost_inr": round(total_refuel_cost, 2),
            "estimated_arrival_fuel_l": est_arrival_fuel,
            "notes": explanation_notes
        }

        # 5. Transactional Persistence to MySQL 8.0
        route_plan_id = None

        if persist_to_db:
            orig_node_id = base_route["origin"]["node_id"]
            dest_node_id = base_route["destination"]["node_id"]

            cur_tx = conn.cursor()

            # Insert TRIP record only if trip_id is not already provided (e.g. initial plan)
            if trip_id is None:
                cur_tx.execute("""
                    INSERT INTO TRIP (user_id, vehicle_id, origin_node, dest_node, initial_fuel_l, reserve_l, safety_margin, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'planned');
                """, (user_id, vehicle_id, orig_node_id, dest_node_id, initial_fuel_l, reserve_l, safety_margin))
                trip_id = cur_tx.lastrowid

            # Insert ROUTE_PLAN record
            cur_tx.execute("""
                INSERT INTO ROUTE_PLAN (trip_id, strategy, total_km, eta_min, fuel_needed_l, risk_score, feasible, explanation)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (trip_id, mode, total_km, eta_min, total_fuel_needed, risk_score, 1 if trip_feasible else 0, json.dumps(explanation_json)))
            route_plan_id = cur_tx.lastrowid

            # Insert ROUTE_PLAN_STOP records
            for s in refuel_stops:
                cur_tx.execute("""
                    INSERT INTO ROUTE_PLAN_STOP (route_plan_id, seq, station_id, refuel_l, estimated_arrival)
                    VALUES (%s, %s, %s, %s, %s);
                """, (route_plan_id, s["seq"], s["station_id"], s["refuel_l"], s["estimated_arrival"]))

            # Insert ROUTE_PLAN_EDGE records in batches of 1000
            edge_chunks = []
            for seq_order, eid in enumerate(route_edge_ids, start=1):
                edge_chunks.append((route_plan_id, seq_order, eid))

            for i in range(0, len(edge_chunks), 1000):
                cur_tx.executemany("""
                    INSERT INTO ROUTE_PLAN_EDGE (route_plan_id, seq, edge_id)
                    VALUES (%s, %s, %s);
                """, edge_chunks[i:i + 1000])

            conn.commit()
            cur_tx.close()
            logger.info(f"[+] Persisted TRIP #{trip_id} and ROUTE_PLAN #{route_plan_id} with {len(refuel_stops)} refuel stops.")

        total_calc_ms = round((time.time() - t_start) * 1000.0, 2)

        return {
            "status": "success" if trip_feasible else "infeasible",
            "trip_id": trip_id,
            "route_plan_id": route_plan_id,
            "mode": mode,
            "total_distance_km": total_km,
            "total_duration_min": eta_min,
            "average_risk_score": risk_score,
            "total_fuel_needed_litres": total_fuel_needed,
            "initial_fuel_litres": float(initial_fuel_l),
            "reserve_threshold_litres": float(reserve_l),
            "estimated_arrival_fuel_litres": est_arrival_fuel,
            "refuel_stops_count": len(refuel_stops),
            "total_refuel_cost_inr": round(total_refuel_cost, 2),
            "refuel_stops": refuel_stops,
            "explanation": explanation_json,
            "polyline": base_route["polyline"],
            "instructions": base_route["instructions"],
            "edge_ids": route_edge_ids,
            "dijkstra_latency_ms": base_route["dijkstra_latency_ms"],
            "total_calc_ms": total_calc_ms
        }

    finally:
        conn.close()


if __name__ == "__main__":
    print("\n--- TEST CASE 1: Feasible Journey (15 Liters) ---")
    res1 = plan_fuel_trip(
        origin=(13.0474, 80.0937),       # Poonamallee
        destination=(12.8973, 79.5067),  # Damal (80 km)
        initial_fuel_l=15.0,
        reserve_l=3.0,
        mode="fuel_safe"
    )
    print(f"Status: {res1['status']} | Feasible: {res1['explanation']['feasible']}")
    print(f"Distance: {res1['total_distance_km']} km | Fuel Needed: {res1['total_fuel_needed_litres']} L")
    print(f"Refuel Stops: {res1['refuel_stops_count']} | Arrival Fuel: {res1['estimated_arrival_fuel_litres']} L")
    for note in res1['explanation']['notes']:
        print(f"  * {note}")

    print("\n--- TEST CASE 2: Fuel-Constrained Journey (4 Liters) ---")
    res2 = plan_fuel_trip(
        origin=(13.0474, 80.0937),       # Poonamallee
        destination=(12.8973, 79.5067),  # Damal (80 km)
        initial_fuel_l=4.0,              # Only 4L in tank! (Can only drive ~16 km before reserve)
        reserve_l=3.0,
        mode="fuel_safe"
    )
    print(f"Status: {res2['status']} | Feasible: {res2['explanation']['feasible']}")
    print(f"Distance: {res2['total_distance_km']} km | Fuel Needed: {res2['total_fuel_needed_litres']} L")
    print(f"Refuel Stops: {res2['refuel_stops_count']} | Cost: INR {res2['total_refuel_cost_inr']}")
    for note in res2['explanation']['notes']:
        print(f"  * {note}")
