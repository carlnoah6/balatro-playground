#!/usr/bin/env python3
"""Debug shop RNG by comparing actual game data with simulator predictions."""

import os
import sys
import json
from pathlib import Path

# Add simulator to path
sys.path.insert(0, str(Path(__file__).parent / "simulator"))

from balatro_sim.shop import generate_shop, ShopConfig
from balatro_sim.rng import RNGState
import psycopg2

# Database connection
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

def fetch_sample_shops(limit=5):
    """Fetch sample shop records from database."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    query = """
    SELECT 
        r.seed,
        gl.ante,
        gl.shop_state
    FROM balatro_game_log gl
    JOIN balatro_runs r ON gl.run_id = r.id
    WHERE gl.shop_state IS NOT NULL
    AND gl.ante <= 3
    ORDER BY r.created_at DESC
    LIMIT %s
    """
    
    cur.execute(query, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    return rows

def compare_shop(seed: str, ante: int, actual_shop):
    """Compare actual shop with simulator prediction."""
    print(f"\n{'='*80}")
    print(f"Seed: {seed}, Ante: {ante}")
    print(f"{'='*80}")
    
    # Generate predicted shop
    rng = RNGState(seed)
    config = ShopConfig()
    predicted_shop = generate_shop(rng, config, ante)
    
    # Extract actual items
    actual_items = []
    if isinstance(actual_shop, list):
        for item in actual_shop:
            item_type = item.get("type", "?")
            item_name = item.get("name", item.get("key", "?"))
            actual_items.append((item_type, item_name))
    
    # Extract predicted items
    predicted_items = []
    for item in predicted_shop.card_slots:
        if hasattr(item, 'rarity'):  # Joker
            predicted_items.append(("Joker", item.name))
        else:  # Consumable
            predicted_items.append(("Consumable", item.name))
    if predicted_shop.voucher:
        predicted_items.append(("Voucher", predicted_shop.voucher.name))
    for item in predicted_shop.packs:
        predicted_items.append(("Booster Pack", item.name))
    
    # Compare
    print("\nActual Shop:")
    for i, (typ, name) in enumerate(actual_items):
        print(f"  {i+1}. [{typ}] {name}")
    
    print("\nPredicted Shop:")
    for i, (typ, name) in enumerate(predicted_items):
        match = "✅" if i < len(actual_items) and (typ, name) == actual_items[i] else "❌"
        print(f"  {i+1}. [{typ}] {name} {match}")
    
    # Calculate match rate
    matches = sum(1 for i in range(min(len(actual_items), len(predicted_items)))
                  if actual_items[i] == predicted_items[i])
    total = max(len(actual_items), len(predicted_items))
    match_rate = matches / total * 100 if total > 0 else 0
    
    print(f"\nMatch Rate: {matches}/{total} ({match_rate:.1f}%)")
    
    return match_rate

def main():
    print("Fetching sample shops from database...")
    shops = fetch_sample_shops(limit=5)
    
    if not shops:
        print("No shops found in database")
        return
    
    total_rate = 0
    count = 0
    
    for seed, ante, shop_state in shops:
        if shop_state:
            rate = compare_shop(seed, ante, shop_state)
            total_rate += rate
            count += 1
    
    if count > 0:
        avg_rate = total_rate / count
        print(f"\n{'='*80}")
        print(f"Average Match Rate: {avg_rate:.1f}%")
        print(f"{'='*80}")

if __name__ == "__main__":
    main()
