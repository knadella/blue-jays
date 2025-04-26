import os
from datetime import datetime
import pandas as pd
from pybaseball import statcast_batter
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

def fetch_statcast_data(start_date, end_date):
    """Fetch Statcast data for Blue Jays batters."""
    # Blue Jays team ID is 141
    blue_jays_batters = statcast_batter(start_date, end_date, team=141)
    return blue_jays_batters

def process_data(df):
    """Process and clean the Statcast data."""
    # Add any necessary data processing steps here
    return df

def save_to_db(df, db_url):
    """Save processed data to database."""
    engine = create_engine(db_url)
    df.to_sql('statcast_data', engine, if_exists='replace', index=False)

def main():
    start_date = os.getenv('STATCAST_START')
    end_date = os.getenv('STATCAST_END')
    db_url = os.getenv('DB_URL')

    if not all([start_date, end_date, db_url]):
        raise ValueError("Missing required environment variables")

    print(f"Fetching Statcast data from {start_date} to {end_date}")
    raw_data = fetch_statcast_data(start_date, end_date)
    
    print("Processing data...")
    processed_data = process_data(raw_data)
    
    print("Saving to database...")
    save_to_db(processed_data, db_url)
    
    print("ETL process completed successfully")

if __name__ == "__main__":
    main() 