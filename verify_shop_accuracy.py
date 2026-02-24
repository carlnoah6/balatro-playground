#!/usr/bin/env python3
"""验证修复后的 shop 预测准确率

从 Neon 数据库提取实际游戏中的 shop 数据，
用修复后的模拟器预测相同的 seed/ante 的 shop，
计算准确率并生成报告。
"""
import json
import sys
import os
from collections import defaultdict
from typing import Dict, List, Tuple

import psycopg2

# Add simulator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'simulator'))

from balatro_sim.rng import RNGState
from balatro_sim.shop import generate_shop, ShopConfig


def get_db_url():
    config_path = "/home/ubuntu/.openclaw/workspace/data/neon-config.json"
    with open(config_path) as f:
        return json.load(f)["database_url"]


def extract_shop_data():
    """从数据库提取 shop 数据"""
    conn = psycopg2.connect(get_db_url())
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT gl.run_id, gl.ante, gl.shop_state, r.seed
        FROM balatro_game_log gl
        JOIN balatro_runs r ON gl.run_id = r.id
        WHERE gl.shop_state IS NOT NULL
        ORDER BY gl.run_id, gl.ante
    """)
    
    records = []
    for row in cursor.fetchall():
        run_id, ante, shop_state, seed = row
        records.append({
            'run_id': run_id,
            'ante': ante,
            'seed': seed,
            'actual_shop': shop_state
        })
    
    conn.close()
    return records


def predict_shop(seed: str, ante: int):
    """用模拟器预测 shop"""
    rng = RNGState(seed)
    config = ShopConfig()
    shop = generate_shop(rng, config, ante)
    
    items = []
    
    # 添加 card_slots（Jokers 和 Consumables）
    for item in shop.card_slots:
        if hasattr(item, 'joker_def'):
            items.append({
                'type': 'Joker',
                'name': item.joker_def.name,
                'cost': item.cost,
            })
        elif hasattr(item, 'name'):
            items.append({
                'type': 'Consumable',
                'name': item.name,
                'cost': getattr(item, 'cost', 0),
            })
    
    # 添加 voucher
    if shop.voucher:
        items.append({
            'type': 'Voucher',
            'name': shop.voucher.name,
            'cost': 10,  # Vouchers 通常是 10
        })
    
    # 添加 packs
    for pack in (shop.packs or []):
        pack_name = getattr(pack, 'name', str(pack))
        items.append({
            'type': 'Booster',
            'name': pack_name,
            'cost': getattr(pack, 'cost', 4),
        })
    
    return {'items': items}


def compare_shops(actual, predicted):
    """对比实际和预测的 shop
    
    返回：
    - name_matches: 名称匹配的物品数
    - order_matches: 名称+顺序都匹配的物品数
    - total: 总物品数
    """
    actual_items = actual['items']
    predicted_items = predicted['items']
    
    total = len(actual_items)
    name_matches = 0
    order_matches = 0
    
    # 统计名称匹配
    actual_names = {item['name'] for item in actual_items}
    predicted_names = {item['name'] for item in predicted_items}
    name_matches = len(actual_names & predicted_names)
    
    # 统计顺序匹配
    for i in range(min(len(actual_items), len(predicted_items))):
        if actual_items[i]['name'] == predicted_items[i]['name']:
            order_matches += 1
    
    return {
        'name_matches': name_matches,
        'order_matches': order_matches,
        'total': total,
        'actual_items': actual_items,
        'predicted_items': predicted_items,
    }


def calculate_accuracy(records):
    """计算准确率"""
    by_ante = defaultdict(lambda: {
        'count': 0,
        'name_matches': 0,
        'order_matches': 0,
        'total_items': 0,
        'examples': []
    })
    
    for record in records:
        ante = record['ante']
        actual = {'items': record['actual_shop']}
        predicted = predict_shop(record['seed'], ante)
        
        comparison = compare_shops(actual, predicted)
        
        by_ante[ante]['count'] += 1
        by_ante[ante]['name_matches'] += comparison['name_matches']
        by_ante[ante]['order_matches'] += comparison['order_matches']
        by_ante[ante]['total_items'] += comparison['total']
        
        # 保存前3个案例
        if len(by_ante[ante]['examples']) < 3:
            by_ante[ante]['examples'].append({
                'seed': record['seed'],
                'run_id': record['run_id'],
                'actual': comparison['actual_items'],
                'predicted': comparison['predicted_items'],
            })
    
    return by_ante


def generate_report(records, by_ante):
    """生成 markdown 报告"""
    report = []
    report.append("# Shop 预测准确率报告\n")
    
    # 数据概览
    report.append("## 数据概览\n")
    report.append(f"- 总记录数：{len(records)}")
    unique_runs = len(set(r['run_id'] for r in records))
    report.append(f"- 覆盖 runs：{unique_runs}")
    unique_antes = sorted(set(r['ante'] for r in records))
    report.append(f"- 覆盖 antes：{unique_antes}\n")
    
    # 按 ante 统计
    report.append("## 准确率（按 ante 分组）\n")
    
    for ante in sorted(by_ante.keys()):
        stats = by_ante[ante]
        name_rate = stats['name_matches'] / stats['total_items'] * 100 if stats['total_items'] > 0 else 0
        order_rate = stats['order_matches'] / stats['total_items'] * 100 if stats['total_items'] > 0 else 0
        
        report.append(f"### Ante {ante}\n")
        report.append(f"- 记录数：{stats['count']}")
        report.append(f"- 总物品数：{stats['total_items']}")
        report.append(f"- 物品名称匹配率：{name_rate:.1f}%")
        report.append(f"- 物品顺序匹配率：{order_rate:.1f}%\n")
        
        # 典型案例
        if stats['examples']:
            report.append("**典型案例：**\n")
            for i, ex in enumerate(stats['examples'][:2], 1):
                report.append(f"案例 {i} (seed: {ex['seed']}, run: {ex['run_id']}):")
                report.append(f"- 实际：{[item['name'] for item in ex['actual']]}")
                report.append(f"- 预测：{[item['name'] for item in ex['predicted']]}\n")
    
    # 总体统计
    report.append("## 总体统计\n")
    total_name_matches = sum(s['name_matches'] for s in by_ante.values())
    total_order_matches = sum(s['order_matches'] for s in by_ante.values())
    total_items = sum(s['total_items'] for s in by_ante.values())
    
    overall_name_rate = total_name_matches / total_items * 100 if total_items > 0 else 0
    overall_order_rate = total_order_matches / total_items * 100 if total_items > 0 else 0
    
    report.append(f"- 总物品数：{total_items}")
    report.append(f"- 总体名称匹配率：{overall_name_rate:.1f}%")
    report.append(f"- 总体顺序匹配率：{overall_order_rate:.1f}%\n")
    
    return "\n".join(report)


if __name__ == "__main__":
    print("正在提取数据库中的 shop 数据...")
    records = extract_shop_data()
    print(f"提取到 {len(records)} 条 shop 记录")
    
    print("\n正在计算准确率...")
    by_ante = calculate_accuracy(records)
    
    print("\n正在生成报告...")
    report = generate_report(records, by_ante)
    
    output_path = "shop_accuracy_report.md"
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\n报告已生成：{output_path}")
    print("\n" + "="*60)
    print(report)
