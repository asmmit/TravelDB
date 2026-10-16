"""
Database Connection Manager for TravelDB.
Provides thread-safe connection pooling to MySQL 8.0 with automatic reconnection.
"""

import os
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "traveldb")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

_pool = None

def get_connection_pool(pool_size=5):
    """
    Initializes or retrieves the singleton MySQL connection pool.
    """
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="traveldb_pool",
            pool_size=pool_size,
            pool_reset_session=True,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            autocommit=True
        )
    return _pool

def get_db_connection():
    """
    Retrieves a connection from the pool.
    Caller is responsible for closing the connection (which returns it to the pool).
    """
    pool = get_connection_pool()
    conn = pool.get_connection()
    return conn

def test_connection():
    """
    Tests whether the MySQL database is reachable with the current credentials.
    Returns (True, version) or (False, error_message).
    """
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cursor = conn.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return True, version
    except Exception as e:
        return False, str(e)
