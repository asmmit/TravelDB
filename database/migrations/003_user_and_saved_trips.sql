-- ============================================================================
-- TravelDB Migration 003: User Profile Enhancement & Saved Trips System
-- Adds emergency profile fields to APP_USER and creates SAVED_TRIP.
-- ============================================================================

USE traveldb;

-- 1. Extend APP_USER with traveler profile and emergency details
ALTER TABLE app_user
    ADD COLUMN username VARCHAR(64) NULL AFTER user_id,
    ADD COLUMN full_name VARCHAR(128) NULL AFTER password_hash,
    ADD COLUMN age INT NULL AFTER full_name,
    ADD COLUMN gender VARCHAR(20) NULL AFTER age,
    ADD COLUMN phone VARCHAR(20) NULL AFTER gender,
    ADD COLUMN emergency_phone VARCHAR(20) NULL AFTER phone;

-- Populate demo user profile fields
UPDATE app_user
SET username = 'demo_driver',
    full_name = 'Asmit Sharma',
    age = 20,
    gender = 'Male',
    phone = '+91 98765 43210',
    emergency_phone = '+91 98111 22334'
WHERE user_id = 1;

-- 2. SAVED_TRIP: User-saved trip plans with distance, fuel, cost, and travel notes
CREATE TABLE IF NOT EXISTS SAVED_TRIP (
    saved_trip_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    trip_id BIGINT NULL,
    trip_title VARCHAR(128) NOT NULL,
    origin_name VARCHAR(128) NOT NULL,
    destination_name VARCHAR(128) NOT NULL,
    vehicle_name VARCHAR(128) NOT NULL,
    distance_km DECIMAL(8,2) NOT NULL,
    fuel_liters DECIMAL(6,2) NOT NULL,
    refuel_stops INT NOT NULL DEFAULT 0,
    estimated_cost_inr DECIMAL(10,2) NOT NULL,
    trip_notes TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_saved_trip_user FOREIGN KEY (user_id) REFERENCES app_user(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_saved_trip_trip FOREIGN KEY (trip_id) REFERENCES TRIP(trip_id) ON DELETE SET NULL,
    INDEX idx_saved_trip_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Seed an initial sample saved trip
INSERT IGNORE INTO SAVED_TRIP (saved_trip_id, user_id, trip_title, origin_name, destination_name, vehicle_name, distance_km, fuel_liters, refuel_stops, estimated_cost_inr, trip_notes)
VALUES (
    1,
    1,
    'NH 48 Weekend Corridor Run',
    'Poonamallee (Chennai West)',
    'Damal (NH 48 KM 81.5)',
    'Maruti Swift VXi (Petrol)',
    80.33,
    4.75,
    1,
    3369.08,
    'Planned refuel at BPCL pump near Sriperumbudur. Check tire pressures before departure.'
);
