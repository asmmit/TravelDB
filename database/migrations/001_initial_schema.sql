-- ==============================================================================
-- Migration: 001_initial_schema.sql
-- Project: TravelDB - Fuel-Aware Live-Data Travel Decision Support System
-- Target: MySQL 8.0, InnoDB, utf8mb4
-- Description: Core relational schema with spatial SRID 4326 and integrity constraints.
-- ==============================================================================

-- Enforce strict SQL mode and character set
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ------------------------------------------------------------------------------
-- 1. Administrative Boundaries & Local Places (Geocoding Index)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS STATE (
    state_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(10) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS DISTRICT (
    district_id INT AUTO_INCREMENT PRIMARY KEY,
    state_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    geom GEOMETRY SRID 4326 NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_state_district (state_id, name),
    CONSTRAINT fk_district_state FOREIGN KEY (state_id) REFERENCES STATE(state_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS PLACE (
    place_id INT AUTO_INCREMENT PRIMARY KEY,
    district_id INT NULL,
    name VARCHAR(150) NOT NULL,
    place_type ENUM('city', 'town', 'village', 'suburb', 'locality') NOT NULL,
    geom POINT SRID 4326 NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    SPATIAL INDEX idx_place_geom (geom),
    INDEX idx_place_name (name),
    CONSTRAINT fk_place_district FOREIGN KEY (district_id) REFERENCES DISTRICT(district_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- 2. Road Network Topology (Nodes & Edges)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ROAD_TYPE (
    road_type VARCHAR(50) PRIMARY KEY,
    default_speed_kph DECIMAL(5,2) NOT NULL CHECK (default_speed_kph > 0),
    fuel_factor DECIMAL(4,2) NOT NULL DEFAULT 1.00 CHECK (fuel_factor > 0),
    description VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ROAD_NODE (
    node_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    osm_id BIGINT NOT NULL UNIQUE,
    geom POINT SRID 4326 NOT NULL,
    district_id INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    SPATIAL INDEX idx_road_node_geom (geom),
    CONSTRAINT fk_road_node_district FOREIGN KEY (district_id) REFERENCES DISTRICT(district_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ROAD_EDGE (
    edge_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    from_node BIGINT NOT NULL,
    to_node BIGINT NOT NULL,
    osm_way_id BIGINT NOT NULL,
    road_name VARCHAR(255) NULL,
    ref VARCHAR(50) NULL,
    road_type VARCHAR(50) NOT NULL,
    length_m DECIMAL(10,2) NOT NULL CHECK (length_m >= 0),
    speed_kph DECIMAL(5,2) NOT NULL CHECK (speed_kph > 0),
    speed_source ENUM('osm', 'default', 'live_override') NOT NULL DEFAULT 'default',
    lanes TINYINT NOT NULL DEFAULT 1 CHECK (lanes >= 1),
    oneway BOOLEAN NOT NULL DEFAULT FALSE,
    is_toll BOOLEAN NOT NULL DEFAULT FALSE,
    surface VARCHAR(50) NULL,
    geom LINESTRING SRID 4326 NOT NULL,
    district_id INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_edge_from (from_node),
    INDEX idx_edge_to (to_node),
    INDEX idx_edge_road_type (road_type),
    SPATIAL INDEX idx_road_edge_geom (geom),
    CONSTRAINT fk_edge_from_node FOREIGN KEY (from_node) REFERENCES ROAD_NODE(node_id) ON DELETE CASCADE,
    CONSTRAINT fk_edge_to_node FOREIGN KEY (to_node) REFERENCES ROAD_NODE(node_id) ON DELETE CASCADE,
    CONSTRAINT fk_edge_road_type FOREIGN KEY (road_type) REFERENCES ROAD_TYPE(road_type) ON DELETE RESTRICT,
    CONSTRAINT fk_edge_district FOREIGN KEY (district_id) REFERENCES DISTRICT(district_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- 3. Points of Interest & Fuel Stations
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS FUEL_STATION (
    station_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    name VARCHAR(255) NULL,
    brand VARCHAR(100) NULL,
    geom POINT SRID 4326 NOT NULL,
    nearest_node_id BIGINT NULL,
    snap_dist_m DECIMAL(8,2) NULL,
    opening_hours VARCHAR(255) NULL,
    verified_status ENUM('osm_unverified', 'crowd_verified', 'official') NOT NULL DEFAULT 'osm_unverified',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    SPATIAL INDEX idx_station_geom (geom),
    INDEX idx_station_nearest_node (nearest_node_id),
    CONSTRAINT fk_station_nearest_node FOREIGN KEY (nearest_node_id) REFERENCES ROAD_NODE(node_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS POI_CATEGORY (
    category_id VARCHAR(50) PRIMARY KEY,
    description VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS POI (
    poi_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    name VARCHAR(255) NULL,
    category_id VARCHAR(50) NOT NULL,
    geom POINT SRID 4326 NOT NULL,
    nearest_node_id BIGINT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    SPATIAL INDEX idx_poi_geom (geom),
    INDEX idx_poi_category (category_id),
    CONSTRAINT fk_poi_category FOREIGN KEY (category_id) REFERENCES POI_CATEGORY(category_id) ON DELETE RESTRICT,
    CONSTRAINT fk_poi_nearest_node FOREIGN KEY (nearest_node_id) REFERENCES ROAD_NODE(node_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS FUEL_PRICE (
    price_id INT AUTO_INCREMENT PRIMARY KEY,
    state_id INT NOT NULL,
    fuel_type ENUM('petrol', 'diesel', 'cng', 'electric') NOT NULL,
    price_per_litre DECIMAL(6,2) NOT NULL CHECK (price_per_litre > 0),
    as_of_date DATE NOT NULL,
    source VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_state_fuel_date (state_id, fuel_type, as_of_date),
    CONSTRAINT fk_fuel_price_state FOREIGN KEY (state_id) REFERENCES STATE(state_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- 4. Users, Vehicles & Trips
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS APP_USER (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('driver', 'admin', 'auditor') NOT NULL DEFAULT 'driver',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS VEHICLE (
    vehicle_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    fuel_type ENUM('petrol', 'diesel', 'cng', 'electric') NOT NULL,
    tank_capacity_l DECIMAL(5,2) NOT NULL CHECK (tank_capacity_l > 0),
    rated_mileage_kmpl DECIMAL(5,2) NOT NULL CHECK (rated_mileage_kmpl > 0),
    vehicle_class VARCHAR(50) NOT NULL DEFAULT 'sedan',
    make_model VARCHAR(100) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_vehicle_user FOREIGN KEY (user_id) REFERENCES APP_USER(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS TRIP (
    trip_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    vehicle_id INT NOT NULL,
    origin_node BIGINT NOT NULL,
    dest_node BIGINT NOT NULL,
    start_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('planned', 'active', 'completed', 'aborted') NOT NULL DEFAULT 'planned',
    initial_fuel_l DECIMAL(5,2) NOT NULL CHECK (initial_fuel_l >= 0),
    reserve_l DECIMAL(5,2) NOT NULL DEFAULT 3.00 CHECK (reserve_l >= 0),
    safety_margin DECIMAL(3,2) NOT NULL DEFAULT 0.85 CHECK (safety_margin > 0 AND safety_margin <= 1.00),
    CONSTRAINT fk_trip_user FOREIGN KEY (user_id) REFERENCES APP_USER(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_trip_vehicle FOREIGN KEY (vehicle_id) REFERENCES VEHICLE(vehicle_id) ON DELETE RESTRICT,
    CONSTRAINT fk_trip_origin FOREIGN KEY (origin_node) REFERENCES ROAD_NODE(node_id) ON DELETE RESTRICT,
    CONSTRAINT fk_trip_dest FOREIGN KEY (dest_node) REFERENCES ROAD_NODE(node_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ROUTE_PLAN (
    route_plan_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,
    strategy ENUM('fastest', 'shortest', 'safest', 'fuel_safe') NOT NULL,
    total_km DECIMAL(8,2) NOT NULL,
    eta_min DECIMAL(8,2) NOT NULL,
    fuel_needed_l DECIMAL(6,2) NOT NULL,
    risk_score DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    feasible BOOLEAN NOT NULL DEFAULT TRUE,
    explanation JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_plan_trip FOREIGN KEY (trip_id) REFERENCES TRIP(trip_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ROUTE_PLAN_EDGE (
    plan_edge_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    route_plan_id BIGINT NOT NULL,
    seq INT NOT NULL,
    edge_id BIGINT NOT NULL,
    UNIQUE KEY uq_plan_edge_seq (route_plan_id, seq),
    CONSTRAINT fk_rpe_plan FOREIGN KEY (route_plan_id) REFERENCES ROUTE_PLAN(route_plan_id) ON DELETE CASCADE,
    CONSTRAINT fk_rpe_edge FOREIGN KEY (edge_id) REFERENCES ROAD_EDGE(edge_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ROUTE_PLAN_STOP (
    plan_stop_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    route_plan_id BIGINT NOT NULL,
    seq INT NOT NULL,
    station_id BIGINT NOT NULL,
    refuel_l DECIMAL(5,2) NOT NULL CHECK (refuel_l > 0),
    estimated_arrival TIMESTAMP NULL,
    UNIQUE KEY uq_plan_stop_seq (route_plan_id, seq),
    CONSTRAINT fk_rps_plan FOREIGN KEY (route_plan_id) REFERENCES ROUTE_PLAN(route_plan_id) ON DELETE CASCADE,
    CONSTRAINT fk_rps_station FOREIGN KEY (station_id) REFERENCES FUEL_STATION(station_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS GPS_PING (
    ping_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    geom POINT SRID 4326 NOT NULL,
    speed_kph DECIMAL(5,2) NULL,
    fuel_remaining_l DECIMAL(5,2) NULL CHECK (fuel_remaining_l >= 0),
    snapped_edge_id BIGINT NULL,
    SPATIAL INDEX idx_ping_geom (geom),
    INDEX idx_ping_trip (trip_id),
    CONSTRAINT fk_ping_trip FOREIGN KEY (trip_id) REFERENCES TRIP(trip_id) ON DELETE CASCADE,
    CONSTRAINT fk_ping_edge FOREIGN KEY (snapped_edge_id) REFERENCES ROAD_EDGE(edge_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS REROUTE_EVENT (
    event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trigger_reason ENUM('low_fuel', 'incident', 'closure', 'traffic', 'manual', 'off_route') NOT NULL,
    details JSON NULL,
    old_route_plan_id BIGINT NULL,
    new_route_plan_id BIGINT NULL,
    explanation TEXT NOT NULL,
    CONSTRAINT fk_re_trip FOREIGN KEY (trip_id) REFERENCES TRIP(trip_id) ON DELETE CASCADE,
    CONSTRAINT fk_re_old_plan FOREIGN KEY (old_route_plan_id) REFERENCES ROUTE_PLAN(route_plan_id) ON DELETE SET NULL,
    CONSTRAINT fk_re_new_plan FOREIGN KEY (new_route_plan_id) REFERENCES ROUTE_PLAN(route_plan_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- 5. Live Feeds, Telemetry & Safety
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS TRAFFIC_SAMPLE_POINT (
    sample_point_id INT AUTO_INCREMENT PRIMARY KEY,
    edge_id BIGINT NOT NULL,
    geom POINT SRID 4326 NOT NULL,
    corridor_name VARCHAR(100) NOT NULL,
    SPATIAL INDEX idx_tsp_geom (geom),
    CONSTRAINT fk_tsp_edge FOREIGN KEY (edge_id) REFERENCES ROAD_EDGE(edge_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS TRAFFIC_FLOW_SNAPSHOT (
    snapshot_id BIGINT AUTO_INCREMENT,
    sample_point_id INT NOT NULL,
    ts DATETIME NOT NULL,
    current_speed DECIMAL(5,2) NOT NULL,
    free_flow_speed DECIMAL(5,2) NOT NULL,
    congestion_index DECIMAL(4,3) NOT NULL,
    confidence DECIMAL(3,2) NOT NULL DEFAULT 1.00,
    source VARCHAR(50) NOT NULL DEFAULT 'tomtom',
    PRIMARY KEY (snapshot_id, ts),
    INDEX idx_tfs_point_ts (sample_point_id, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS INCIDENT (
    incident_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    source_incident_id VARCHAR(100) NOT NULL,
    category ENUM('accident', 'road_closed', 'road_works', 'jam', 'hazard', 'flooding', 'broken_down_vehicle', 'other') NOT NULL,
    severity ENUM('minor', 'moderate', 'major', 'critical') NOT NULL,
    description TEXT NULL,
    geom GEOMETRY SRID 4326 NOT NULL,
    start_ts TIMESTAMP NULL,
    end_ts TIMESTAMP NULL,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    SPATIAL INDEX idx_incident_geom (geom),
    UNIQUE KEY uq_source_incident (source, source_incident_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS INCIDENT_EDGE (
    incident_edge_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    incident_id BIGINT NOT NULL,
    edge_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_incident_edge (incident_id, edge_id),
    CONSTRAINT fk_ie_incident FOREIGN KEY (incident_id) REFERENCES INCIDENT(incident_id) ON DELETE CASCADE,
    CONSTRAINT fk_ie_edge FOREIGN KEY (edge_id) REFERENCES ROAD_EDGE(edge_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS WEATHER_OBS (
    obs_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    grid_point POINT SRID 4326 NOT NULL,
    ts TIMESTAMP NOT NULL,
    precip_mm DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    visibility_m DECIMAL(7,2) NOT NULL DEFAULT 10000.00,
    wind_kph DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    temp_c DECIMAL(4,1) NOT NULL DEFAULT 28.0,
    SPATIAL INDEX idx_weather_grid (grid_point),
    INDEX idx_weather_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ACCIDENT_HISTORICAL (
    hist_id INT AUTO_INCREMENT PRIMARY KEY,
    year INT NOT NULL,
    district_id INT NOT NULL,
    road_category VARCHAR(50) NOT NULL,
    accidents INT NOT NULL DEFAULT 0,
    fatalities INT NOT NULL DEFAULT 0,
    injuries INT NOT NULL DEFAULT 0,
    source_doc VARCHAR(255) NOT NULL,
    UNIQUE KEY uq_district_year_road (year, district_id, road_category),
    CONSTRAINT fk_ah_district FOREIGN KEY (district_id) REFERENCES DISTRICT(district_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS BLACKSPOT (
    blackspot_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    geom POINT SRID 4326 NOT NULL,
    source VARCHAR(100) NOT NULL,
    year INT NOT NULL,
    SPATIAL INDEX idx_blackspot_geom (geom)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS EDGE_RISK (
    risk_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    edge_id BIGINT NOT NULL UNIQUE,
    risk_score DECIMAL(5,2) NOT NULL CHECK (risk_score >= 0.00 AND risk_score <= 100.00),
    components JSON NULL,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_er_edge FOREIGN KEY (edge_id) REFERENCES ROAD_EDGE(edge_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- 6. Crowdsourced User Reports & Fuel Logging
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS USER_REPORT (
    report_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    report_type ENUM('pothole', 'blockage', 'accident', 'waterlogging', 'fuel_station_closed', 'out_of_fuel') NOT NULL,
    geom POINT SRID 4326 NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    upvotes INT NOT NULL DEFAULT 0,
    downvotes INT NOT NULL DEFAULT 0,
    status ENUM('pending', 'verified', 'expired', 'dismissed') NOT NULL DEFAULT 'pending',
    SPATIAL INDEX idx_user_report_geom (geom),
    CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES APP_USER(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS FUEL_LOG (
    log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    vehicle_id INT NOT NULL,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    odometer_km DECIMAL(9,2) NOT NULL,
    litres DECIMAL(5,2) NOT NULL CHECK (litres > 0),
    price_per_litre DECIMAL(6,2) NOT NULL CHECK (price_per_litre > 0),
    full_tank BOOLEAN NOT NULL DEFAULT TRUE,
    station_id BIGINT NULL,
    CONSTRAINT fk_fl_vehicle FOREIGN KEY (vehicle_id) REFERENCES VEHICLE(vehicle_id) ON DELETE CASCADE,
    CONSTRAINT fk_fl_station FOREIGN KEY (station_id) REFERENCES FUEL_STATION(station_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- 7. Model Registry, Ingestion Runs & Auditing
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ML_MODEL_REGISTRY (
    model_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    version VARCHAR(20) NOT NULL,
    trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metrics JSON NULL,
    artifact_path VARCHAR(255) NOT NULL,
    data_window VARCHAR(100) NULL,
    UNIQUE KEY uq_model_version (name, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS INGESTION_RUN (
    run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    started TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished TIMESTAMP NULL,
    status ENUM('running', 'success', 'failed') NOT NULL DEFAULT 'running',
    rows_in INT DEFAULT 0,
    error_message TEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS AUDIT_LOG (
    audit_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(50) NOT NULL,
    operation ENUM('INSERT', 'UPDATE', 'DELETE') NOT NULL,
    record_id BIGINT NOT NULL,
    changed_by VARCHAR(100) NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    old_value JSON NULL,
    new_value JSON NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------------------------
-- Seed Default Road Types with Baseline Speeds and Fuel Multipliers
-- ------------------------------------------------------------------------------
INSERT IGNORE INTO ROAD_TYPE (road_type, default_speed_kph, fuel_factor, description) VALUES
('motorway', 100.00, 1.05, 'Access-controlled expressways (e.g. Bangalore-Mysore Expwy)'),
('motorway_link', 60.00, 1.10, 'Expressway entry/exit ramps'),
('trunk', 80.00, 1.00, 'National Highways (e.g. NH 48, NH 44)'),
('trunk_link', 50.00, 1.10, 'National Highway ramps and slip roads'),
('primary', 65.00, 1.05, 'State Highways (e.g. SH 4, SH 9)'),
('primary_link', 45.00, 1.15, 'State Highway ramps'),
('secondary', 50.00, 1.15, 'Major District Roads (MDR) connecting towns'),
('secondary_link', 35.00, 1.20, 'Connecting links to secondary roads'),
('tertiary', 40.00, 1.25, 'Other District Roads (ODR) connecting villages'),
('tertiary_link', 30.00, 1.30, 'Connecting links to tertiary roads'),
('unclassified', 35.00, 1.35, 'Minor connecting through-roads');

-- Seed POI Categories
INSERT IGNORE INTO POI_CATEGORY (category_id, description) VALUES
('hospital', 'Hospital, medical clinic or trauma care center'),
('police', 'Police station or highway patrol outpost'),
('charging_station', 'Electric vehicle (EV) fast-charging facility'),
('toll', 'Highway toll plaza / toll collection point'),
('rest_area', 'Highway rest area, food court or highway plaza');

SET FOREIGN_KEY_CHECKS = 1;
