"""
Master Ingestion Pipeline Scheduler for TravelDB.
Orchestrates periodic polling of:
- Open-Meteo Weather (every 30 minutes)
- Live Traffic Flow Snapshots (every 5 minutes)
- Live Incident & Closure Feeds (every 10 minutes)
Tracks all executions in MySQL INGESTION_RUN table.
Supports running once synchronously (--run-once) for verification and testing.
"""

import os
import sys
import argparse
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

# Add parent directory to path to import database module
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from ingestion.weather_ingest import fetch_and_store_weather
from ingestion.traffic_ingest import poll_traffic_flow
from ingestion.incident_ingest import poll_incidents

def run_all_jobs_once():
    """Executes a single cycle of all ingestion pipelines synchronously."""
    print("=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING FULL INGESTION CYCLE")
    print("=" * 60)

    # 1. Weather
    try:
        fetch_and_store_weather()
    except Exception as e:
        print(f"[!] Weather job exception: {e}")

    # 2. Traffic Flow
    try:
        poll_traffic_flow()
    except Exception as e:
        print(f"[!] Traffic flow job exception: {e}")

    # 3. Incidents
    try:
        poll_incidents()
    except Exception as e:
        print(f"[!] Incidents job exception: {e}")

    print("=" * 60)
    print("CYCLE COMPLETE")
    print("=" * 60)

def start_scheduler():
    scheduler = BlockingScheduler()

    # Schedule periodic jobs
    scheduler.add_job(poll_traffic_flow, 'interval', minutes=5, id='job_traffic_flow', next_run_time=datetime.now())
    scheduler.add_job(poll_incidents, 'interval', minutes=10, id='job_incidents', next_run_time=datetime.now())
    scheduler.add_job(fetch_and_store_weather, 'interval', minutes=30, id='job_weather', next_run_time=datetime.now())

    print("\n[+] TravelDB Ingestion Scheduler Started!")
    print("    - Traffic Flow Snapshots: every 5 minutes")
    print("    - Traffic Incidents:      every 10 minutes")
    print("    - Weather Observations:   every 30 minutes")
    print("Press Ctrl+C to terminate.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[!] Scheduler stopped cleanly.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TravelDB Pipeline Scheduler")
    parser.add_argument("--run-once", action="store_true", help="Run one ingestion cycle immediately and exit")
    args = parser.parse_args()

    if args.run_once:
        run_all_jobs_once()
    else:
        start_scheduler()
