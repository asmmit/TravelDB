"""
Database Migration Runner for TravelDB.
Discovers and executes numbered SQL migrations in database/migrations/
Tracks applied migrations in the SCHEMA_MIGRATIONS table.
"""

import os
import glob
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "traveldb")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

def init_database():
    """Ensures the target database exists."""
    print(f"Connecting to MySQL at {DB_HOST}:{DB_PORT} as '{DB_USER}'...")
    conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD
    )
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    print(f"Database `{DB_NAME}` confirmed/created.")
    cursor.close()
    conn.close()

def run_migrations():
    """Runs all pending migrations in order."""
    init_database()

    conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = conn.cursor()

    # Track migrations in a metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS SCHEMA_MIGRATIONS (
            version VARCHAR(100) PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)
    conn.commit()

    cursor.execute("SELECT version FROM SCHEMA_MIGRATIONS;")
    applied = {row[0] for row in cursor.fetchall()}

    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    migration_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))

    if not migration_files:
        print("No migration files found in database/migrations/")
        return

    for file_path in migration_files:
        version = os.path.basename(file_path)
        if version in applied:
            print(f"[-] Migration already applied: {version}")
            continue

        print(f"[+] Applying migration: {version}...")
        with open(file_path, "r", encoding="utf-8") as f:
            sql_script = f.read()

        # Parse individual SQL statements (handling comments, stored procedures, and multi-line definitions)
        statements = []
        cur_stmt = []
        in_routine = False

        for line in sql_script.splitlines():
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("--") or trimmed.startswith("#"):
                continue

            upper_trimmed = trimmed.upper()
            if "CREATE PROCEDURE" in upper_trimmed or "CREATE FUNCTION" in upper_trimmed or "CREATE TRIGGER" in upper_trimmed:
                in_routine = True

            cur_stmt.append(line)

            if in_routine:
                if upper_trimmed == "END;" or upper_trimmed.endswith("END;"):
                    stmt = "\n".join(cur_stmt).strip()
                    if stmt:
                        statements.append(stmt)
                    cur_stmt = []
                    in_routine = False
            else:
                if trimmed.endswith(";"):
                    stmt = "\n".join(cur_stmt).strip()
                    if stmt:
                        statements.append(stmt)
                    cur_stmt = []

        try:
            for stmt in statements:
                cursor.execute(stmt)
            
            cursor.execute("INSERT INTO SCHEMA_MIGRATIONS (version) VALUES (%s);", (version,))
            conn.commit()
            print(f"[OK] Successfully applied {version}")
        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed applying {version}: {e}")
            raise e

    cursor.close()
    conn.close()
    print("All migrations completed successfully!")

if __name__ == "__main__":
    run_migrations()
