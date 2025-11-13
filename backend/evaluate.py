import csv
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging

import requests
import numpy as np
import psycopg2
from psycopg2.extras import execute_batch
import schedule
import time

# Database configuration - can be overridden by environment variables
import os

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "103.253.20.30"),
    "port": int(os.environ.get("DB_PORT", 26001)),
    "database": os.environ.get("DB_NAME", "robot-workflow-user-log-test"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "postgres")
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Create and return a database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        raise


def create_metric_by_day_table():
    """Create metric_by_day table if it doesn't exist."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metric_by_day (
                    id SERIAL PRIMARY KEY,
                    date_time DATE NOT NULL,
                    bot_id INTEGER,
                    server_response_p90 NUMERIC(10, 2),
                    server_response_p99 NUMERIC(10, 2),
                    llm_response_p90 NUMERIC(10, 2),
                    llm_response_p99 NUMERIC(10, 2),
                    fast_response_p90 NUMERIC(10, 2),
                    fast_response_p99 NUMERIC(10, 2),
                    total_records INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(date_time, bot_id)
                );
            """)
            conn.commit()
            logger.info("metric_by_day table created or already exists")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating metric_by_day table: {e}")
        raise
    finally:
        conn.close()


def check_data_exists_for_date(target_date: date, metric_type: str = "learn") -> bool:
    """
    Check if data already exists in latency_metric table for the given date and type.
    
    Args:
        target_date: The date to check
        metric_type: Type of metric to check (default: "learn")
    
    Returns:
        True if data exists, False otherwise
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM latency_metric 
                WHERE date_time = %s AND type = %s
            """, (target_date, metric_type))
            count = cur.fetchone()[0]
            return count > 0
    except Exception as e:
        logger.error(f"Error checking data existence: {e}")
        return False
    finally:
        conn.close()


def save_latency_data_to_db(
    data_rows: List[Dict[str, Any]], 
    target_date: date,
    metric_type: str = "workflow",
    skip_if_exists: bool = True
) -> int:
    """
    Save latency data to latency_metric table.
    
    Args:
        data_rows: List of dictionaries containing latency data
        target_date: The date for which data is being saved
        metric_type: Type of metric (default: "workflow")
        skip_if_exists: If True, skip insertion if data already exists for the date
    
    Returns:
        Number of records inserted
    """
    if not data_rows:
        logger.warning("No data rows to save")
        return 0
    
    # Check if data already exists
    if skip_if_exists and check_data_exists_for_date(target_date, metric_type):
        logger.info(f"Data already exists for {target_date} (type: {metric_type}). Skipping insertion.")
        return 0
    
    conn = get_db_connection()
    inserted_count = 0
    
    try:
        with conn.cursor() as cur:
            insert_query = """
                INSERT INTO latency_metric 
                (bot_id, conversation_id, fast_response_time, llm_response_time, 
                 server_response_time, type, date_time, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            records = []
            for row in data_rows:
                bot_id = row.get("bot_id")
                conversation_id = row.get("conversation_id")
                fast_response_time = row.get("fast_response_time")
                llm_response_time = row.get("llm_response_time")
                server_response_time = row.get("server_response_time")
                
                # Skip if essential fields are missing
                if not conversation_id:
                    continue
                
                records.append((
                    bot_id,
                    conversation_id,
                    fast_response_time,
                    llm_response_time,
                    server_response_time,
                    metric_type,
                    target_date,
                    datetime.now()
                ))
            
            if records:
                execute_batch(cur, insert_query, records, page_size=1000)
                inserted_count = len(records)
                conn.commit()
                logger.info(f"Inserted {inserted_count} records into latency_metric table")
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving latency data to database: {e}")
        raise
    finally:
        conn.close()
    
    return inserted_count


def calculate_and_save_daily_metrics(target_date: date, bot_id: Optional[int] = None):
    """
    Calculate daily metrics (p90, p99) from latency_metric table and save to metric_by_day.
    
    Args:
        target_date: The date for which to calculate metrics
        bot_id: Optional bot_id filter. If None, calculates for all bots
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Build query to get data for the date
            if bot_id:
                query = """
                    SELECT 
                        bot_id,
                        server_response_time,
                        llm_response_time,
                        fast_response_time
                    FROM latency_metric
                    WHERE date_time = %s AND bot_id = %s
                    AND (server_response_time IS NOT NULL 
                         OR llm_response_time IS NOT NULL 
                         OR fast_response_time IS NOT NULL)
                """
                params = (target_date, bot_id)
            else:
                query = """
                    SELECT 
                        bot_id,
                        server_response_time,
                        llm_response_time,
                        fast_response_time
                    FROM latency_metric
                    WHERE date_time = %s
                    AND (server_response_time IS NOT NULL 
                         OR llm_response_time IS NOT NULL 
                         OR fast_response_time IS NOT NULL)
                """
                params = (target_date,)
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            if not rows:
                logger.warning(f"No data found for date {target_date}")
                return
            
            # Group by bot_id and calculate metrics
            bot_data = {}
            for row in rows:
                bot_id_val = row[0]
                server_response = row[1]
                llm_response = row[2]
                fast_response = row[3]
                
                if bot_id_val not in bot_data:
                    bot_data[bot_id_val] = {
                        "server_response": [],
                        "llm_response": [],
                        "fast_response": []
                    }
                
                if server_response is not None:
                    bot_data[bot_id_val]["server_response"].append(float(server_response))
                if llm_response is not None:
                    bot_data[bot_id_val]["llm_response"].append(float(llm_response))
                if fast_response is not None:
                    bot_data[bot_id_val]["fast_response"].append(float(fast_response))
            
            # Calculate percentiles for each bot
            for bot_id_val, metrics in bot_data.items():
                server_p90 = calculate_percentiles(metrics["server_response"], 90) if metrics["server_response"] else None
                server_p99 = calculate_percentiles(metrics["server_response"], 99) if metrics["server_response"] else None
                llm_p90 = calculate_percentiles(metrics["llm_response"], 90) if metrics["llm_response"] else None
                llm_p99 = calculate_percentiles(metrics["llm_response"], 99) if metrics["llm_response"] else None
                fast_p90 = calculate_percentiles(metrics["fast_response"], 90) if metrics["fast_response"] else None
                fast_p99 = calculate_percentiles(metrics["fast_response"], 99) if metrics["fast_response"] else None
                
                total_records = len(metrics["server_response"]) + len(metrics["llm_response"]) + len(metrics["fast_response"])
                
                # Upsert into metric_by_day
                upsert_query = """
                    INSERT INTO metric_by_day 
                    (date_time, bot_id, server_response_p90, server_response_p99,
                     llm_response_p90, llm_response_p99, fast_response_p90, fast_response_p99,
                     total_records, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date_time, bot_id)
                    DO UPDATE SET
                        server_response_p90 = EXCLUDED.server_response_p90,
                        server_response_p99 = EXCLUDED.server_response_p99,
                        llm_response_p90 = EXCLUDED.llm_response_p90,
                        llm_response_p99 = EXCLUDED.llm_response_p99,
                        fast_response_p90 = EXCLUDED.fast_response_p90,
                        fast_response_p99 = EXCLUDED.fast_response_p99,
                        total_records = EXCLUDED.total_records,
                        updated_at = EXCLUDED.updated_at
                """
                
                cur.execute(upsert_query, (
                    target_date,
                    bot_id_val,
                    server_p90,
                    server_p99,
                    llm_p90,
                    llm_p99,
                    fast_p90,
                    fast_p99,
                    total_records,
                    datetime.now()
                ))
            
            conn.commit()
            logger.info(f"Calculated and saved daily metrics for {target_date}, {len(bot_data)} bot(s)")
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Error calculating daily metrics: {e}")
        raise
    finally:
        conn.close()


def get_daily_metrics_from_db(start_date: date, end_date: date, bot_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get daily metrics from metric_by_day table for UI display.
    
    Args:
        start_date: Start date for query
        end_date: End date for query
        bot_id: Optional bot_id filter
    
    Returns:
        List of daily metrics dictionaries
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            if bot_id:
                query = """
                    SELECT 
                        date_time, bot_id,
                        server_response_p90, server_response_p99,
                        llm_response_p90, llm_response_p99,
                        fast_response_p90, fast_response_p99,
                        total_records
                    FROM metric_by_day
                    WHERE date_time BETWEEN %s AND %s AND bot_id = %s
                    ORDER BY date_time DESC, bot_id
                """
                params = (start_date, end_date, bot_id)
            else:
                query = """
                    SELECT 
                        date_time, bot_id,
                        server_response_p90, server_response_p99,
                        llm_response_p90, llm_response_p99,
                        fast_response_p90, fast_response_p99,
                        total_records
                    FROM metric_by_day
                    WHERE date_time BETWEEN %s AND %s
                    ORDER BY date_time DESC, bot_id
                """
                params = (start_date, end_date)
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "date_time": row[0],
                    "bot_id": row[1],
                    "server_response_p90": float(row[2]) if row[2] else None,
                    "server_response_p99": float(row[3]) if row[3] else None,
                    "llm_response_p90": float(row[4]) if row[4] else None,
                    "llm_response_p99": float(row[5]) if row[5] else None,
                    "fast_response_p90": float(row[6]) if row[6] else None,
                    "fast_response_p99": float(row[7]) if row[7] else None,
                    "total_records": row[8]
                })
            
            return results
            
    except Exception as e:
        logger.error(f"Error getting daily metrics from database: {e}")
        raise
    finally:
        conn.close()


def get_latency_data_from_db(start_date: date, end_date: date, bot_id: Optional[int] = None) -> Dict[str, List[float]]:
    """
    Get raw latency data from database and calculate p90, p99 for UI refresh.
    
    Args:
        start_date: Start date for query
        end_date: End date for query
        bot_id: Optional bot_id filter
    
    Returns:
        Dictionary with lists of response times and calculated percentiles
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            if bot_id:
                query = """
                    SELECT 
                        server_response_time,
                        llm_response_time,
                        fast_response_time
                    FROM latency_metric
                    WHERE date_time BETWEEN %s AND %s AND bot_id = %s
                    AND (server_response_time IS NOT NULL 
                         OR llm_response_time IS NOT NULL 
                         OR fast_response_time IS NOT NULL)
                """
                params = (start_date, end_date, bot_id)
            else:
                query = """
                    SELECT 
                        server_response_time,
                        llm_response_time,
                        fast_response_time
                    FROM latency_metric
                    WHERE date_time BETWEEN %s AND %s
                    AND (server_response_time IS NOT NULL 
                         OR llm_response_time IS NOT NULL 
                         OR fast_response_time IS NOT NULL)
                """
                params = (start_date, end_date)
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            server_response_times = []
            llm_response_times = []
            fast_response_times = []
            
            for row in rows:
                if row[0] is not None:
                    server_response_times.append(float(row[0]))
                if row[1] is not None:
                    llm_response_times.append(float(row[1]))
                if row[2] is not None:
                    fast_response_times.append(float(row[2]))
            
            # Calculate percentiles
            results = {
                "server_response_time": {
                    "values": server_response_times,
                    "p90": calculate_percentiles(server_response_times, 90) if server_response_times else 0.0,
                    "p99": calculate_percentiles(server_response_times, 99) if server_response_times else 0.0,
                    "count": len(server_response_times)
                },
                "llm_response_time": {
                    "values": llm_response_times,
                    "p90": calculate_percentiles(llm_response_times, 90) if llm_response_times else 0.0,
                    "p99": calculate_percentiles(llm_response_times, 99) if llm_response_times else 0.0,
                    "count": len(llm_response_times)
                },
                "fast_response_time": {
                    "values": fast_response_times,
                    "p90": calculate_percentiles(fast_response_times, 90) if fast_response_times else 0.0,
                    "p99": calculate_percentiles(fast_response_times, 99) if fast_response_times else 0.0,
                    "count": len(fast_response_times)
                }
            }
            
            return results
            
    except Exception as e:
        logger.error(f"Error getting latency data from database: {e}")
        raise
    finally:
        conn.close()


def daily_job(auth_token: str = None, monitor_token: str = None, target_date: Optional[date] = None, metric_type: str = "learn"):
    """
    Daily job to fetch data from API and save to latency_metric table.
    This function runs once per day at 2:00 AM and fetches data from the previous day.
    
    Args:
        auth_token: Token for conversations/ids API (optional, uses hardcoded token)
        monitor_token: Token for monitor API (optional, uses hardcoded token)
        target_date: Optional target date. If None, uses yesterday's date
        metric_type: Type of metric to save (default: "learn")
    """
    logger.info(f"Starting daily job for type: {metric_type}...")
    
    # Use hardcoded tokens if not provided
    # Note: get_conversation_ids uses fixed_token internally (AUTH_TOKEN)
    # get_response_times uses MONITOR_TOKEN
    monitor_token = monitor_token or MONITOR_TOKEN
    
    # Get target date (default to yesterday)
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    
    # Format date for API (DD/MM/YYYY)
    date_str = target_date.strftime("%d/%m/%Y")
    logger.info(f"Target date: {target_date} (formatted as {date_str} for API)")
    
    try:
        # Step 1: Fetch conversation IDs for the selected date
        # get_conversation_ids uses fixed_token internally (b1812cb7-2513-408b-bb22-d9f91b099fbd)
        logger.info(f"Fetching conversation IDs for {date_str} (date: {target_date})...")
        conversation_ids = get_conversation_ids(date_str, date_str)
        logger.info(f"Found {len(conversation_ids)} conversations")
        
        # Step 2: Fetch response times and collect data
        logger.info("Fetching response times for each conversation...")
        raw_rows: List[Dict[str, Any]] = []
        
        for idx, conv_id in enumerate(conversation_ids, 1):
            try:
                response_data = get_response_times(conv_id, monitor_token)
                for item in response_data:
                    row = {"conversation_id": conv_id}
                    if isinstance(item, dict):
                        row.update(item)
                    raw_rows.append(row)
                
                if idx % 100 == 0:
                    logger.info(f"Processed {idx}/{len(conversation_ids)} conversations...")
            except Exception as e:
                logger.warning(f"Error processing conversation {conv_id}: {e}")
                continue
        
        logger.info(f"Collected {len(raw_rows)} response time records")
        
        # Step 3: Save to database with specified type and target_date
        logger.info(f"Saving {len(raw_rows)} records to database for date: {target_date} (type: {metric_type})...")
        inserted_count = save_latency_data_to_db(raw_rows, target_date, metric_type=metric_type)
        logger.info(f"Saved {inserted_count} records to latency_metric table with date_time={target_date}, type={metric_type}")
        
        logger.info(f"Daily job completed successfully for {date_str} (date: {target_date}, type: {metric_type}, records: {inserted_count})")
        
    except Exception as e:
        logger.error(f"Error in daily job: {e}", exc_info=True)


def get_daily_metrics_from_latency_table(start_date: date, end_date: date, bot_id: Optional[int] = None, metric_type: str = "learn") -> List[Dict[str, Any]]:
    """
    Get daily metrics by calculating from latency_metric table.
    Groups data by date and calculates p90, p99 for each day.
    
    Args:
        start_date: Start date for query
        end_date: End date for query
        bot_id: Optional bot_id filter
        metric_type: Type of metric to filter (default: "learn")
                   Maps: "learn" -> "workflow", "talk" -> "talk"
    
    Returns:
        List of daily metrics dictionaries, sorted by date (newest first)
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Map metric_type to database type
            # For now, "learn" maps to "workflow" (existing data)
            db_type = "workflow" if metric_type == "learn" else metric_type
            
            # Build query to get data grouped by date, filtered by type
            if bot_id:
                query = """
                    SELECT 
                        date_time,
                        bot_id,
                        server_response_time,
                        llm_response_time,
                        fast_response_time
                    FROM latency_metric
                    WHERE date_time BETWEEN %s AND %s 
                    AND type = %s
                    AND bot_id = %s
                    AND (server_response_time IS NOT NULL 
                         OR llm_response_time IS NOT NULL 
                         OR fast_response_time IS NOT NULL)
                    ORDER BY date_time DESC
                """
                params = (start_date, end_date, db_type, bot_id)
            else:
                query = """
                    SELECT 
                        date_time,
                        bot_id,
                        server_response_time,
                        llm_response_time,
                        fast_response_time
                    FROM latency_metric
                    WHERE date_time BETWEEN %s AND %s 
                    AND type = %s
                    AND (server_response_time IS NOT NULL 
                         OR llm_response_time IS NOT NULL 
                         OR fast_response_time IS NOT NULL)
                    ORDER BY date_time DESC
                """
                params = (start_date, end_date, db_type)
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            # Group by date only (aggregate all bots for each day)
            daily_data = {}
            for row in rows:
                date_key = row[0]  # date_time
                bot_id_val = row[1]
                server_response = row[2]
                llm_response = row[3]
                fast_response = row[4]
                
                # Always group by date only to show one point per day on chart
                key = date_key
                
                if key not in daily_data:
                    daily_data[key] = {
                        "date_time": date_key,
                        "bot_ids": set(),  # Track all bot_ids for this date
                        "server_response": [],
                        "llm_response": [],
                        "fast_response": []
                    }
                
                # Add bot_id to set
                if bot_id_val:
                    daily_data[key]["bot_ids"].add(bot_id_val)
                
                # Collect all response times for this date (from all bots)
                if server_response is not None:
                    daily_data[key]["server_response"].append(float(server_response))
                if llm_response is not None:
                    daily_data[key]["llm_response"].append(float(llm_response))
                if fast_response is not None:
                    daily_data[key]["fast_response"].append(float(fast_response))
            
            # Calculate percentiles for each day
            results = []
            for key, data in daily_data.items():
                # Get list of bot_ids (or None if filtering by specific bot)
                bot_ids_list = sorted(list(data["bot_ids"])) if data["bot_ids"] else []
                bot_id_display = bot_ids_list[0] if len(bot_ids_list) == 1 else (f"{len(bot_ids_list)} bots" if len(bot_ids_list) > 1 else None)
                
                # Convert date_time to ISO string format
                date_time_str = data["date_time"].isoformat() if isinstance(data["date_time"], date) else str(data["date_time"])
                
                results.append({
                    "date_time": date_time_str,
                    "bot_id": bot_id_display,
                    "bot_ids": bot_ids_list,  # Keep list for reference
                    "server_response_p90": calculate_percentiles(data["server_response"], 90) if data["server_response"] else None,
                    "server_response_p99": calculate_percentiles(data["server_response"], 99) if data["server_response"] else None,
                    "llm_response_p90": calculate_percentiles(data["llm_response"], 90) if data["llm_response"] else None,
                    "llm_response_p99": calculate_percentiles(data["llm_response"], 99) if data["llm_response"] else None,
                    "fast_response_p90": calculate_percentiles(data["fast_response"], 90) if data["fast_response"] else None,
                    "fast_response_p99": calculate_percentiles(data["fast_response"], 99) if data["fast_response"] else None,
                    "total_records": len(data["server_response"]) + len(data["llm_response"]) + len(data["fast_response"])
                })
            
            # Sort by date (newest first)
            results.sort(key=lambda x: x["date_time"], reverse=True)
            
            return results
            
    except Exception as e:
        logger.error(f"Error getting daily metrics from latency table: {e}")
        raise
    finally:
        conn.close()


def get_last_7_days_metrics(bot_id: Optional[int] = None, metric_type: str = "learn") -> List[Dict[str, Any]]:
    """
    Get metrics for the last 7 days for UI display.
    Calculates directly from latency_metric table.
    
    Args:
        bot_id: Optional bot_id filter
        metric_type: Type of metric to filter (default: "learn")
    
    Returns:
        List of daily metrics for last 7 days
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=6)  # Last 7 days including today
    
    return get_daily_metrics_from_latency_table(start_date, end_date, bot_id, metric_type)


def refresh_ui_metrics(bot_id: Optional[int] = None, metric_type: str = "learn") -> Dict[str, Any]:
    """
    Refresh and recalculate metrics from database for UI display.
    Gets data from latency_metric table, calculates p90, p99 for each day.
    Returns 7 days of metrics grouped by date.
    
    Args:
        bot_id: Optional bot_id filter
        metric_type: Type of metric to filter (default: "learn")
    
    Returns:
        Dictionary containing daily metrics for last 7 days
    """
    logger.info(f"Refreshing UI metrics for type: {metric_type}...")
    
    # Get last 7 days data (from today going back)
    end_date = date.today()
    start_date = end_date - timedelta(days=6)  # Last 7 days including today
    
    # Get daily metrics calculated from latency_metric table
    daily_metrics = get_last_7_days_metrics(bot_id, metric_type)
    
    results = {
        "daily_metrics": daily_metrics,
        "date_range": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        },
        "metric_type": metric_type
    }
    
    logger.info(f"UI metrics refreshed successfully. Found {len(daily_metrics)} days of data for type: {metric_type}.")
    return results


def run_scheduler(auth_token: str, monitor_token: str, run_time: str = "02:00", metric_type: str = "learn"):
    """
    Run the daily scheduler to execute the daily job.
    Daily job will fetch data from the previous day and save to latency_metric table.
    
    Args:
        auth_token: Token for conversations/ids API
        monitor_token: Token for monitor API (response_time, conversations)
        run_time: Time to run daily job in HH:MM format (default: "02:00")
        metric_type: Type of metric to save (default: "learn")
    """
    logger.info(f"Starting scheduler. Daily job will run at {run_time} every day to fetch previous day's data (type: {metric_type}).")
    
    # Schedule daily job with metric_type
    schedule.every().day.at(run_time).do(daily_job, auth_token=auth_token, monitor_token=monitor_token, metric_type=metric_type)
    
    # Run scheduler
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def calculate_percentiles(response_times: List[float], percentile: float) -> float:
    """Calculate percentile value from a list of response times."""
    if not response_times:
        return 0.0
    return np.percentile(response_times, percentile)


# Hardcoded tokens
AUTH_TOKEN = "b1812cb7-2513-408b-bb22-d9f91b099fbd"  # Token cho conversations/ids API
MONITOR_TOKEN = "dd4e758e-51ed-d9fb-7b25-1e4f704f4cea"  # Token cho monitor API (response_time, conversations)

def get_conversation_ids(start_date: str, end_date: str, token: str = None) -> List[int]:
    """
    Step 1: Request API to get list of conversation_ids.
    
    Args:
        start_date: Start date in format DD/MM/YYYY
        end_date: End date in format DD/MM/YYYY
        token: Token parameter (optional, uses hardcoded token if not provided)
    
    Returns:
        List of conversation IDs
    """
    url = "https://robot-api.hacknao.edu.vn/web/admin/api/conversations/ids"
    # Use fixed token: b1812cb7-2513-408b-bb22-d9f91b099fbd
    fixed_token = "b1812cb7-2513-408b-bb22-d9f91b099fbd"
    params = {
        "startDate": start_date,
        "endDate": end_date,
        "token": token or fixed_token
    }
    headers = {
        "accept": "*/*"
    }
    
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    
    data = response.json()
    if data.get("status") == 200:
        return data.get("data", {}).get("conversation_ids", [])
    else:
        raise Exception(f"API error: {data.get('message', 'Unknown error')}")


def get_response_times(conversation_id: int, token: str = None) -> List[Dict[str, Any]]:
    """
    Step 2: Request API to get server response time and LLM response time for a conversation.
    
    Args:
        conversation_id: The conversation ID
        token: Token for monitor API (optional, uses MONITOR_TOKEN if not provided)
    
    Returns:
        List of response time data dictionaries
    """
    url = "https://robot-api.hacknao.edu.vn/robot/api/v1/monitor/conversations/response_time"
    params = {
        "token": token or MONITOR_TOKEN,
        "conversation_id": conversation_id
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    
    data = response.json()
    if data.get("status") == 200:
        return data.get("data", {}).get("data", [])
    else:
        raise Exception(f"API error: {data.get('message', 'Unknown error')}")


def build_output_filename(
    start_date: str,
    end_date: str,
    base_dir: str = ".",
    prefix: str = "response_times"
) -> Path:
    """Generate an output CSV path derived from the requested date range."""
    fmt = "%d/%m/%Y"
    try:
        start = datetime.strptime(start_date, fmt)
        end = datetime.strptime(end_date, fmt)
    except ValueError as exc:
        raise ValueError(
            "Dates must follow DD/MM/YYYY format for automatic naming"
        ) from exc

    filename = f"{prefix}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    return (Path(base_dir).expanduser() / filename).resolve()


def save_response_times(rows: List[Dict[str, Any]], output_path: Path) -> Path:
    """Save raw response time rows to a CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        output_path.write_text("")
        print(f"No response time data found. Created empty file at {output_path}")
        return output_path

    fieldnames = sorted({key for row in rows for key in row.keys()})

    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows to {output_path}")
    return output_path


def calculate_response_time_percentiles(
    start_date: str,
    end_date: str,
    auth_token: str,
    monitor_token: str = None,
    output_file: str | None = None,
    output_dir: str = ".",
    output_prefix: str = "response_times"
) -> Dict:
    """
    Main function to calculate p90 and p99 percentiles for server and LLM response times.
    
    Args:
        start_date: Start date in format DD/MM/YYYY
        end_date: End date in format DD/MM/YYYY
        auth_token: Token for API
        monitor_token: Token for API (optional, same as auth_token)
    
    Returns:
        Dictionary containing p90 and p99 values for both metrics
    """
    # Step 1: Get list of conversation_ids
    # Note: get_conversation_ids uses fixed_token internally (b1812cb7-2513-408b-bb22-d9f91b099fbd)
    # auth_token parameter is ignored
    print("Step 1: Fetching conversation IDs...")
    conversation_ids = get_conversation_ids(start_date, end_date)
    print(f"Found {len(conversation_ids)} conversations")
    
    # Step 2: Collect all response times
    print("Step 2: Fetching response times for each conversation...")
    server_response_times = []
    llm_response_times = []
    raw_rows: List[Dict[str, Any]] = []
    
    # Use MONITOR_TOKEN for response_time API
    monitor_token = monitor_token or auth_token or MONITOR_TOKEN
    for idx, conv_id in enumerate(conversation_ids, 1):
        try:
            response_data = get_response_times(conv_id, monitor_token)
            for item in response_data:
                row = {"conversation_id": conv_id}
                if isinstance(item, dict):
                    row.update(item)

                    if (
                        "server_response_time" in item
                        and item["server_response_time"] is not None
                    ):
                        server_response_times.append(item["server_response_time"])

                    if (
                        "llm_response_time" in item
                        and item["llm_response_time"] is not None
                    ):
                        llm_response_times.append(item["llm_response_time"])

                raw_rows.append(row)
            
            if idx % 100 == 0:
                print(f"Processed {idx}/{len(conversation_ids)} conversations...")
        except Exception as e:
            print(f"Error processing conversation {conv_id}: {e}")
            continue
    
    print(f"Collected {len(server_response_times)} server response times")
    print(f"Collected {len(llm_response_times)} LLM response times")
    
    # Step 3: Save raw data before calculating percentiles
    print("Step 3: Saving raw response times to file...")
    if output_file:
        output_path = Path(output_file).expanduser().resolve()
    else:
        output_path = build_output_filename(
            start_date=start_date,
            end_date=end_date,
            base_dir=output_dir,
            prefix=output_prefix,
        )

    output_path = save_response_times(raw_rows, output_path)

    # Step 4: Calculate p90 and p99
    print("Step 4: Calculating percentiles...")
    results = {
        "server_response_time": {
            "p90": calculate_percentiles(server_response_times, 90),
            "p99": calculate_percentiles(server_response_times, 99)
        },
        "llm_response_time": {
            "p90": calculate_percentiles(llm_response_times, 90),
            "p99": calculate_percentiles(llm_response_times, 99)
        },
        "sample_sizes": {
            "server_response_time": len(server_response_times),
            "llm_response_time": len(llm_response_times)
        },
        "output_file": str(output_path)
    }
    
    # Step 5: Print results
    print("\n" + "="*50)
    print("RESULTS (in milliseconds)")
    print("="*50)
    print(f"\nServer Response Time:")
    print(f"  P90: {results['server_response_time']['p90']:.2f} ms")
    print(f"  P99: {results['server_response_time']['p99']:.2f} ms")
    print(f"  Sample size: {results['sample_sizes']['server_response_time']}")
    
    print(f"\nLLM Response Time:")
    print(f"  P90: {results['llm_response_time']['p90']:.2f} ms")
    print(f"  P99: {results['llm_response_time']['p99']:.2f} ms")
    print(f"  Sample size: {results['sample_sizes']['llm_response_time']}")
    print("="*50 + "\n")
    print(f"Raw data saved to: {results['output_file']}")
    
    return results


if __name__ == "__main__":
    import sys
    
    # Configuration
    # Note: AUTH_TOKEN is the short token (b1812cb7-2513-408b-bb22-d9f91b099fbd) for conversations/ids
    # MONITOR_TOKEN is for monitor API (response_time, conversations)
    AUTH_TOKEN = "b1812cb7-2513-408b-bb22-d9f91b099fbd"
    MONITOR_TOKEN = "dd4e758e-51ed-d9fb-7b25-1e4f704f4cea"
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "scheduler":
            # Run scheduler for daily jobs
            logger.info("Starting scheduler mode...")
            run_time = sys.argv[2] if len(sys.argv) > 2 else "02:00"
            metric_type = sys.argv[3] if len(sys.argv) > 3 else "learn"
            run_scheduler(AUTH_TOKEN, MONITOR_TOKEN, run_time=run_time, metric_type=metric_type)
        
        elif command == "daily":
            # Run daily job manually
            logger.info("Running daily job manually...")
            metric_type = sys.argv[2] if len(sys.argv) > 2 else "learn"
            daily_job(AUTH_TOKEN, MONITOR_TOKEN, metric_type=metric_type)
        
        elif command == "refresh":
            # Refresh UI metrics
            logger.info("Refreshing UI metrics...")
            bot_id = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
            results = refresh_ui_metrics(bot_id)
            
            print("\n" + "="*50)
            print("UI METRICS REFRESH RESULTS (Last 7 Days)")
            print("="*50)
            print(f"\nDate Range: {results['date_range']['start_date']} to {results['date_range']['end_date']}")
            print(f"\nDaily Metrics: {len(results['daily_metrics'])} days")
            
            for metric in results['daily_metrics']:
                print(f"\n  Date: {metric['date_time']}, Bot ID: {metric['bot_id']}")
                if metric['server_response_p90'] is not None:
                    print(f"    Server Response: P90={metric['server_response_p90']:.2f} ms, P99={metric['server_response_p99']:.2f} ms")
                if metric['llm_response_p90'] is not None:
                    print(f"    LLM Response: P90={metric['llm_response_p90']:.2f} ms, P99={metric['llm_response_p99']:.2f} ms")
                if metric['fast_response_p90'] is not None:
                    print(f"    Fast Response: P90={metric['fast_response_p90']:.2f} ms, P99={metric['fast_response_p99']:.2f} ms")
                print(f"    Total Records: {metric['total_records']}")
            print("="*50 + "\n")
        
        elif command == "test":
            # Test database connection
            logger.info("Testing database connection...")
            conn = get_db_connection()
            conn.close()
            logger.info("Database test completed successfully")
        
        else:
            print("Usage:")
            print("  python evaluate.py scheduler [time]  - Run daily scheduler (default: 02:00)")
            print("  python evaluate.py daily             - Run daily job manually")
            print("  python evaluate.py refresh [bot_id]  - Refresh UI metrics")
            print("  python evaluate.py test              - Test database connection")
    else:
        # Default: Example usage with CSV export (original functionality)
        START_DATE = "07/11/2025"
        END_DATE = "07/11/2025"
        OUTPUT_DIR = "data"
        OUTPUT_PREFIX = "response_times"
        
        calculate_response_time_percentiles(
            start_date=START_DATE,
            end_date=END_DATE,
            auth_token=AUTH_TOKEN,
            monitor_token=MONITOR_TOKEN,
            output_dir=OUTPUT_DIR,
            output_prefix=OUTPUT_PREFIX
        )
