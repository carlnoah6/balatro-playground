#!/usr/bin/env python3
"""验证 shop RNG 修复后的准确率 — 带游戏状态追踪"""

import os
import sys
import json
import psycopg2
from urllib.parse import urlparse
from collections import defaultdict
from balatro_sim.shop import generate_shop, ShopConfig
from balatro_sim.rng import RNGState
from balatro_sim.game_state import extract_game_state_at_shops


def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    result = urlparse(db_url)
    return psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )


def normalize_shop_items(shop_state):
    items = []
    for item in shop_state:
        item_type = item.get('type', '')
        name = item.get('name', '')
        items.append((item_type, name))
    return sorted(items)


def main():
    use_state = '--no-state' not in sys.argv
    mode_label = "WITH game state" if use_state else "WITHOUT game state"
    print(f"验证 shop RNG 准确率 ({mode_label})")
    print("=" * 60)

    conn = get_db_connection()
    cur = conn.cursor()

    # Get all seeds
    cur.execute("""
        SELECT DISTINCT r.seed, r.id
        FROM balatro_runs r
        JOIN balatro_game_log g ON g.run_id = r.id
        WHERE g.shop_state IS NOT NULL
        ORDER BY r.seed
    """)
    seeds = cur.fetchall()
    print(f"找到 {len(seeds)} 个种子\n")

    total = 0
    correct = 0
    by_ante = defaultdict(lambda: {'total': 0, 'correct': 0})
    by_type = defaultdict(lambda: {'total': 0, 'correct': 0})
    mismatches = []

    for seed, run_id in seeds:
        # Get full game log for this run (for state tracking)
        cur.execute("""
            SELECT g.seq, g.ante, g.phase, g.action, g.hand_type, g.jokers,
                   g.shop_state IS NOT NULL as has_shop
            FROM balatro_game_log g
            WHERE g.run_id = %s
            ORDER BY g.seq
        """, (run_id,))
        all_rows = cur.fetchall()

        # Extract game state at each shop visit
        if use_state:
            shop_states = extract_game_state_at_shops(all_rows)
        else:
            shop_states = {}

        # Get shop entries (first per ante)
        cur.execute("""
            WITH ranked AS (
                SELECT g.seq, g.ante, g.shop_state,
                       ROW_NUMBER() OVER (PARTITION BY g.ante ORDER BY g.seq) as rn
                FROM balatro_game_log g
                WHERE g.run_id = %s AND g.shop_state IS NOT NULL
            )
            SELECT seq, ante, shop_state FROM ranked WHERE rn = 1
            ORDER BY ante
        """, (run_id,))

        for seq, ante, actual_shop in cur.fetchall():
            if isinstance(actual_shop, str):
                actual_shop = json.loads(actual_shop)

            total += 1
            by_ante[ante]['total'] += 1

            try:
                rng = RNGState(seed)

                if use_state and seq in shop_states:
                    config = shop_states[seq].to_shop_config(ante)
                else:
                    config = ShopConfig()
                    if ante > 2:
                        config.first_shop_buffoon = True

                predicted_shop_state = generate_shop(rng, config, ante)

                # Build comparable format
                predicted_shop = []
                for item in predicted_shop_state.card_slots:
                    if hasattr(item, 'card_type'):
                        predicted_shop.append({'type': item.card_type, 'name': item.name})
                    else:
                        predicted_shop.append({'type': 'Joker', 'name': item.name})

                if predicted_shop_state.voucher:
                    predicted_shop.append({'type': 'Voucher', 'name': predicted_shop_state.voucher.name})

                for pack in predicted_shop_state.packs:
                    predicted_shop.append({'type': 'Booster', 'name': pack.name})

                pred_norm = normalize_shop_items(predicted_shop)
                actual_norm = normalize_shop_items(actual_shop)

                if pred_norm == actual_norm:
                    correct += 1
                    by_ante[ante]['correct'] += 1
                else:
                    # Per-item comparison
                    pred_cards = [(t, n) for t, n in pred_norm if t not in ('Booster', 'Voucher')]
                    actual_cards = [(t, n) for t, n in actual_norm if t not in ('Booster', 'Voucher')]
                    pred_packs = [(t, n) for t, n in pred_norm if t == 'Booster']
                    actual_packs = [(t, n) for t, n in actual_norm if t == 'Booster']
                    pred_voucher = [(t, n) for t, n in pred_norm if t == 'Voucher']
                    actual_voucher = [(t, n) for t, n in actual_norm if t == 'Voucher']

                    mismatches.append({
                        'seed': seed, 'ante': ante, 'seq': seq,
                        'pred_cards': pred_cards, 'actual_cards': actual_cards,
                        'pred_packs': pred_packs, 'actual_packs': actual_packs,
                        'pred_voucher': pred_voucher, 'actual_voucher': actual_voucher,
                        'state_info': f"used_jokers={list(shop_states[seq].used_jokers.keys())}" if use_state and seq in shop_states else "no state",
                    })

                # Per-type accuracy
                for category, pred_list, actual_list in [
                    ('Cards', [(t,n) for t,n in pred_norm if t not in ('Booster','Voucher')],
                              [(t,n) for t,n in actual_norm if t not in ('Booster','Voucher')]),
                    ('Packs', [(t,n) for t,n in pred_norm if t == 'Booster'],
                              [(t,n) for t,n in actual_norm if t == 'Booster']),
                    ('Voucher', [(t,n) for t,n in pred_norm if t == 'Voucher'],
                                [(t,n) for t,n in actual_norm if t == 'Voucher']),
                ]:
                    by_type[category]['total'] += 1
                    if pred_list == actual_list:
                        by_type[category]['correct'] += 1

            except Exception as e:
                mismatches.append({'seed': seed, 'ante': ante, 'error': str(e)})

    conn.close()

    # Results
    print("\n" + "=" * 60)
    acc = 100 * correct / total if total else 0
    print(f"总体准确率: {correct}/{total} ({acc:.1f}%)")

    print("\n按 Ante:")
    for ante in sorted(by_ante.keys()):
        s = by_ante[ante]
        print(f"  Ante {ante}: {s['correct']}/{s['total']} ({100*s['correct']/s['total']:.1f}%)")

    print("\n按类型:")
    for cat in ('Cards', 'Packs', 'Voucher'):
        if cat in by_type:
            s = by_type[cat]
            print(f"  {cat}: {s['correct']}/{s['total']} ({100*s['correct']/s['total']:.1f}%)")

    if mismatches:
        print(f"\n不匹配 ({len(mismatches)} 个, 显示前 10):")
        for i, m in enumerate(mismatches[:10]):
            print(f"\n  [{m['seed']} ante {m['ante']}]")
            if 'error' in m:
                print(f"    错误: {m['error']}")
            else:
                if m.get('pred_cards') != m.get('actual_cards'):
                    print(f"    Cards: pred={m['pred_cards']}")
                    print(f"           actual={m['actual_cards']}")
                if m.get('pred_packs') != m.get('actual_packs'):
                    print(f"    Packs: pred={m['pred_packs']}")
                    print(f"           actual={m['actual_packs']}")
                if m.get('pred_voucher') != m.get('actual_voucher'):
                    print(f"    Voucher: pred={m['pred_voucher']}")
                    print(f"             actual={m['actual_voucher']}")
                print(f"    State: {m.get('state_info', 'N/A')}")

    print("\n" + "=" * 60)
    return acc


if __name__ == '__main__':
    accuracy = main()
