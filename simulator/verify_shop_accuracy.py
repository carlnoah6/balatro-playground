#!/usr/bin/env python3
"""验证 shop RNG 修复后的准确率"""

import os
import sys
import psycopg2
from urllib.parse import urlparse
from collections import defaultdict
from balatro_sim.shop import generate_shop, ShopConfig
from balatro_sim.rng import RNGState

def get_db_connection():
    """获取数据库连接"""
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
    """标准化 shop 物品列表，只保留名称和类型"""
    items = []
    for item in shop_state:
        item_type = item.get('type', '')
        name = item.get('name', '')
        items.append((item_type, name))
    return sorted(items)

def compare_shops(predicted, actual):
    """比较预测和实际的 shop"""
    pred_items = normalize_shop_items(predicted)
    actual_items = normalize_shop_items(actual)
    return pred_items == actual_items

def main():
    print("开始验证 shop RNG 准确率...")
    print("=" * 60)
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 获取所有有 shop_state 的记录（只取每个 run+ante 的第一条）
    cur.execute("""
        WITH ranked_shops AS (
            SELECT 
                g.run_id, 
                g.ante, 
                g.shop_state, 
                r.seed,
                ROW_NUMBER() OVER (PARTITION BY g.run_id, g.ante ORDER BY g.seq) as rn
            FROM balatro_game_log g
            JOIN balatro_runs r ON g.run_id = r.id
            WHERE g.shop_state IS NOT NULL
        )
        SELECT run_id, ante, shop_state, seed
        FROM ranked_shops
        WHERE rn = 1
        ORDER BY run_id, ante
    """)
    
    records = cur.fetchall()
    print(f"找到 {len(records)} 条 shop 记录\n")
    
    # 统计结果
    total = 0
    correct = 0
    by_ante = defaultdict(lambda: {'total': 0, 'correct': 0})
    mismatches = []
    
    for run_id, ante, actual_shop, seed in records:
        total += 1
        by_ante[ante]['total'] += 1
        
        # 使用模拟器预测
        try:
            # 初始化 RNG 和配置
            rng = RNGState(seed)
            config = ShopConfig()
            
            predicted_shop_state = generate_shop(rng, config, ante)
            
            # 转换为可比较的格式
            predicted_shop = []
            for item in predicted_shop_state.card_slots:
                if item:
                    # 检查是 Joker 还是 Consumable
                    if hasattr(item, 'card_type'):
                        # ShopConsumable (Tarot/Planet/Spectral)
                        predicted_shop.append({
                            'type': item.card_type,
                            'name': item.name
                        })
                    else:
                        # ShopJoker
                        predicted_shop.append({
                            'type': 'Joker',
                            'name': item.name
                        })
            
            if predicted_shop_state.voucher:
                predicted_shop.append({
                    'type': 'Voucher',
                    'name': predicted_shop_state.voucher.name
                })
            
            for pack in predicted_shop_state.packs:
                if pack:
                    predicted_shop.append({
                        'type': 'Booster',
                        'name': pack.name
                    })
            
            # 比较
            if compare_shops(predicted_shop, actual_shop):
                correct += 1
                by_ante[ante]['correct'] += 1
            else:
                # 记录不匹配的案例
                mismatches.append({
                    'run_id': run_id,
                    'seed': seed,
                    'ante': ante,
                    'predicted': normalize_shop_items(predicted_shop),
                    'actual': normalize_shop_items(actual_shop)
                })
        except Exception as e:
            print(f"错误 (run_id={run_id}, seed={seed}, ante={ante}): {e}")
            mismatches.append({
                'run_id': run_id,
                'seed': seed,
                'ante': ante,
                'error': str(e)
            })
    
    conn.close()
    
    # 输出结果
    print("\n" + "=" * 60)
    print("总体准确率:")
    print(f"  正确: {correct}/{total} ({100*correct/total:.1f}%)")
    
    print("\n按 Ante 统计:")
    for ante in sorted(by_ante.keys()):
        stats = by_ante[ante]
        acc = 100 * stats['correct'] / stats['total']
        print(f"  Ante {ante}: {stats['correct']}/{stats['total']} ({acc:.1f}%)")
    
    # 输出不匹配案例（最多 10 个）
    if mismatches:
        print(f"\n不匹配案例 (显示前 10 个):")
        for i, case in enumerate(mismatches[:10]):
            print(f"\n案例 {i+1}:")
            print(f"  Run ID: {case['run_id']}")
            print(f"  Seed: {case['seed']}")
            print(f"  Ante: {case['ante']}")
            if 'error' in case:
                print(f"  错误: {case['error']}")
            else:
                print(f"  预测: {case['predicted']}")
                print(f"  实际: {case['actual']}")
    
    print("\n" + "=" * 60)
    return correct / total if total > 0 else 0

if __name__ == '__main__':
    accuracy = main()
    sys.exit(0 if accuracy > 0.5 else 1)
