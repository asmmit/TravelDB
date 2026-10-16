# TravelDB: Comprehensive DBMS Viva & Defense Guide

This document prepares you for every theoretical and architectural question your professor can ask during your final project evaluation and viva.

---

## 1. Relational Modeling & Normalization

### Q1: "What Normal Form is your database in? Prove it."
**Answer**:
- Our schema is normalized to **Third Normal Form (3NF) and Boyce-Codd Normal Form (BCNF)** across all entities.
- **Formal BCNF Definition**: A relation $R$ is in BCNF if for every non-trivial functional dependency $X \rightarrow Y$, $X$ is a superkey of $R$.
- **Example Proof on `ROAD_TYPE`**:
  - Relation: `ROAD_TYPE(road_type, default_speed_kph, fuel_factor, description)`
  - Primary Key: `{road_type}`
  - Dependency: `road_type -> default_speed_kph, fuel_factor, description`
  - Since the determinant `road_type` is the candidate key, no partial dependencies or transitive dependencies exist. Thus, it satisfies 1NF, 2NF, 3NF, and BCNF.
- **Controlled Denormalization Defense**:
  - We have two deliberate denormalizations:
    1. `ROAD_EDGE.length_m`: Length is technically functionally dependent on `geom` ($\text{length} = f(\text{geom})$). We store it to avoid invoking `ST_Length()` repeatedly during routing.
    2. `ROAD_EDGE.district_id`: Can be derived via spatial intersection ($\text{geom} \cap \text{DISTRICT.geom}$). Storing `district_id` allows $O(1)$ indexed joins for district risk aggregation without $O(E \times D)$ spatial geometric intersections.

---

## 2. Spatial Indexing & SRID 4326

### Q2: "Why did you use MySQL SPATIAL INDEX instead of regular B-Tree indexes on lat and lng columns?"
**Answer**:
- A standard **B-Tree index is strictly 1-dimensional**. If we store coordinates as two floating-point numbers (`lat FLOAT`, `lng FLOAT`), a B-tree can only index one dimension effectively.
  - A query like `WHERE lat BETWEEN 12.8 AND 13.0 AND lng BETWEEN 79.0 AND 79.5` forces MySQL to scan all rows matching the `lat` range and then sequentially inspect every `lng` value.
- A **Spatial Index in MySQL uses an R-Tree (Region Tree)**:
  - An R-tree groups nearby geometric objects into Minimum Bounding Rectangles (MBRs) organized in a hierarchical tree.
  - Multi-dimensional bounding box searches prune vast subtrees simultaneously in $O(\log N)$ time.
- **SRID 4326**:
  - Specifies the **WGS 84 (World Geodetic System 1984)** coordinate system.
  - Tells MySQL that the coordinates represent an ellipsoidal Earth surface (latitude and longitude in degrees), ensuring distance and containment functions calculate true geodesic distances rather than Euclidean flat-plane approximations.

---

## 3. In-Memory Graph vs Recursive SQL CTEs

### Q3: "Why did you use python-igraph in memory instead of running graph queries directly in MySQL?"
**Answer**:
- **Relational Databases are Systems of Record, not Graph Traversal Engines**:
  - Finding the shortest path in a graph requires **pointer-chasing** and exploring tens of thousands of adjacent vertices.
  - In pure SQL, this must be done using a **Recursive Common Table Expression (CTE)**. On a road graph of 100,000+ edges, recursive self-joins result in quadratic temporary table generation and severe disk/buffer-pool I/O thrashing, taking 5 to 30 seconds per query.
- **Our Hybrid Architecture**:
  - **MySQL 8.0**: Holds the single source of truth, guarantees ACID persistence, handles spatial indexing, user profiles, fuel logs, and telemetry.
  - **python-igraph**: An in-memory, highly optimized C-library that builds a contiguous adjacency list in RAM. Dijkstra/A* pathfinding executes in $< 15\text{ ms}$.
- **Viva Demo**:
  - We can run a Recursive CTE query on a small 10-node subnetwork inside MySQL to prove the relational concept, while defending our in-memory engine for real-time dynamic rerouting.

---

## 4. Transactions, Concurrency & ACID

### Q4: "Where do you use ACID transactions in TravelDB, and what isolation level do you use?"
**Answer**:
- **Atomic Refueling Transaction**:
  - When a user logs a refuel stop mid-trip, three operations must succeed together or not at all:
    1. Insert row into `FUEL_LOG (vehicle_id, litres, odometer, station_id)`.
    2. Insert row into `ROUTE_PLAN_STOP (trip_id, station_id, refuel_l)`.
    3. Update `TRIP.initial_fuel_l` and `GPS_PING.fuel_remaining_l`.
  - Wrapped in `START TRANSACTION ... COMMIT` (with `ROLLBACK` on error) to prevent partial updates.
- **Isolation Level**:
  - Default MySQL InnoDB isolation: **REPEATABLE READ**.
  - Uses Multi-Version Concurrency Control (MVCC) and Next-Key Locking (record locks + gap locks) to prevent dirty reads, non-repeatable reads, and phantom rows during concurrent trip reads and GPS telemetry writes.

---

## 5. Security & Least-Privilege Roles

### Q5: "How is database security enforced in your application?"
**Answer**:
- **No Direct Root Access**: We create three dedicated MySQL roles with least-privilege principles:
  1. `app_rw`: For Flask backend (SELECT, INSERT, UPDATE on application tables; no DROP/ALTER/GRANT).
  2. `ingest_w`: For background scheduled workers (INSERT, UPDATE on traffic, weather, and incident tables).
  3. `analytics_ro`: Read-only access for reporting and ML feature extraction (SELECT only).
- **SQL Injection Prevention**: All queries use parameterized queries / prepared statements (`%s` placeholders in `mysql-connector-python`), ensuring user input is never concatenated directly into SQL text.
- **Password Hashing**: User passwords are encrypted using **Argon2id** (winner of the Password Hashing Competition) or bcrypt with cryptographic salt, stored in `APP_USER.password_hash`.

---

## 6. Semi-Structured Data & JSON Support in MySQL 8.0

### Q6: "Why did you use a JSON column (`components`) in `EDGE_RISK` instead of separate relational columns? How do you query it?"
**Answer**:
- **Design Trade-off**:
  - The aggregate score `risk_score DECIMAL(5,2)` is a standard relational column indexed for numeric sorting, range filtering, and Dijkstra graph weight extraction.
  - The sub-component breakdown (`base_risk`, `road_type`, `blackspot_penalty`, `nearest_blackspot`, `blackspot_dist_m`, `weather_penalty`, `district_factor`) is explainable metadata that varies dynamically depending on which hazards are active.
  - Using a JSON document allows schema evolution without running `ALTER TABLE` whenever a new risk feature (such as school zones, wildlife crossings, or gradient steepness) is added.
- **Querying JSON in MySQL 8.0**:
  - We use MySQL's native JSON path expression and inline operator `->>` (equivalent to `JSON_UNQUOTE(JSON_EXTRACT(components, '$.key'))`).
  - Example:
    ```sql
    SELECT edge_id, risk_score, components->>'$.nearest_blackspot' AS blackspot
    FROM EDGE_RISK
    WHERE CAST(components->>'$.blackspot_penalty' AS DECIMAL(5,2)) > 20.00;
    ```
- **Performance & Indexing**:
  - If high-frequency querying is required on a nested JSON property, MySQL 8.0 supports **Generated Columns with B-Tree indexes** or **Multi-Valued Indexes**:
    ```sql
    ALTER TABLE EDGE_RISK ADD COLUMN blackspot_penalty DECIMAL(5,2) 
    GENERATED ALWAYS AS (components->>'$.blackspot_penalty') STORED;
    CREATE INDEX idx_er_penalty ON EDGE_RISK (blackspot_penalty);
    ```

---

## 7. Database Views & Stored Procedures

### Q7: "What is the difference between a View and a Stored Procedure in TravelDB, and when do you use each?"
**Answer**:
- **Database View (`v_high_risk_corridor_edges`)**:
  - **What it is**: A saved virtual SQL query that does not store data on disk. When queried, MySQL merges the view's definition with the outer query.
  - **Purpose in TravelDB**: Encapsulates the join between `EDGE_RISK` and `ROAD_EDGE` while unrolling nested JSON fields into clean tabular columns (`nearest_blackspot`, `blackspot_dist_m`, `weather_penalty`). This prevents the application layer from having to write complex JSON parsing SQL.
- **Stored Procedure (`sp_get_corridor_risk_summary()`)**:
  - **What it is**: Precompiled SQL code stored in the database catalog that executes procedural logic and conditional statements on the database server.
  - **Purpose in TravelDB**: Executes corridor-wide aggregations (calculating counts of high, medium, and low risk edges alongside min/avg/max scores).
  - **Benefits**:
    1. **Reduced Network Traffic**: A single call `CALL sp_get_corridor_risk_summary();` replaces transferring thousands of raw records to the client.
    2. **Execution Plan Caching**: MySQL compiles and caches the procedural execution plan.
    3. **Encapsulation**: Business logic for risk categorization lives directly in the database engine.

---

## 8. Spatial Containment & Pre-Aggregation

### Q8: "Why did you pre-aggregate `district_id` on `ROAD_EDGE` and precompute `EDGE_RISK` instead of computing them on-the-fly during routing?"
**Answer**:
- **Computational Complexity**:
  - The road network contains **59,468 edges** and **45,518 nodes**.
  - Checking if an edge intersects with complex 100-vertex district polygons or calculating Euclidean/geodesic distance to 10 blackspots for 59,468 edges takes ~7 to 10 seconds of CPU time.
- **Sub-Second Pathfinding Requirement**:
  - When a user requests a route or encounters a road closure, the routing engine must evaluate alternative paths in **less than 50 milliseconds**.
  - If risk calculations were computed dynamically inside Dijkstra's algorithm, every edge relaxation step would perform multiple spatial distance checks, causing user requests to time out.
- **Asynchronous Refresh Pattern**:
  - By persisting `district_id` statically and updating `EDGE_RISK` asynchronously whenever weather changes or blackspot registries update, pathfinding reduces to an instantaneous $O(1)$ memory lookup of a precomputed numerical weight.

---

## 9. Graph Theory & Real-Time Pathfinding

### Q9: "What algorithm does your router use, what is its computational complexity, and how do you achieve sub-10ms performance?"
**Answer**:
- **Algorithm**: Dijkstra's algorithm implemented in C within the `python-igraph` core library.
- **Complexity**:
  - Utilizing a Fibonacci heap or binary min-heap priority queue, Dijkstra's computational complexity is:
    $$\mathcal{O}(|E| + |V| \log |V|)$$
    Where $|V| = 45,518$ vertices and $|E| = 84,908$ directed edges.
- **Why it achieves ~5 ms latency**:
  1. **Contiguous Memory Allocation**: The adjacency list and edge weight vectors are stored in contiguous C memory buffers (cache-line friendly, zero Python object overhead during pointer dereferences).
  2. **In-Memory Execution**: No disk I/O, SQL parsing, or database locks during graph traversal.
  3. **Spatial Snap Pruning**: Coordinate snapping uses an $O(\log N)$ 2D KD-tree in $< 0.1\text{ ms}$, ensuring the solver begins directly from the closest routable node index.

---

### Q10: "How do your cost functions mathematically ensure that the Fastest, Shortest, and Safest paths diverge?"
**Answer**:
- **Fastest Path**:
  $$w_{\text{fastest}}(e) = \frac{\text{length\_m}(e)}{\text{speed\_kph}(e) \times \frac{1000}{3600}}$$
  Prioritizes high-speed corridors (National Highways at 80–100 km/h) even if the physical distance is longer.
- **Shortest Path**:
  $$w_{\text{shortest}}(e) = \text{length\_m}(e)$$
  Strictly minimizes Euclidean/geodesic road distance. It often cuts through narrower town roads or State Highways (at 40–50 km/h) if they provide a more direct geographic line.
- **Safest Path**:
  $$w_{\text{safest}}(e) = w_{\text{fastest}}(e) \times \left(1.0 + \frac{\text{risk\_score}(e)}{50.0}\right)$$
  Synthesizes travel time with risk. When a high-speed highway segment has a severe blackspot hazard (e.g. risk score 65 at Sriperumbudur Toll Plaza), its effective routing cost increases by $+130\%$, prompting Dijkstra to choose an alternate bypass or service road.

---

### Q11: "Why did you build a directed graph with bidirectional two-way expansion rather than an undirected graph?"
**Answer**:
- **Real-World Highway Semantics**:
  - Real road networks are **inherently directed**:
    - National Highways (NH 48) feature dual-carriageway divided lanes where driving in reverse is illegal and impossible (`oneway = TRUE`).
    - Expressway ramps (`motorway_link`), roundabouts, and urban one-way streets allow travel in only one direction.
    - Two-way streets (`oneway = FALSE`) permit travel in both directions.
- **Graph Design**:
  - An undirected graph would allow vehicles to travel against traffic on one-way divided highways and entry/exit ramps, producing dangerous and physically impossible routes.
  - A strictly directed graph that omits reverse edges for two-way streets would make two-way roads impassable in the reverse direction, fragmenting the network into thousands of isolated components.
  - Therefore, we constructed a **directed graph with 84,908 edges**: one-way roads produce 1 directed edge, and two-way roads produce 2 directed edges $(u, v)$ and $(v, u)$. This achieves an authentic **40,551-node Giant Strongly Connected Component (89.1% coverage)**.

---

### Q12: "How does TravelDB solve the Gas Station Problem along the corridor without combinatorial explosion?"
**Answer**:
- **The Challenge**: The general Gas Station Problem on an arbitrary graph is NP-hard. Checking all possible subsets of 240+ fuel stations across a 50,000-node graph causes combinatorial explosion.
- **Our Solution: 2-Stage Reduced Corridor Horizon Solver**:
  1. **Stage 1 (Base Shortest/Fastest Path)**: Compute the base optimal path $P$ from origin to destination using Dijkstra on `igraph` in $< 10\text{ ms}$.
  2. **Stage 2 (Corridor Horizon Filter & Greedy Longest Reach)**:
     - Filter candidate pumps to those within a 2.5 km spatial buffer of path $P$.
     - Calculate each candidate's cumulative distance along the highway corridor.
     - Simulate fuel burn edge-by-edge factoring road type friction ($\alpha_{\text{road\_type}}$) and weather drag ($\beta_{\text{weather}}$).
     - If current fuel minus safety reserve ($R$) cannot reach the destination, select the **furthest reachable fuel station** along the corridor.
     - Refuel to capacity $C$ and repeat until destination is reached.
- **Complexity**: $O(|E| + |V| \log |V|)$ for initial Dijkstra + $O(S \log S)$ for sorting $S$ corridor stations (where $S \le 30$), running in $< 25\text{ ms}$ total!

---

### Q13: "How does TravelDB guarantee ACID consistency and auditability during dynamic mid-trip reroutes?"
**Answer**:
- **ACID Transactional Guarantees**:
  - When a reroute trigger (`low_fuel`, `incident`, `closure`) fires, the reroute engine wraps all mutations in a single MySQL transaction:
    1. Update previous `ROUTE_PLAN` status from `'active'` to `'superseded'`.
    2. Insert new `ROUTE_PLAN` record with new polyline, ETA, fuel required, and explanation JSON.
    3. Bulk insert detailed edge sequence into `ROUTE_PLAN_EDGE`.
    4. Bulk insert planned refuel stops into `ROUTE_PLAN_STOP`.
    5. Insert audit log record into `REROUTE_EVENT` linking `old_route_plan_id`, `new_route_plan_id`, trigger reason, timestamp, and coordinates.
    6. Update `TRIP.status = 'rerouted'`.
    7. Commit transaction atomically. If any query fails, `conn.rollback()` executes, ensuring zero corrupted or orphaned route plans.
- **Auditability**: `REROUTE_EVENT` provides full viva-ready provenance of every decision the system makes during travel.

---

### Q14: "Why did you build a decoupled Flask REST API with GeoJSON payloads instead of server-side template rendering or GraphQL?"
**Answer**:
- **Separation of Concerns**:
  - The client is an interactive mapping application requiring asynchronous, client-driven map updates without full page reloads.
  - Server-side template rendering (e.g. Jinja2 full HTML reloads) would destroy map state (zoom, pan, active layers, marker popups) on every route recalculation or fuel slider adjustment.
- **Why GeoJSON / RFC 7946 Standard**:
  - Spatial layer endpoints (`/api/layers/blackspots`, `/api/layers/fuel-stations`, `/api/layers/weather`) serialize MySQL spatial geometries (`POINT`, `LINESTRING`) directly into standard `FeatureCollection` objects.
  - Leaflet natively parses GeoJSON in hardware-accelerated SVG/Canvas pipelines with zero impedance mismatch.
- **Why REST over GraphQL**:
  - Routing queries have simple, fixed access patterns (`origin`, `destination`, `vehicle_id`, `fuel`). REST provides straightforward HTTP semantics, sub-millisecond route response serialization, and predictable browser cacheability.

---

### Q15: "How does the architecture prevent route recalculations from blocking other database operations?"
**Answer**:
- **Dual Engine Architecture**:
  - Route calculation happens in **contiguous memory in C (`python-igraph`)**, requiring zero database table locks or disk I/O.
  - Database queries during trip creation use short-lived, indexed `INSERT` and `UPDATE` statements running under InnoDB `READ COMMITTED` isolation.
  - Read-only spatial layer queries (`BLACKSPOT`, `WEATHER_OBS`, `FUEL_STATION`) utilize MySQL 8.0 `SPATIAL INDEX` (R-Trees), executing in $< 2\text{ ms}$ without acquiring table locks.




