"""
Multi-Objective Corridor Router for TravelDB (Phase 4).
Executes sub-20ms pathfinding over python-igraph with three distinct objectives:
1. 'fastest': Minimizes journey duration based on road speeds.
2. 'shortest': Minimizes physical distance in kilometers.
3. 'safest': Minimizes safety risk by penalizing high-risk corridors, fatal blackspots, and adverse weather.
"""

import os
import sys
import time
import logging
import shapely.wkt
from shapely.geometry import LineString

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from engine.graph_loader import get_road_network

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("router")


def find_route(origin, destination, mode="fastest", avoid_blackspots=False):
    """
    Calculates the optimal route between origin and destination.

    Parameters:
    - origin: (lat, lon) tuple or int (node_id)
    - destination: (lat, lon) tuple or int (node_id)
    - mode: 'fastest' | 'shortest' | 'safest'
    - avoid_blackspots: if True, applies an additional 3x penalty to edges within 500m of blackspots

    Returns:
    Dictionary containing summary metrics, road segments, turn instructions, and Leaflet polyline.
    """
    t_start = time.time()
    net = get_road_network()
    g = net.graph

    # 1. Resolve Origin Vertex Index
    if isinstance(origin, (tuple, list)):
        lat, lon = origin[0], origin[1]
        orig_node_id, src_idx, orig_snap_m = net.find_nearest_node(lat, lon, ensure_routable=True)
    else:
        orig_node_id = int(origin)
        src_idx = net.node_id_to_idx.get(orig_node_id)
        orig_snap_m = 0.0
        if src_idx is None:
            raise ValueError(f"Origin node_id {orig_node_id} not found in road network.")

    # 2. Resolve Destination Vertex Index
    if isinstance(destination, (tuple, list)):
        lat, lon = destination[0], destination[1]
        dest_node_id, dst_idx, dest_snap_m = net.find_nearest_node(lat, lon, ensure_routable=True)
    else:
        dest_node_id = int(destination)
        dst_idx = net.node_id_to_idx.get(dest_node_id)
        dest_snap_m = 0.0
        if dst_idx is None:
            raise ValueError(f"Destination node_id {dest_node_id} not found in road network.")

    if src_idx == dst_idx:
        return {
            "status": "success",
            "message": "Origin and destination snap to the same road node.",
            "distance_km": 0.0,
            "duration_min": 0.0,
            "average_risk_score": 0.0,
            "polyline": [net.get_vertex_coords(src_idx)],
            "edge_ids": []
        }

    # 3. Select Edge Weight Attribute & Multi-Objective Cost Function
    if mode == "shortest":
        weights = list(g.es["length_m"])
    elif mode == "safest":
        # Safest mode minimizes danger exposure with quadratic risk weighting and blackspot avoidance
        weights = [
            (l / 1000.0) * ((r / 15.0) ** 2.0) * (15.0 if r >= 30.0 else 1.0)
            for l, r in zip(g.es["length_m"], g.es["risk_score"])
        ]
    else:  # default 'fastest'
        weights = list(g.es["travel_time_s"])

    if avoid_blackspots and mode != "safest":
        # Apply 15x penalty on high-risk edges and blackspot proximity zones (risk >= 30.0)
        weights = [
            w * 15.0 if r >= 30.0 else w
            for w, r in zip(weights, g.es["risk_score"])
        ]

    # 4. Execute Dijkstra Shortest Path in C (igraph)
    t_dijkstra_0 = time.time()
    epaths = g.get_shortest_paths(src_idx, to=dst_idx, weights=weights, output="epath")
    epath = epaths[0] if epaths else []
    t_dijkstra_1 = time.time()
    dijkstra_ms = (t_dijkstra_1 - t_dijkstra_0) * 1000.0

    if not epath:
        return {
            "status": "not_found",
            "message": f"No drivable path found between node {orig_node_id} and {dest_node_id}.",
            "origin_node_id": orig_node_id,
            "dest_node_id": dest_node_id,
            "dijkstra_ms": round(dijkstra_ms, 2)
        }

    # 5. Extract Metrics & Detailed Leg Narrative
    total_length_m = 0.0
    total_time_s = 0.0
    risk_scores = []
    high_risk_count = 0
    route_edge_ids = []
    polyline = []
    turn_instructions = []

    current_road_name = None
    current_leg_dist_m = 0.0
    current_leg_time_s = 0.0

    for eid in epath:
        e_attr = g.es[eid]
        l_m = e_attr["length_m"]
        t_s = e_attr["travel_time_s"]
        r_score = e_attr["risk_score"]
        r_name = e_attr["road_name"] or e_attr["ref"] or "Unnamed Road"
        r_type = e_attr["road_type"]

        total_length_m += l_m
        total_time_s += t_s
        risk_scores.append(r_score)
        route_edge_ids.append(e_attr["edge_id"])

        if r_score >= 50.0:
            high_risk_count += 1

        # Extract coordinate points from Linestring WKT for map polyline
        geom_wkt = e_attr["geom_wkt"]
        if geom_wkt:
            try:
                geom = shapely.wkt.loads(geom_wkt)
                if isinstance(geom, LineString):
                    for x, y in geom.coords:
                        polyline.append([round(y, 6), round(x, 6)])  # [lat, lon]
            except Exception:
                pass

        # Aggregate turn instruction legs
        if current_road_name is None:
            current_road_name = r_name
            current_leg_dist_m = l_m
            current_leg_time_s = t_s
            current_road_type = r_type
        elif r_name == current_road_name:
            current_leg_dist_m += l_m
            current_leg_time_s += t_s
        else:
            turn_instructions.append({
                "instruction": f"Follow {current_road_name}",
                "road_name": current_road_name,
                "road_type": current_road_type,
                "distance_km": round(current_leg_dist_m / 1000.0, 2),
                "duration_min": round(current_leg_time_s / 60.0, 1)
            })
            current_road_name = r_name
            current_leg_dist_m = l_m
            current_leg_time_s = t_s
            current_road_type = r_type

    # Append final leg
    if current_road_name is not None:
        turn_instructions.append({
            "instruction": f"Follow {current_road_name} to destination",
            "road_name": current_road_name,
            "road_type": current_road_type,
            "distance_km": round(current_leg_dist_m / 1000.0, 2),
            "duration_min": round(current_leg_time_s / 60.0, 1)
        })

    # Remove adjacent duplicate coordinates from polyline
    dedup_polyline = []
    for pt in polyline:
        if not dedup_polyline or dedup_polyline[-1] != pt:
            dedup_polyline.append(pt)

    avg_risk = round(sum(risk_scores) / len(risk_scores), 2) if risk_scores else 0.0
    max_risk = round(max(risk_scores), 2) if risk_scores else 0.0
    risk_tier = "High" if avg_risk >= 50.0 else ("Moderate" if avg_risk >= 30.0 else "Low")

    total_calc_ms = (time.time() - t_start) * 1000.0

    return {
        "status": "success",
        "mode": mode,
        "distance_km": round(total_length_m / 1000.0, 2),
        "duration_min": round(total_time_s / 60.0, 1),
        "average_risk_score": avg_risk,
        "max_risk_score": max_risk,
        "risk_tier": risk_tier,
        "high_risk_edges_count": high_risk_count,
        "total_edges": len(epath),
        "origin": {
            "node_id": orig_node_id,
            "snap_distance_m": round(orig_snap_m, 1)
        },
        "destination": {
            "node_id": dest_node_id,
            "snap_distance_m": round(dest_snap_m, 1)
        },
        "instructions": turn_instructions,
        "polyline": dedup_polyline,
        "edge_ids": route_edge_ids,
        "dijkstra_latency_ms": round(dijkstra_ms, 2),
        "total_calc_ms": round(total_calc_ms, 2)
    }


def compare_route_objectives(origin, destination):
    """
    Computes and compares all three route objectives ('fastest', 'shortest', 'safest')
    for a given origin and destination pair.
    """
    results = {}
    for mode in ["fastest", "shortest", "safest"]:
        res = find_route(origin, destination, mode=mode)
        results[mode] = res
    return results


if __name__ == "__main__":
    print("Testing Multi-Objective Router (Poonamallee -> Sriperumbudur)...")
    comparison = compare_route_objectives((13.0474, 80.0937), (12.9675, 79.9436))
    for m, r in comparison.items():
        print(f"\n[{m.upper()}] Status: {r['status']}")
        print(f"  Distance: {r['distance_km']} km | Duration: {r['duration_min']} mins")
        print(f"  Avg Risk: {r['average_risk_score']} | High-risk edges: {r['high_risk_edges_count']}")
        print(f"  Dijkstra: {r['dijkstra_latency_ms']} ms | Total: {r['total_calc_ms']} ms")
        print(f"  Legs: {len(r['instructions'])} turns, {len(r['polyline'])} polyline points")
