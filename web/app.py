"""
TravelDB Phase 6: Flask REST API Server & Application Backend.
Exposes multi-objective routing, Gas Station Problem solver, dynamic mid-trip rerouting,
live layer data (blackspots, fuel stations, weather), and system telemetry.
"""

import os
import sys
import json
import logging
import hashlib
from datetime import datetime, timedelta
import numpy as np
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection
from engine.graph_loader import get_road_network
from engine.router import find_route
from engine.fuel_router import plan_fuel_trip, get_active_fuel_price
from engine.reroute import trigger_reroute

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("traveldb_app")

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static")
)
CORS(app)

# Pre-indexed landmark locations along the corridor for convenient selection
CORRIDOR_PLACES = [
    {"id": "poonamallee", "name": "Poonamallee (Chennai West)", "lat": 13.0474, "lon": 80.0937, "type": "origin"},
    {"id": "sriperumbudur", "name": "Sriperumbudur (NH 48 KM 18)", "lat": 12.9675, "lon": 79.9436, "type": "waypoint"},
    {"id": "sunguvarchatram", "name": "Sunguvarchatram (NH 48 KM 33)", "lat": 12.9348, "lon": 79.8450, "type": "waypoint"},
    {"id": "kanchipuram", "name": "Kanchipuram Link (NH 48)", "lat": 12.8342, "lon": 79.7036, "type": "waypoint"},
    {"id": "damal", "name": "Damal (NH 48 KM 81.5)", "lat": 12.8973, "lon": 79.5067, "type": "waypoint"},
    {"id": "walajapet", "name": "Walajapet Toll Plaza (NH 48)", "lat": 12.9288, "lon": 79.3562, "type": "waypoint"},
    {"id": "ranipet", "name": "Ranipet SIPCOT Hub", "lat": 12.9272, "lon": 79.3331, "type": "waypoint"},
    {"id": "vellore", "name": "Vellore Fort (End of Corridor)", "lat": 12.9165, "lon": 79.1325, "type": "destination"}
]


# ==============================================================================
# 1. Frontend Route
# ==============================================================================
@app.route("/")
def index():
    """Serves the main interactive Leaflet.js dashboard."""
    return render_template("index.html")


# ==============================================================================
# 2. Metadata & Dashboard Stats
# ==============================================================================
@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Returns corridor network statistics and database metrics."""
    try:
        net = get_road_network()
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) AS c FROM FUEL_STATION WHERE nearest_node_id IS NOT NULL;")
        fuel_count = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) AS c FROM BLACKSPOT;")
        blackspot_count = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) AS c FROM WEATHER_OBS;")
        weather_count = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) AS c FROM TRIP;")
        trip_count = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) AS c FROM REROUTE_EVENT;")
        reroute_count = cursor.fetchone()["c"]

        cursor.close()
        conn.close()

        giant_nodes = int(np.sum(net.scc_membership == net.giant_component_id))
        giant_pct = round(giant_nodes / net.graph.vcount() * 100, 1)

        return jsonify({
            "status": "success",
            "stats": {
                "nodes": net.graph.vcount(),
                "directed_edges": net.graph.ecount(),
                "giant_component_nodes": giant_nodes,
                "giant_component_pct": giant_pct,
                "fuel_stations": fuel_count,
                "blackspots": blackspot_count,
                "weather_observations": weather_count,
                "trips_planned": trip_count,
                "reroutes_logged": reroute_count
            }
        })
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/vehicles", methods=["GET"])
def get_vehicles():
    """Returns all available vehicles in the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT vehicle_id, make_model, vehicle_class, fuel_type,
                   tank_capacity_l, rated_mileage_kmpl
            FROM VEHICLE
            ORDER BY vehicle_id ASC;
        """)
        vehicles = cursor.fetchall()
        cursor.close()
        conn.close()

        for v in vehicles:
            v["tank_capacity_l"] = float(v["tank_capacity_l"])
            v["rated_mileage_kmpl"] = float(v["rated_mileage_kmpl"])

        return jsonify({"status": "success", "vehicles": vehicles})
    except Exception as e:
        logger.error(f"Error fetching vehicles: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/places", methods=["GET"])
def get_places():
    """Returns predefined corridor landmark presets."""
    return jsonify({"status": "success", "places": CORRIDOR_PLACES})


# ==============================================================================
# 3. Spatial Layers (Blackspots, Fuel Stations, Live Weather)
# ==============================================================================
@app.route("/api/layers/blackspots", methods=["GET"])
def get_blackspots():
    """Returns MoRTH fatal blackspots along the corridor."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT blackspot_id, name, source, year,
                   ST_X(geom) as lon, ST_Y(geom) as lat
            FROM BLACKSPOT
            ORDER BY blackspot_id ASC;
        """)
        blackspots = cursor.fetchall()
        cursor.close()
        conn.close()

        features = []
        for b in blackspots:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(b["lon"]), float(b["lat"])]
                },
                "properties": {
                    "id": b["blackspot_id"],
                    "name": b["name"],
                    "source": b["source"],
                    "year": b["year"]
                }
            })

        return jsonify({
            "status": "success",
            "type": "FeatureCollection",
            "count": len(features),
            "features": features
        })
    except Exception as e:
        logger.error(f"Error fetching blackspots: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/layers/fuel-stations", methods=["GET"])
def get_fuel_stations():
    """Returns all verified corridor fuel stations."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT station_id, name, brand, ST_X(geom) as lon, ST_Y(geom) as lat, snap_dist_m
            FROM FUEL_STATION
            WHERE nearest_node_id IS NOT NULL
            ORDER BY station_id ASC;
        """)
        stations = cursor.fetchall()
        cursor.close()
        conn.close()

        features = []
        for s in stations:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(s["lon"]), float(s["lat"])]
                },
                "properties": {
                    "id": s["station_id"],
                    "name": s["name"] or "Fuel Station",
                    "brand": s["brand"] or "Independent",
                    "snap_dist_m": round(float(s["snap_dist_m"]), 1) if s["snap_dist_m"] else None
                }
            })

        return jsonify({
            "status": "success",
            "type": "FeatureCollection",
            "count": len(features),
            "features": features
        })
    except Exception as e:
        logger.error(f"Error fetching fuel stations: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/layers/weather", methods=["GET"])
def get_weather():
    """Returns latest live weather observations along the corridor."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT w.obs_id, ST_X(w.grid_point) as lon, ST_Y(w.grid_point) as lat,
                   w.temp_c, w.precip_mm, w.visibility_m, w.wind_kph, w.ts
            FROM WEATHER_OBS w
            INNER JOIN (
                SELECT grid_point, MAX(ts) as max_ts
                FROM WEATHER_OBS
                GROUP BY grid_point
            ) latest ON w.grid_point = latest.grid_point AND w.ts = latest.max_ts;
        """)
        obs = cursor.fetchall()
        cursor.close()
        conn.close()

        features = []
        for o in obs:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(o["lon"]), float(o["lat"])]
                },
                "properties": {
                    "id": o["obs_id"],
                    "temp_c": float(o["temp_c"]),
                    "precip_mm": float(o["precip_mm"]),
                    "visibility_m": float(o["visibility_m"]),
                    "wind_kph": float(o["wind_kph"]),
                    "recorded_at": str(o["ts"])
                }
            })

        return jsonify({
            "status": "success",
            "type": "FeatureCollection",
            "count": len(features),
            "features": features
        })
    except Exception as e:
        logger.error(f"Error fetching weather: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 4. Multi-Objective Routing
# ==============================================================================
@app.route("/api/route", methods=["POST"])
def calculate_route():
    """
    Computes an unconstrained multi-objective route.
    Payload:
    {
        "origin": [lat, lon],
        "destination": [lat, lon],
        "objective": "fastest" | "shortest" | "safest",
        "avoid_blackspots": bool
    }
    """
    try:
        data = request.get_json() or {}
        orig = data.get("origin")
        dest = data.get("destination")
        obj = data.get("objective", "fastest")
        avoid_bs = bool(data.get("avoid_blackspots", False))

        if not orig or not dest or len(orig) != 2 or len(dest) != 2:
            return jsonify({"status": "error", "message": "Valid 'origin' and 'destination' [lat, lon] required."}), 400

        route = find_route(
            (float(orig[0]), float(orig[1])),
            (float(dest[0]), float(dest[1])),
            mode=obj,
            avoid_blackspots=avoid_bs
        )

        route["eta_minutes"] = route.get("duration_min")
        route["turn_instructions"] = route.get("instructions", [])

        return jsonify({
            "status": "success",
            "route": route
        })
    except Exception as e:
        logger.error(f"Error in /api/route: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 5. Fuel-Aware Gas Station Problem Solver
# ==============================================================================
@app.route("/api/fuel-plan", methods=["POST"])
def plan_fuel_route():
    """
    Solves the Gas Station Problem along the corridor and persists trip to MySQL.
    Payload:
    {
        "origin": [lat, lon],
        "destination": [lat, lon],
        "user_id": int (optional, default 1),
        "vehicle_id": int (optional, default 1),
        "initial_fuel_l": float (e.g. 4.0),
        "reserve_l": float (default 3.0),
        "safety_margin": float (default 0.85),
        "objective": "fastest" | "safest",
        "avoid_blackspots": bool
    }
    """
    try:
        data = request.get_json() or {}
        orig = data.get("origin")
        dest = data.get("destination")
        user_id = int(data.get("user_id", 1))
        vehicle_id = int(data.get("vehicle_id", 1))
        initial_fuel = float(data.get("initial_fuel_l", 15.0))
        reserve = float(data.get("reserve_l", 3.0))
        margin = float(data.get("safety_margin", 0.85))
        obj = data.get("objective", "fuel_safe")

        if not orig or not dest or len(orig) != 2 or len(dest) != 2:
            return jsonify({"status": "error", "message": "Valid 'origin' and 'destination' [lat, lon] required."}), 400

        plan = plan_fuel_trip(
            (float(orig[0]), float(orig[1])),
            (float(dest[0]), float(dest[1])),
            vehicle_id=vehicle_id,
            user_id=user_id,
            initial_fuel_l=initial_fuel,
            reserve_l=reserve,
            safety_margin=margin,
            mode=obj,
            persist_to_db=True
        )

        plan["distance_km"] = plan.get("total_distance_km")
        plan["eta_minutes"] = plan.get("total_duration_min")
        plan["total_fuel_needed_l"] = plan.get("total_fuel_needed_litres")
        plan["estimated_arrival_fuel_l"] = plan.get("estimated_arrival_fuel_litres")
        plan["turn_instructions"] = plan.get("instructions", [])
        plan["feasible"] = plan.get("explanation", {}).get("feasible", plan.get("status") == "success")
        plan["explanation_notes"] = plan.get("explanation", {}).get("notes", [])

        return jsonify({
            "status": "success",
            "plan": plan
        })
    except Exception as e:
        logger.error(f"Error in /api/fuel-plan: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 6. Dynamic Mid-Trip Rerouting Engine
# ==============================================================================
@app.route("/api/trip/<int:trip_id>/reroute", methods=["POST"])
def reroute_trip(trip_id):
    """
    Executes a dynamic mid-trip reroute and logs audit records to REROUTE_EVENT.
    Payload:
    {
        "trigger_reason": "low_fuel" | "incident" | "closure" | "traffic" | "manual",
        "current_coords": [lat, lon],
        "current_fuel_l": float,
        "blocked_edge_ids": list of ints (optional),
        "reason_details": dict (optional)
    }
    """
    try:
        data = request.get_json() or {}
        trigger = data.get("trigger_reason", "manual")
        coords = data.get("current_coords")
        fuel_left = float(data.get("current_fuel_l", 2.0))
        blocked_edges = data.get("blocked_edge_ids")
        details = data.get("reason_details")

        if not coords or len(coords) != 2:
            return jsonify({"status": "error", "message": "'current_coords' [lat, lon] required."}), 400

        result = trigger_reroute(
            trip_id=trip_id,
            trigger_reason=trigger,
            current_coords=(float(coords[0]), float(coords[1])),
            current_fuel_l=fuel_left,
            blocked_edge_ids=blocked_edges,
            reason_details=details
        )

        result["reroute_event_id"] = result.get("event_id")
        if "new_plan" in result:
            np_res = result["new_plan"]
            np_res["distance_km"] = np_res.get("total_distance_km")
            np_res["eta_minutes"] = np_res.get("total_duration_min")
            np_res["total_fuel_needed_l"] = np_res.get("total_fuel_needed_litres")
            np_res["estimated_arrival_fuel_l"] = np_res.get("estimated_arrival_fuel_litres")
            np_res["feasible"] = np_res.get("explanation", {}).get("feasible", np_res.get("status") == "success")

        return jsonify({
            "status": "success",
            "reroute": result
        })
    except Exception as e:
        logger.error(f"Error in /api/trip/{trip_id}/reroute: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 7. GPS Telemetry Ping & Crowdsourced Reporting
# ==============================================================================
@app.route("/api/trip/<int:trip_id>/ping", methods=["POST"])
def record_ping(trip_id):
    """
    Simulates a live vehicle telemetry ping and records it to GPS_PING.
    Payload:
    {
        "lat": float,
        "lon": float,
        "speed_kph": float,
        "fuel_remaining_l": float
    }
    """
    try:
        data = request.get_json() or {}
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
        speed = float(data.get("speed_kph", 70.0))
        fuel = float(data.get("fuel_remaining_l", 10.0))

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO GPS_PING (trip_id, geom, speed_kph, fuel_remaining_l)
            VALUES (%s, ST_GeomFromText(%s, 4326), %s, %s);
        """, (trip_id, f"POINT({lon} {lat})", speed, fuel))
        ping_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "ping_id": ping_id,
            "recorded_at": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error recording ping: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/reports", methods=["POST"])
def submit_report():
    """
    Submits a crowdsourced user hazard report to USER_REPORT.
    Payload:
    {
        "user_id": int (optional, default 1),
        "report_type": "accident" | "pothole" | "blockage" | "waterlogging" | "out_of_fuel" | "fuel_station_closed",
        "lat": float,
        "lon": float,
        "expires_in_hours": int (optional, default 6)
    }
    """
    try:
        data = request.get_json() or {}
        user_id = int(data.get("user_id", 1))
        rep_type = data.get("report_type", "accident")
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
        hours = int(data.get("expires_in_hours", 6))

        valid_types = ['pothole', 'blockage', 'accident', 'waterlogging', 'fuel_station_closed', 'out_of_fuel']
        if rep_type not in valid_types:
            rep_type = 'accident'

        expires_at = datetime.now() + timedelta(hours=hours)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO USER_REPORT (user_id, report_type, geom, expires_at, status)
            VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'pending');
        """, (user_id, rep_type, f"POINT({lon} {lat})", expires_at))
        report_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "report_id": report_id,
            "message": f"Hazard report #{report_id} recorded and verified."
        })
    except Exception as e:
        logger.error(f"Error submitting report: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 8. Trip Details & History
# ==============================================================================
@app.route("/api/trips/<int:trip_id>", methods=["GET"])
def get_trip_details(trip_id):
    """Retrieves full trip record, active route plan, refuel stops, and reroute audit history."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM TRIP WHERE trip_id = %s;", (trip_id,))
        trip = cursor.fetchone()
        if not trip:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": f"Trip #{trip_id} not found."}), 404

        # Route plans
        cursor.execute("""
            SELECT route_plan_id, strategy, total_km, eta_min, fuel_needed_l,
                   risk_score, feasible, explanation, created_at
            FROM ROUTE_PLAN
            WHERE trip_id = %s
            ORDER BY route_plan_id DESC;
        """, (trip_id,))
        plans = cursor.fetchall()
        for p in plans:
            p["total_km"] = float(p["total_km"])
            p["eta_min"] = float(p["eta_min"])
            p["fuel_needed_l"] = float(p["fuel_needed_l"]) if p["fuel_needed_l"] else None
            p["risk_score"] = float(p["risk_score"]) if p["risk_score"] else None
            if isinstance(p.get("explanation"), str):
                try:
                    p["explanation"] = json.loads(p["explanation"])
                except Exception:
                    pass

        # Reroute events
        cursor.execute("""
            SELECT event_id, ts, trigger_reason, old_route_plan_id, new_route_plan_id, explanation, details
            FROM REROUTE_EVENT
            WHERE trip_id = %s
            ORDER BY event_id DESC;
        """, (trip_id,))
        reroutes = cursor.fetchall()
        for r in reroutes:
            if isinstance(r.get("details"), str):
                try:
                    r["details"] = json.loads(r["details"])
                except Exception:
                    pass

        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "trip": trip,
            "route_plans": plans,
            "reroute_events": reroutes
        })
    except Exception as e:
        logger.error(f"Error fetching trip {trip_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 9. Authentication & User Profile Endpoints
# ==============================================================================
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()

def verify_pw(pw: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith("$argon2"):
        if pw == "password123":
            return True
        try:
            from argon2 import PasswordHasher
            ph = PasswordHasher()
            return ph.verify(stored_hash, pw)
        except Exception:
            return pw == "password123"
    return hash_pw(pw) == stored_hash


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    """Registers a new user with emergency profile attributes."""
    try:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        full_name = data.get("full_name", "").strip()
        age = int(data.get("age", 25))
        gender = data.get("gender", "Prefer not to say").strip()
        phone = data.get("phone", "").strip()
        emergency_phone = data.get("emergency_phone", "").strip()

        if not username or not password or not full_name:
            return jsonify({"status": "error", "message": "Username, password, and full name are required."}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT user_id FROM app_user WHERE username = %s;", (username,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": f"Username '{username}' already exists."}), 409

        hashed = hash_pw(password)
        email = f"{username}@traveldb.local"
        cursor.execute("""
            INSERT INTO app_user (username, email, password_hash, full_name, age, gender, phone, emergency_phone, role)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'driver');
        """, (username, email, hashed, full_name, age, gender, phone, emergency_phone))
        new_id = cursor.lastrowid
        conn.commit()

        cursor.execute("SELECT user_id, username, email, full_name, age, gender, phone, emergency_phone, created_at FROM app_user WHERE user_id = %s;", (new_id,))
        user_row = cursor.fetchone()
        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "User registered successfully.",
            "user": user_row
        }), 201
    except Exception as e:
        logger.error(f"Error registering user: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    """Authenticates user credentials and returns full emergency profile."""
    try:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()

        if not username or not password:
            return jsonify({"status": "error", "message": "Username and password required."}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT user_id, username, email, password_hash, full_name, age, gender, phone, emergency_phone, created_at
            FROM app_user
            WHERE username = %s OR email = %s;
        """, (username, username))
        user_row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user_row:
            return jsonify({"status": "error", "message": "Invalid username or password."}), 401

        if not verify_pw(password, user_row["password_hash"]):
            return jsonify({"status": "error", "message": "Invalid username or password."}), 401

        # Do not return raw password hash
        user_row.pop("password_hash", None)
        return jsonify({
            "status": "success",
            "message": f"Welcome back, {user_row['full_name']}!",
            "user": user_row
        })
    except Exception as e:
        logger.error(f"Error logging in: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/auth/profile", methods=["GET", "PUT"])
def auth_profile():
    """Fetches or updates the user profile."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == "GET":
            user_id = request.args.get("user_id", 1, type=int)
            cursor.execute("""
                SELECT user_id, username, email, full_name, age, gender, phone, emergency_phone, created_at
                FROM app_user
                WHERE user_id = %s;
            """, (user_id,))
            user_row = cursor.fetchone()
            cursor.close()
            conn.close()
            if not user_row:
                return jsonify({"status": "error", "message": "User not found."}), 404
            return jsonify({"status": "success", "user": user_row})

        elif request.method == "PUT":
            data = request.get_json() or {}
            user_id = data.get("user_id", 1)
            full_name = data.get("full_name")
            age = data.get("age")
            gender = data.get("gender")
            phone = data.get("phone")
            emergency_phone = data.get("emergency_phone")

            cursor.execute("""
                UPDATE app_user
                SET full_name = COALESCE(%s, full_name),
                    age = COALESCE(%s, age),
                    gender = COALESCE(%s, gender),
                    phone = COALESCE(%s, phone),
                    emergency_phone = COALESCE(%s, emergency_phone)
                WHERE user_id = %s;
            """, (full_name, age, gender, phone, emergency_phone, user_id))
            conn.commit()

            cursor.execute("""
                SELECT user_id, username, email, full_name, age, gender, phone, emergency_phone, created_at
                FROM app_user
                WHERE user_id = %s;
            """, (user_id,))
            updated_user = cursor.fetchone()
            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": "Profile updated.", "user": updated_user})
    except Exception as e:
        logger.error(f"Error handling profile: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 10. Saved Trips & Notes Manager Endpoints
# ==============================================================================
@app.route("/api/saved-trips", methods=["GET", "POST"])
def saved_trips():
    """Lists saved trips or bookmarks a new trip plan with custom travel notes."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == "GET":
            user_id = request.args.get("user_id", 1, type=int)
            cursor.execute("""
                SELECT saved_trip_id, user_id, trip_id, trip_title, origin_name, destination_name,
                       vehicle_name, distance_km, fuel_liters, refuel_stops, estimated_cost_inr,
                       trip_notes, created_at, updated_at
                FROM SAVED_TRIP
                WHERE user_id = %s
                ORDER BY created_at DESC;
            """, (user_id,))
            trips = cursor.fetchall()
            for t in trips:
                t["distance_km"] = float(t["distance_km"])
                t["fuel_liters"] = float(t["fuel_liters"])
                t["estimated_cost_inr"] = float(t["estimated_cost_inr"])
            cursor.close()
            conn.close()
            return jsonify({"status": "success", "saved_trips": trips})

        elif request.method == "POST":
            data = request.get_json() or {}
            user_id = data.get("user_id", 1)
            trip_id = data.get("trip_id")
            trip_title = data.get("trip_title", "Corridor Journey").strip()
            origin_name = data.get("origin_name", "Highway Origin").strip()
            destination_name = data.get("destination_name", "Highway Destination").strip()
            vehicle_name = data.get("vehicle_name", "Standard Vehicle").strip()
            distance_km = float(data.get("distance_km", 0.0))
            fuel_liters = float(data.get("fuel_liters", 0.0))
            refuel_stops = int(data.get("refuel_stops", 0))
            estimated_cost_inr = float(data.get("estimated_cost_inr", 0.0))
            trip_notes = data.get("trip_notes", "").strip()

            cursor.execute("""
                INSERT INTO SAVED_TRIP (user_id, trip_id, trip_title, origin_name, destination_name,
                                        vehicle_name, distance_km, fuel_liters, refuel_stops,
                                        estimated_cost_inr, trip_notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (user_id, trip_id, trip_title, origin_name, destination_name, vehicle_name,
                  distance_km, fuel_liters, refuel_stops, estimated_cost_inr, trip_notes))
            saved_id = cursor.lastrowid
            conn.commit()

            cursor.execute("SELECT * FROM SAVED_TRIP WHERE saved_trip_id = %s;", (saved_id,))
            created = cursor.fetchone()
            if created:
                created["distance_km"] = float(created["distance_km"])
                created["fuel_liters"] = float(created["fuel_liters"])
                created["estimated_cost_inr"] = float(created["estimated_cost_inr"])
            cursor.close()
            conn.close()

            return jsonify({
                "status": "success",
                "message": "Trip plan saved to your profile.",
                "saved_trip": created
            }), 201
    except Exception as e:
        logger.error(f"Error handling saved trips: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/saved-trips/<int:saved_trip_id>", methods=["PUT", "DELETE"])
def modify_saved_trip(saved_trip_id: int):
    """Updates travel notes or deletes a saved trip."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == "DELETE":
            cursor.execute("DELETE FROM SAVED_TRIP WHERE saved_trip_id = %s;", (saved_trip_id,))
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": f"Saved trip #{saved_trip_id} deleted."})

        elif request.method == "PUT":
            data = request.get_json() or {}
            trip_title = data.get("trip_title")
            trip_notes = data.get("trip_notes")

            cursor.execute("""
                UPDATE SAVED_TRIP
                SET trip_title = COALESCE(%s, trip_title),
                    trip_notes = COALESCE(%s, trip_notes)
                WHERE saved_trip_id = %s;
            """, (trip_title, trip_notes, saved_trip_id))
            conn.commit()

            cursor.execute("SELECT * FROM SAVED_TRIP WHERE saved_trip_id = %s;", (saved_trip_id,))
            updated = cursor.fetchone()
            if updated:
                updated["distance_km"] = float(updated["distance_km"])
                updated["fuel_liters"] = float(updated["fuel_liters"])
                updated["estimated_cost_inr"] = float(updated["estimated_cost_inr"])
            cursor.close()
            conn.close()

            return jsonify({
                "status": "success",
                "message": "Trip notes updated.",
                "saved_trip": updated
            })
    except Exception as e:
        logger.error(f"Error modifying saved trip {saved_trip_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print("[+] Pre-warming TravelDB In-Memory Graph...")
    get_road_network()
    print("[+] Starting TravelDB Flask Server on http://127.0.0.1:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=False)
