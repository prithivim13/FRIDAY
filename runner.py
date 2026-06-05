import subprocess
import sys
from fetch_eod import run_fetcher
from adjust_corporate_actions import run_adjustments

def main():
    print("Running Phase 1 Pipeline...")
    print("1. Fetching EOD data...")
    # Fetching data for a small range to keep it quick for testing
    run_fetcher(db_path="test.db", start_date="2024-05-01", end_date="2024-06-05")

    print("2. Adjusting corporate actions...")
    run_adjustments(db_path="test.db")

    print("Phase 1 data pipeline completed successfully.")

if __name__ == "__main__":
    main()
