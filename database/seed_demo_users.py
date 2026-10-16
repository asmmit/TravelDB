"""
Demo Users & Vehicles Seeder for TravelDB.
Creates standard demo driver accounts and vehicle profiles for trip planning and fuel simulation.
"""

import os
import sys
import argon2

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db_connection import get_db_connection


def seed_users_and_vehicles():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    ph = argon2.PasswordHasher()
    hashed_pw = ph.hash("traveldb2026")

    # 1. Insert Demo User
    cursor.execute("""
        INSERT INTO APP_USER (email, password_hash, role)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            password_hash = VALUES(password_hash),
            role = VALUES(role);
    """, ("driver@traveldb.local", hashed_pw, "driver"))
    conn.commit()

    cursor.execute("SELECT user_id FROM APP_USER WHERE email = 'driver@traveldb.local';")
    user_id = cursor.fetchone()["user_id"]
    print(f"[+] Demo user 'driver@traveldb.local' confirmed (user_id={user_id}).")

    # 2. Insert Demo Vehicles
    vehicles = [
        {
            "fuel_type": "petrol",
            "tank_capacity_l": 37.0,
            "rated_mileage_kmpl": 17.5,
            "vehicle_class": "hatchback",
            "make_model": "Maruti Swift VXi"
        },
        {
            "fuel_type": "diesel",
            "tank_capacity_l": 45.0,
            "rated_mileage_kmpl": 21.0,
            "vehicle_class": "sedan",
            "make_model": "Hyundai Verna CRDi"
        },
        {
            "fuel_type": "petrol",
            "tank_capacity_l": 40.0,
            "rated_mileage_kmpl": 15.0,
            "vehicle_class": "sedan",
            "make_model": "Honda City i-VTEC"
        }
    ]

    for v in vehicles:
        cursor.execute("""
            SELECT vehicle_id FROM VEHICLE
            WHERE user_id = %s AND make_model = %s;
        """, (user_id, v["make_model"]))
        row = cursor.fetchone()
        if not row:
            cursor.execute("""
                INSERT INTO VEHICLE (user_id, fuel_type, tank_capacity_l, rated_mileage_kmpl, vehicle_class, make_model)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (user_id, v["fuel_type"], v["tank_capacity_l"], v["rated_mileage_kmpl"], v["vehicle_class"], v["make_model"]))
            print(f"[+] Inserted vehicle: {v['make_model']}")
        else:
            print(f"[-] Vehicle already exists: {v['make_model']} (id={row['vehicle_id']})")

    conn.commit()
    cursor.close()
    conn.close()
    print("[OK] Seeding complete.")


if __name__ == "__main__":
    seed_users_and_vehicles()
