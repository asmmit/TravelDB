"""
In-Memory Graph Loader for TravelDB (Phase 4).
Loads the road topology (ROAD_NODE, ROAD_EDGE) and safety scores (EDGE_RISK) from MySQL 8.0
into an optimized, in-memory python-igraph Graph.
Provides spatial KD-Tree vertex snapping and dynamic weight overlay capabilities.
"""

import os
import sys
import time
import logging
import numpy as np
from scipy.spatial import cKDTree
import igraph

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("graph_loader")

# Geodetic constants for fast local distance approximation near latitude 13 deg N
METERS_PER_DEG_LAT = 110900.0
METERS_PER_DEG_LON = 108300.0

_NETWORK_INSTANCE = None


class RoadNetwork:
    """
    Singleton in-memory road network wrapper around python-igraph.
    Maintains bidirectional node-to-index mappings and a 2D spatial index for fast coordinate snapping.
    """

    def __init__(self, conn=None):
        self.graph = None
        self.node_id_to_idx = {}
        self.idx_to_node_id = []
        self.node_coords = []  # [[lon, lat], ...]
        self.kdtree = None
        self.edge_map = {}  # edge_id -> edge dictionary
        self._load_from_db(conn)

    def _load_from_db(self, conn=None):
        owns_conn = False
        if conn is None:
            conn = get_db_connection()
            owns_conn = True

        try:
            t0 = time.time()
            logger.info("Loading road network from MySQL into in-memory igraph structure...")

            cursor = conn.cursor(dictionary=True)

            # 1. Load Road Nodes
            cursor.execute("""
                SELECT node_id, osm_id, ST_X(geom) as lon, ST_Y(geom) as lat, district_id
                FROM ROAD_NODE
                ORDER BY node_id ASC;
            """)
            nodes = cursor.fetchall()
            t_nodes = time.time()
            logger.info(f"Loaded {len(nodes)} road nodes in {t_nodes - t0:.2f}s.")

            self.idx_to_node_id = [n["node_id"] for n in nodes]
            self.node_id_to_idx = {n["node_id"]: idx for idx, n in enumerate(nodes)}
            self.node_coords = np.array([[n["lon"], n["lat"]] for n in nodes])

            # Build KD-Tree in projected meters for sub-millisecond point snapping
            proj_coords = np.column_stack([
                self.node_coords[:, 0] * METERS_PER_DEG_LON,
                self.node_coords[:, 1] * METERS_PER_DEG_LAT
            ])
            self.kdtree = cKDTree(proj_coords)

            # 2. Load Road Edges with Risk Scores
            cursor.execute("""
                SELECT e.edge_id, e.from_node, e.to_node, e.osm_way_id, e.road_name, e.ref,
                       e.road_type, e.length_m, e.speed_kph, e.lanes, e.oneway,
                       ST_AsText(e.geom) as geom_wkt,
                       COALESCE(r.risk_score, 25.00) as risk_score
                FROM ROAD_EDGE e
                LEFT JOIN EDGE_RISK r ON e.edge_id = r.edge_id;
            """)
            edges = cursor.fetchall()
            t_edges = time.time()
            logger.info(f"Loaded {len(edges)} road edges with risk scores in {t_edges - t_nodes:.2f}s.")

            cursor.close()

            # 3. Construct Directed igraph Graph
            g = igraph.Graph(directed=True)
            g.add_vertices(len(nodes))

            # Store vertex attributes
            g.vs["node_id"] = self.idx_to_node_id
            g.vs["lon"] = self.node_coords[:, 0]
            g.vs["lat"] = self.node_coords[:, 1]

            edge_tuples = []
            edge_ids = []
            lengths = []
            speeds = []
            times = []
            risks = []
            safety_weights = []
            road_types = []
            road_names = []
            refs = []
            wkts = []

            for e in edges:
                u = self.node_id_to_idx.get(e["from_node"])
                v = self.node_id_to_idx.get(e["to_node"])
                if u is None or v is None:
                    continue

                length = float(e["length_m"])
                speed = float(e["speed_kph"]) if float(e["speed_kph"]) > 0 else 40.0
                # Travel time in seconds = distance (m) / speed (m/s)
                time_s = length / (speed * (1000.0 / 3600.0))
                risk = float(e["risk_score"])
                # Safety weight penalizes high-risk edges in safety-first routing
                # (e.g. risk score 50 adds +100% travel time penalty to the cost function)
                safety_weight = time_s * (1.0 + (risk / 50.0))

                edge_tuples.append((u, v))
                edge_ids.append(e["edge_id"])
                lengths.append(length)
                speeds.append(speed)
                times.append(time_s)
                risks.append(risk)
                safety_weights.append(safety_weight)
                road_types.append(e["road_type"] or "unclassified")
                road_names.append(e["road_name"] or "")
                refs.append(e["ref"] or "")
                wkts.append(e["geom_wkt"])

                # Add reverse edge for bidirectional roads (oneway == False)
                if not e["oneway"]:
                    edge_tuples.append((v, u))
                    edge_ids.append(e["edge_id"])
                    lengths.append(length)
                    speeds.append(speed)
                    times.append(time_s)
                    risks.append(risk)
                    safety_weights.append(safety_weight)
                    road_types.append(e["road_type"] or "unclassified")
                    road_names.append(e["road_name"] or "")
                    refs.append(e["ref"] or "")
                    wkts.append(e["geom_wkt"])

                self.edge_map[e["edge_id"]] = {
                    "edge_id": e["edge_id"],
                    "from_node": e["from_node"],
                    "to_node": e["to_node"],
                    "length_m": length,
                    "speed_kph": speed,
                    "travel_time_s": time_s,
                    "risk_score": risk,
                    "road_type": e["road_type"],
                    "road_name": e["road_name"],
                    "ref": e["ref"],
                    "geom_wkt": e["geom_wkt"]
                }

            g.add_edges(edge_tuples)
            g.es["edge_id"] = edge_ids
            g.es["length_m"] = lengths
            g.es["speed_kph"] = speeds
            g.es["travel_time_s"] = times
            g.es["risk_score"] = risks
            g.es["safety_weight"] = safety_weights
            g.es["road_type"] = road_types
            g.es["road_name"] = road_names
            g.es["ref"] = refs
            g.es["geom_wkt"] = wkts

            # Analyze strongly connected components for robust routing reachability
            scc = g.connected_components(mode="strong")
            self.scc_membership = np.array(scc.membership)
            self.giant_component_id = int(np.argmax(scc.sizes()))
            giant_size = scc.sizes()[self.giant_component_id]

            self.graph = g
            t_total = time.time()
            logger.info(f"[+] In-memory road graph constructed: {g.vcount()} vertices, {g.ecount()} edges in {t_total - t0:.2f}s total.")
            logger.info(f"[+] Giant Strongly Connected Component: {giant_size} nodes ({giant_size / g.vcount() * 100:.1f}% coverage).")

        finally:
            if owns_conn:
                conn.close()

    def find_nearest_node(self, lat, lon, ensure_routable=True):
        """
        Snaps geographic coordinates (lat, lon) to the nearest road network node.
        If ensure_routable is True, ensures the snapped node belongs to the Giant SCC.
        Returns (node_id, vertex_idx, distance_meters).
        """
        pt_proj = np.array([lon * METERS_PER_DEG_LON, lat * METERS_PER_DEG_LAT])
        
        if ensure_routable and self.giant_component_id is not None:
            # Query candidate nearest nodes up to k=50
            dists, indices = self.kdtree.query(pt_proj, k=min(50, len(self.idx_to_node_id)))
            if not isinstance(indices, (list, np.ndarray)):
                indices = [indices]
                dists = [dists]
            for d, idx in zip(dists, indices):
                if self.scc_membership[idx] == self.giant_component_id:
                    return self.idx_to_node_id[idx], int(idx), float(d)
        
        # Fallback to absolute closest node
        dist_m, idx = self.kdtree.query(pt_proj)
        node_id = self.idx_to_node_id[idx]
        return node_id, int(idx), float(dist_m)

    def get_vertex_coords(self, vertex_idx):
        """Returns (lat, lon) tuple for a given vertex index."""
        return float(self.node_coords[vertex_idx, 1]), float(self.node_coords[vertex_idx, 0])


def get_road_network(reload_cache=False):
    """
    Returns the singleton RoadNetwork instance, initializing it on first call.
    """
    global _NETWORK_INSTANCE
    if _NETWORK_INSTANCE is None or reload_cache:
        _NETWORK_INSTANCE = RoadNetwork()
    return _NETWORK_INSTANCE


if __name__ == "__main__":
    net = get_road_network()
    print(f"Graph loaded successfully: {net.graph.vcount()} vertices, {net.graph.ecount()} edges.")
    
    # Test snapping Chennai Central (13.0827, 80.2707)
    node_id, idx, dist = net.find_nearest_node(13.0827, 80.2707)
    lat, lon = net.get_vertex_coords(idx)
    print(f"Chennai Central snapped to node {node_id} (idx {idx}) at distance {dist:.1f}m (coords: {lat:.5f}, {lon:.5f})")
