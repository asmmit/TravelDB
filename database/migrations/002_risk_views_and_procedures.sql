-- ==============================================================================
-- Migration: 002_risk_views_and_procedures.sql
-- Project: TravelDB - Phase 3 Risk Engine Views & Stored Procedures
-- Target: MySQL 8.0
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. View: High Risk Corridor Edges
-- Unrolls JSON components for immediate spatial inspection and dashboard display
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_high_risk_corridor_edges AS
SELECT 
    r.edge_id,
    e.road_name,
    e.ref,
    e.road_type,
    e.length_m,
    e.speed_kph,
    r.risk_score,
    r.components->>'$.district_name' AS district_name,
    r.components->>'$.nearest_blackspot' AS nearest_blackspot,
    CAST(r.components->>'$.blackspot_dist_m' AS DECIMAL(8,1)) AS blackspot_dist_m,
    CAST(r.components->>'$.blackspot_penalty' AS DECIMAL(5,2)) AS blackspot_penalty,
    CAST(r.components->>'$.weather_penalty' AS DECIMAL(5,2)) AS weather_penalty,
    r.computed_at
FROM EDGE_RISK r
JOIN ROAD_EDGE e ON r.edge_id = e.edge_id
WHERE r.risk_score >= 40.00;

-- ------------------------------------------------------------------------------
-- 2. View: Fuel Price State Comparison
-- ------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fuel_price_summary AS
SELECT 
    s.name AS state_name,
    s.code AS state_code,
    f.fuel_type,
    f.price_per_litre,
    f.as_of_date,
    f.source
FROM FUEL_PRICE f
JOIN STATE s ON f.state_id = s.state_id;

-- ------------------------------------------------------------------------------
-- 3. Stored Procedure: Corridor Risk Summary
-- ------------------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_get_corridor_risk_summary;

CREATE PROCEDURE sp_get_corridor_risk_summary()
BEGIN
    SELECT 
        COUNT(*) AS total_edges,
        MIN(risk_score) AS min_risk_score,
        ROUND(AVG(risk_score), 2) AS avg_risk_score,
        MAX(risk_score) AS max_risk_score,
        SUM(CASE WHEN risk_score >= 60 THEN 1 ELSE 0 END) AS high_risk_edges,
        SUM(CASE WHEN risk_score >= 40 AND risk_score < 60 THEN 1 ELSE 0 END) AS medium_risk_edges,
        SUM(CASE WHEN risk_score < 40 THEN 1 ELSE 0 END) AS low_risk_edges
    FROM EDGE_RISK;
END;
