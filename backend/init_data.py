#!/usr/bin/env python3
"""
Script to initialize data for the last 3 days
Run this script to fetch and save data for the last 3 days into database
"""

import sys
from datetime import date, timedelta
from evaluate import daily_job, logger

# Configuration
AUTH_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiMDE5NTFlOTgtZTMzOC03NzRjLWEzM2ItNjdjNWNlOWQ5NzQ2IiwicGhvbmUiOiIwODY5NjEzMTA4IiwianRpIjoiNEpkUGh1OVd3WHYySkp1Ym1sTHI1XzAxOTUxZTk4LWUzMzgtNzc0Yy1hMzNiLTY3YzVjZTlkOTc0NiIsImF1dGhvcml0aWVzIjpbIlVTRVIiXSwiaWF0IjoxNzYyMzM1Mzg5LCJleHAiOjE3NjMxOTkzODl9.BWI8Th5p2P3pNv8M5YcUs7wZqF_prExsXdj74h4oXVs"
MONITOR_TOKEN = "dd4e758e-51ed-d9fb-7b25-1e4f704f4cea"

def init_data(days=3):
    """
    Fetch and save data for the last N days into database.
    
    Args:
        days: Number of days to fetch (default: 3)
    """
    print("="*60)
    print("🚀 Initializing Data for Last {} Days".format(days))
    print("="*60)
    print()
    
    today = date.today()
    success_count = 0
    error_count = 0
    
    for day_offset in range(1, days + 1):
        target_date = today - timedelta(days=day_offset)
        date_str = target_date.strftime("%Y-%m-%d")
        
        print(f"\n📅 Processing date: {date_str} (Day {day_offset} ago)")
        print("-" * 60)
        
        try:
            daily_job(AUTH_TOKEN, MONITOR_TOKEN, target_date=target_date, metric_type="learn")
            success_count += 1
            print(f"✅ Successfully processed {date_str}")
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Error processing {date_str}: {e}")
            print(f"❌ Error processing {date_str}: {e}")
            continue
    
    print()
    print("="*60)
    print("📊 Summary")
    print("="*60)
    print(f"✅ Success: {success_count} days")
    print(f"❌ Errors: {error_count} days")
    print(f"📅 Total: {days} days")
    print()
    
    if success_count > 0:
        print("✅ Data initialization completed!")
        print("   You can now view the dashboard with data.")
    else:
        print("⚠️  No data was fetched. Please check the errors above.")
    
    print("="*60)

if __name__ == "__main__":
    # Get number of days from command line argument or use default
    days = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    
    print(f"Starting data initialization for last {days} days...")
    print()
    
    init_data(days)


