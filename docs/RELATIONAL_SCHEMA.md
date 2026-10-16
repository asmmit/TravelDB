# TravelDB Relational Schema, Normalization & Functional Dependencies

## 1. Schema Overview

The database design adheres strictly to the Relational Model and Boyce-Codd Normal Form (BCNF) / Third Normal Form (3NF), with documented and mathematically justified denormalizations for spatial graph routing performance.

---

## 2. Functional Dependencies & Normalization Proofs

### Relation: `STATE`
- **Schema**: `(state_id, name, code, created_at)`
- **Candidate Keys**: `{state_id}`, `{name}`, `{code}`
- **Functional Dependencies (FDs)**:
  - `state_id -> name, code, created_at`
  - `name -> state_id, code, created_at`
  - `code -> state_id, name, created_at`
- **Normal Form**: **BCNF**. For every non-trivial FD $X \rightarrow Y$, $X$ is a superkey.

### Relation: `DISTRICT`
- **Schema**: `(district_id, state_id, name, geom, created_at)`
- **Candidate Keys**: `{district_id}`, `{state_id, name}`
- **Functional Dependencies (FDs)**:
  - `district_id -> state_id, name, geom, created_at`
  - `state_id, name -> district_id, geom, created_at`
- **Normal Form**: **BCNF**. Every determinant is a candidate key.

### Relation: `ROAD_TYPE`
- **Schema**: `(road_type, default_speed_kph, fuel_factor, description)`
- **Candidate Keys**: `{road_type}`
- **Functional Dependencies (FDs)**:
  - `road_type -> default_speed_kph, fuel_factor, description`
- **Normal Form**: **BCNF**.

### Relation: `ROAD_NODE`
- **Schema**: `(node_id, osm_id, geom, district_id, created_at)`
- **Candidate Keys**: `{node_id}`, `{osm_id}`
- **Functional Dependencies (FDs)**:
  - `node_id -> osm_id, geom, district_id, created_at`
  - `osm_id -> node_id, geom, district_id, created_at`
- **Normal Form**: **3NF / BCNF**. `district_id` represents the administrative boundary containing `geom`.

### Relation: `ROAD_EDGE`
- **Schema**: `(edge_id, from_node, to_node, osm_way_id, road_name, ref, road_type, length_m, speed_kph, speed_source, lanes, oneway, is_toll, surface, geom, district_id, created_at)`
- **Primary Key**: `{edge_id}`
- **Functional Dependencies (FDs)**:
  - `edge_id -> from_node, to_node, osm_way_id, road_name, ref, road_type, length_m, speed_kph, speed_source, lanes, oneway, is_toll, surface, geom, district_id, created_at`
- **Controlled Denormalizations**:
  1. **`length_m`**: In a pure normalized schema, length is derived mathematically from `geom` ($\text{length} = f(\text{geom})$). We store `length_m` explicitly to avoid calling CPU-heavy geodesic computations (`ST_Length()`) repeatedly inside routing graph queries.
  2. **`district_id`**: In pure 3NF, the edge's district is determined by intersecting `geom` with `DISTRICT.geom`. Computing spatial polygon containment on every edge join during risk scoring would cripple query performance ($O(E \cdot D)$ spatial intersection). Denormalizing `district_id` allows instantaneous indexed joins ($O(1)$ B-Tree lookup).

### Relation: `FUEL_STATION`
- **Schema**: `(station_id, osm_id, name, brand, geom, nearest_node_id, snap_dist_m, opening_hours, verified_status, created_at)`
- **Candidate Keys**: `{station_id}`, `{osm_id}`
- **Functional Dependencies**:
  - `station_id -> osm_id, name, brand, geom, nearest_node_id, snap_dist_m, opening_hours, verified_status, created_at`
- **Normal Form**: **3NF / BCNF**.

### Relation: `ROUTE_PLAN_EDGE`
- **Schema**: `(plan_edge_id, route_plan_id, seq, edge_id)`
- **Candidate Keys**: `{plan_edge_id}`, `{route_plan_id, seq}`
- **Functional Dependencies**:
  - `plan_edge_id -> route_plan_id, seq, edge_id`
  - `route_plan_id, seq -> plan_edge_id, edge_id`
- **Normal Form**: **BCNF**. Guarantees strict ordering of edges in a route plan without repeating groups (1NF satisfied, no partial dependencies, no transitive dependencies).

---

## 3. Defense Against Viva Questions on Storage & Data Modeling

### Q1: "Why not store the graph in a NoSQL Graph Database like Neo4j?"
**Defense**:
1. **Mathematical Representation**: In graph theory, a directed graph is defined as $G = (V, E)$ where $V$ is a set of vertices and $E \subseteq V \times V$ is a set of edges. Relational tables `ROAD_NODE` and `ROAD_EDGE` directly instantiate this formal mathematical model.
2. **ACID Transactional Guarantees**: A real-world trip planning platform manages financial and operational transactions (user accounts, fuel payments, refuel logs, telemetry). Neo4j and graph databases do not provide the robust multi-table foreign-key relational integrity, mature connection pooling, and multi-version concurrency control (MVCC) of MySQL InnoDB.
3. **Hybrid Architecture (Best of Both Worlds)**: MySQL is the authoritative **System of Record** ensuring persistent storage, spatial indexing, and strict schema validation. For traversal, the topology is loaded into an optimized in-memory adjacency index (`python-igraph`), executing graph traversals in milliseconds without disk I/O bottlenecks.

### Q2: "Why use MySQL Spatial SRID 4326 and SPATIAL INDEX instead of just float lat/lng columns?"
**Defense**:
1. **SRID 4326**: Corresponds to the WGS 84 geographic coordinate reference system (standard GPS latitude/longitude). Using `SRID 4326` ensures MySQL computes geodesic calculations on an ellipsoidal Earth model rather than planar Cartesian math.
2. **Spatial Indexes (R-Tree)**: Standard B-Trees only index 1-dimensional scalar data. If we query with two floats (`WHERE lat BETWEEN ... AND lng BETWEEN ...`), MySQL can only index scan on one column and filter the other, resulting in $O(N)$ scanning. MySQL's `SPATIAL INDEX` uses a multi-dimensional **R-Tree (Region Tree)** that partitions 2D space into bounding boxes (Minimum Bounding Rectangles - MBRs), allowing $O(\log N)$ spatial filtering for point-in-radius and nearest-neighbor queries.
