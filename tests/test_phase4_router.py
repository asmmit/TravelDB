"""
Tests for TravelDB Phase 4: In-Memory Graph Engine & Multi-Objective Router.
Validates:
1. python-igraph graph topology and Giant SCC coverage (> 85%).
2. Nearest node snapping and projection math.
3. Fastest, shortest, and safest multi-objective pathfinding.
4. Sub-25ms Dijkstra query latency.
5. Polyline generation and turn-by-turn leg instructions.
"""

import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from engine.graph_loader import get_road_network
from engine.router import find_route, compare_route_objectives


@pytest.fixture(scope="module")
def network():
    """Initializes and caches the in-memory road network for all Phase 4 tests."""
    return get_road_network()


def test_network_topology_integrity(network):
    """Validates vertices, bidirectional edge count, and Giant SCC coverage."""
    g = network.graph
    assert g is not None
    assert g.vcount() > 40000
    # Edges should include bidirectional expansion (> 80,000)
    assert g.ecount() > 80000

    # Validate Giant SCC coverage > 85%
    scc = g.connected_components(mode="strong")
    max_scc_size = max(scc.sizes())
    coverage = max_scc_size / g.vcount()
    assert coverage >= 0.85


def test_spatial_snapping_to_routable_component(network):
    """Validates that coordinate snapping routes to the Giant SCC."""
    # Test coordinates for Poonamallee and Sriperumbudur
    node_id_1, idx_1, dist_1 = network.find_nearest_node(13.0474, 80.0937, ensure_routable=True)
    node_id_2, idx_2, dist_2 = network.find_nearest_node(12.9675, 79.9436, ensure_routable=True)

    assert node_id_1 > 0
    assert node_id_2 > 0
    assert dist_1 < 1000.0
    assert dist_2 < 500.0

    # Ensure both belong to Giant SCC
    assert network.scc_membership[idx_1] == network.giant_component_id
    assert network.scc_membership[idx_2] == network.giant_component_id


def test_fastest_route_computation(network):
    """Validates fastest path calculation between Poonamallee and Sriperumbudur."""
    res = find_route((13.0474, 80.0937), (12.9675, 79.9436), mode="fastest")
    assert res["status"] == "success"
    assert res["mode"] == "fastest"
    assert 15.0 <= res["distance_km"] <= 25.0
    assert 10.0 <= res["duration_min"] <= 30.0
    assert res["average_risk_score"] > 0.0
    assert res["dijkstra_latency_ms"] < 25.0  # Must be sub-25ms
    assert len(res["polyline"]) > 100
    assert len(res["instructions"]) >= 3
    assert len(res["edge_ids"]) > 50


def test_shortest_vs_fastest(network):
    """Validates shortest path distance is less than or equal to fastest path distance."""
    fastest = find_route((13.0474, 80.0937), (12.9675, 79.9436), mode="fastest")
    shortest = find_route((13.0474, 80.0937), (12.9675, 79.9436), mode="shortest")

    assert fastest["status"] == "success"
    assert shortest["status"] == "success"
    assert shortest["distance_km"] <= fastest["distance_km"]


def test_safest_route_objective(network):
    """Validates safest path achieves lower or equal average risk compared to fastest path."""
    fastest = find_route((13.0474, 80.0937), (12.9675, 79.9436), mode="fastest")
    safest = find_route((13.0474, 80.0937), (12.9675, 79.9436), mode="safest")

    assert fastest["status"] == "success"
    assert safest["status"] == "success"
    assert safest["average_risk_score"] <= fastest["average_risk_score"]


def test_avoid_blackspots_flag(network):
    """Validates avoid_blackspots routing flag."""
    route_standard = find_route((13.0474, 80.0937), (12.9675, 79.9436), mode="fastest", avoid_blackspots=False)
    route_avoid = find_route((13.0474, 80.0937), (12.9675, 79.9436), mode="fastest", avoid_blackspots=True)

    assert route_standard["status"] == "success"
    assert route_avoid["status"] == "success"
    assert route_avoid["dijkstra_latency_ms"] < 30.0


def test_same_origin_and_destination(network):
    """Validates behavior when origin and destination coordinates are identical."""
    res = find_route((13.0474, 80.0937), (13.0474, 80.0937))
    assert res["status"] == "success"
    assert res["distance_km"] == 0.0
    assert res["duration_min"] == 0.0
