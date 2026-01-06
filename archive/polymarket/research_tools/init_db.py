"""Initialize the trading-lab database."""
from src.storage import db

if __name__ == "__main__":
    print("Initializing trading-lab database...")
    db.initialize()
    
    # Verify tables were created
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    
    print("\n✓ Created tables:")
    for table in tables:
        print(f"  - {table[0]}")
    
    print(f"\n✓ Database ready at: {db.db_path}")
